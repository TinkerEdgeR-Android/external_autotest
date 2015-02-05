#!/usr/bin/python
#pylint: disable-msg=C0111

# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import logging
import os
import signal
import socket
import time

import common
from autotest_lib.frontend import setup_django_environment
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib import global_config
from autotest_lib.client.common_lib.cros.graphite import autotest_stats
from autotest_lib.frontend.afe import models
from autotest_lib.scheduler import email_manager
from autotest_lib.scheduler import scheduler_lib
from autotest_lib.server.cros.dynamic_suite import frontend_wrappers
from django.db import transaction

"""
Autotest shard client

The shard client can be run as standalone service. It periodically polls the
master in a heartbeat, retrieves new jobs and hosts and inserts them into the
local database.

A shard is set up (by a human) and pointed to the global AFE (cautotest).
On the shard, this script periodically makes so called heartbeat requests to the
global AFE, which will then complete the following actions:

1. Find the previously created (with atest) record for the shard. Shards are
   identified by their hostnames, specified in the shadow_config.
2. Take the records that were sent in the heartbeat and insert them into the
   global database.
   - This is to set the status of jobs to completed in the master database after
     they were run by a slave. This is necessary so one can just look at the
     master's afe to see the statuses of all jobs. Otherwise one would have to
     check the tko tables or the individual slave AFEs.
3. Find labels that have been assigned to this shard.
4. Assign hosts that:
   - have the specified label
   - aren't leased
   - have an id which is not in the known_host_ids which were sent in the
     heartbeat request.
5. Assign jobs that:
   - depend on the specified label
   - haven't been assigned before
   - aren't started yet
   - aren't completed yet
   - have an id which is not in the jobs_known_ids which were sent in the
     heartbeat request.
6. Serialize the chosen jobs and hosts.
   - Find objects that the Host/Job objects depend on: Labels, AclGroups, Users,
     and many more. Details about this can be found around
     model_logic.serialize()
7. Send these objects to the slave.


On the client side, this will happen:
1. Deserialize the objects sent from the master and persist them to the local
   database.
2. monitor_db on the shard will pick up these jobs and schedule them on the
   available hosts (which were retrieved from a heartbeat).
3. Once a job is finished, it's shard_id is set to NULL
4. The shard_client will pick up all jobs where shard_id=NULL and will
   send them to the master in the request of the next heartbeat.
   - The master will persist them as described earlier.
   - the shard_id will be set back to the shard's id, so the record won't be
     uploaded again.
   The heartbeat request will also contain the ids of incomplete jobs and the
   ids of all hosts. This is used to not send objects repeatedly. For more
   information on this and alternatives considered
   see site_rpc_interface.shard_heartbeat.
"""


HEARTBEAT_AFE_ENDPOINT = 'shard_heartbeat'

RPC_TIMEOUT_MIN = 5
RPC_DELAY_SEC = 5

STATS_KEY = 'shard_client.%s' % socket.gethostname()
timer = autotest_stats.Timer(STATS_KEY)
_heartbeat_client = None


class ShardClient(object):
    """Performs client side tasks of sharding, i.e. the heartbeat.

    This class contains the logic to do periodic heartbeats to a global AFE,
    to retrieve new jobs from it and to report completed jobs back.
    """

    def __init__(self, global_afe_hostname, shard_hostname, tick_pause_sec):
        self.afe = frontend_wrappers.RetryingAFE(server=global_afe_hostname,
                                                 timeout_min=RPC_TIMEOUT_MIN,
                                                 delay_sec=RPC_DELAY_SEC)
        self.hostname = shard_hostname
        self.tick_pause_sec = tick_pause_sec
        self._shutdown = False
        self._shard = None


    @timer.decorate
    def process_heartbeat_response(self, heartbeat_response):
        """Save objects returned by a heartbeat to the local database.

        This deseralizes hosts and jobs including their dependencies and saves
        them to the local database.

        @param heartbeat_response: A dictionary with keys 'hosts' and 'jobs',
                                   as returned by the `shard_heartbeat` rpc
                                   call.
        """
        hosts_serialized = heartbeat_response['hosts']
        jobs_serialized = heartbeat_response['jobs']

        autotest_stats.Gauge(STATS_KEY).send(
            'hosts_received', len(hosts_serialized))
        autotest_stats.Gauge(STATS_KEY).send(
            'jobs_received', len(jobs_serialized))

        for host in hosts_serialized:
            with transaction.commit_on_success():
                models.Host.deserialize(host)
        for job in jobs_serialized:
            with transaction.commit_on_success():
                models.Job.deserialize(job)

        job_ids = [j['id'] for j in jobs_serialized]
        logging.info('Heartbeat response contains jobs %s', job_ids)

        # If the master has just sent any jobs that we think have completed,
        # re-sync them with the master. This is especially useful when a
        # heartbeat or job is silently dropped, as the next heartbeat will
        # have a disagreement. Updating the shard_id to NULL will mark these
        # jobs for upload on the next heartbeat.
        models.Job.objects.filter(
                id__in=job_ids,
                hostqueueentry__complete=True).update(shard=None)


    @property
    def shard(self):
        """Return this shard's own shard object, fetched from the database.

        A shard's object is fetched from the master with the first jobs. It will
        not exist before that time.

        @returns: The shard object if it already exists, otherwise None
        """
        if self._shard is None:
            try:
                self._shard = models.Shard.smart_get(self.hostname)
            except models.Shard.DoesNotExist:
                # This might happen before any jobs are assigned to this shard.
                # This is okay because then there is nothing to offload anyway.
                pass
        return self._shard


    def _get_jobs_to_upload(self):
        jobs = []
        # The scheduler sets shard to None upon completion of the job.
        # For more information on the shard field's semantic see
        # models.Job.shard. We need to be careful to wait for both the
        # shard_id and the complete bit here, or we will end up syncing
        # the job without ever setting the complete bit.
        job_ids = list(models.Job.objects.filter(
            shard=None,
            hostqueueentry__complete=True).values_list('pk', flat=True))

        for job_to_upload in models.Job.objects.filter(pk__in=job_ids).all():
            jobs.append(job_to_upload)
        return jobs


    def _mark_jobs_as_uploaded(self, job_ids):
        # self.shard might be None if no jobs were downloaded yet.
        # But then job_ids is empty, so this is harmless.
        # Even if there were jobs we'd in the worst case upload them twice.
        models.Job.objects.filter(pk__in=job_ids).update(shard=self.shard)


    def _get_hqes_for_jobs(self, jobs):
        hqes = []
        for job in jobs:
            hqes.extend(job.hostqueueentry_set.all())
        return hqes


    def _get_known_ids(self):
        """Returns lists of host and job ids to send in a heartbeat.

        The host and job ids are ids of objects that are already present on the
        shard and therefore don't need to be sent again.

        For jobs, only incomplete jobs are sent, as the master won't sent
        already completed jobs anyway. This helps keeping the list of id's
        considerably small.

        @returns: Tuple of two dictionaries. The first one contains job ids, the
                  second one host ids.
        """
        job_ids = list(models.Job.objects.filter(
            hostqueueentry__complete=False).values_list('id', flat=True))
        host_ids = list(models.Host.objects.filter(
                invalid=0).values_list('id', flat=True))
        return job_ids, host_ids


    def _heartbeat_packet(self):
        """Construct the heartbeat packet.

        See site_rpc_interface for a more detailed description of the heartbeat.

        @return: A heartbeat packet.
        """
        known_job_ids, known_host_ids = self._get_known_ids()
        logging.info('Known jobs: %s', known_job_ids)

        job_objs = self._get_jobs_to_upload()
        hqes = [hqe.serialize(include_dependencies=False)
                for hqe in self._get_hqes_for_jobs(job_objs)]
        jobs = [job.serialize(include_dependencies=False) for job in job_objs]
        logging.info('Uploading jobs %s', [j['id'] for j in jobs])

        return {'shard_hostname': self.hostname,
                'known_job_ids': known_job_ids,
                'known_host_ids': known_host_ids,
                'jobs': jobs, 'hqes': hqes}


    @timer.decorate
    def do_heartbeat(self):
        """Perform a heartbeat: Retreive new jobs.

        This function executes a `shard_heartbeat` RPC. It retrieves the
        response of this call and processes the response by storing the returned
        objects in the local database.
        """
        logging.info("Performing heartbeat.")

        packet = self._heartbeat_packet()
        autotest_stats.Gauge(STATS_KEY).send(
                'heartbeat.request_size', len(str(packet)))
        response = self.afe.run(HEARTBEAT_AFE_ENDPOINT, **packet)
        autotest_stats.Gauge(STATS_KEY).send(
                'heartbeat.response_size', len(str(response)))

        self._mark_jobs_as_uploaded([job['id'] for job in packet['jobs']])
        self.process_heartbeat_response(response)
        logging.info("Heartbeat completed.")


    def tick(self):
        """Performs all tasks the shard clients needs to do periodically."""
        self.do_heartbeat()


    def loop(self):
        """Calls tick() until shutdown() is called."""
        while not self._shutdown:
            self.tick()
            time.sleep(self.tick_pause_sec)


    def shutdown(self):
        """Stops the shard client after the current tick."""
        logging.info("Shutdown request received.")
        self._shutdown = True


def handle_signal(signum, frame):
    """Sigint handler so we don't crash mid-tick."""
    _heartbeat_client.shutdown()


def _get_global_afe_hostname():
    """Read the hostname of the global AFE from the global configuration."""
    return global_config.global_config.get_config_value(
            'SHARD', 'global_afe_hostname')


def _get_shard_hostname_and_ensure_running_on_shard():
    """Read the hostname the local shard from the global configuration.

    Raise an exception if run from elsewhere than a shard.

    @raises error.HeartbeatOnlyAllowedInShardModeException if run from
            elsewhere than from a shard.
    """
    hostname = global_config.global_config.get_config_value(
        'SHARD', 'shard_hostname', default=None)
    if not hostname:
        raise error.HeartbeatOnlyAllowedInShardModeException(
            'To run the shard client, shard_hostname must neither be None nor '
            'empty.')
    return hostname


def _get_tick_pause_sec():
    """Read pause to make between two ticks from the global configuration."""
    return global_config.global_config.get_config_value(
        'SHARD', 'heartbeat_pause_sec', type=float)


def get_shard_client():
    """Instantiate a shard client instance.

    Configuration values will be read from the global configuration.

    @returns A shard client instance.
    """
    global_afe_hostname = _get_global_afe_hostname()
    shard_hostname = _get_shard_hostname_and_ensure_running_on_shard()
    tick_pause_sec = _get_tick_pause_sec()
    return ShardClient(global_afe_hostname, shard_hostname, tick_pause_sec)


def main():
    try:
        autotest_stats.Counter(STATS_KEY + 'starts').increment()
        main_without_exception_handling()
    except Exception as e:
        message = 'Uncaught exception; terminating shard_client.'
        email_manager.manager.log_stacktrace(message)
        logging.exception(message)
        autotest_stats.Counter(STATS_KEY + 'uncaught_exceptions').increment()
        raise
    finally:
        email_manager.manager.send_queued_emails()


def main_without_exception_handling():
    parser = argparse.ArgumentParser(description='Shard client.')
    options = parser.parse_args()

    scheduler_lib.setup_logging(
            os.environ.get('AUTOTEST_SCHEDULER_LOG_DIR', None),
            None, timestamped_logfile_prefix='shard_client')

    logging.info("Setting signal handler.")
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logging.info("Starting shard client.")
    global _heartbeat_client
    _heartbeat_client = get_shard_client()
    _heartbeat_client.loop()


if __name__ == '__main__':
    main()
