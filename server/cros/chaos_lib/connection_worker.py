# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import time

from autotest_lib.server import hosts
from autotest_lib.server.cros.network import wifi_client
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.network import iw_runner
from autotest_lib.client.common_lib.cros.network import ping_runner
from autotest_lib.client.common_lib.cros.network import xmlrpc_datatypes

WORK_CLIENT_CONNECTION_RETRIES = 3
WAIT_FOR_CONNECTION = 10

class ConnectionWorker(object):
    """ ConnectionWorker is a thin layer of interfaces for worker classes """

    @property
    def name(self):
        """@return a string: representing name of the worker class"""
        raise NotImplementedError('Missing subclass implementation')


    def prepare_work_client(self, work_client_machine):
        """Prepare the SSHHost object into WiFiClient object

        @param work_client_machine: a SSHHost object to be wrapped

        """
        work_client_host = hosts.create_host(work_client_machine.hostname)
        # All packet captures in chaos lab have dual NICs. Let us use phy1 to
        # be a radio dedicated for work client
        iw = iw_runner.IwRunner(remote_host=work_client_host)
        phys = iw.list_phys()
        devs = iw.list_interfaces(desired_if_type='managed')
        if len(devs) > 0:
            logging.debug('Removing interfaces in work host machine %s', devs)
            for i in range(len(devs)):
                iw.remove_interface(devs[i].if_name)
        if len(phys) > 1:
            logging.debug('Adding interfaces in work host machine')
            iw.add_interface('phy1', 'work0', 'managed')
            logging.debug('Interfaces in work client %s', iw.list_interfaces())
        elif len(phys) == 1:
            raise error.TestError('Not enough phys available to create a'
                                  'work client interface %s.' %
                                   work_client_host.hostname)
        self.work_client = wifi_client.WiFiClient(work_client_host, './debug')


    def connect_work_client(self, assoc_params):
        """
        Connect client to the AP.

        Tries to connect the work client to AP in WORK_CLIENT_CONNECTION_RETRIES
        tries. If we fail to connect in all tries then we would return False
        otherwise returns True on successful connection to the AP.

        @param assoc_params: an AssociationParameters object.
        @return a boolean: True if work client is successfully connected to AP
                or False on failing to connect to the AP

        """
        if not self.work_client.shill.init_test_network_state():
            logging.error('Failed to set up isolated test context profile for '
                          'work client.')
            return False

        success = False
        for i in range(WORK_CLIENT_CONNECTION_RETRIES):
            logging.info('Connecting work client to AP')
            assoc_result = xmlrpc_datatypes.deserialize(
                           self.work_client.shill.connect_wifi(assoc_params))
            success = assoc_result.success
            if not success:
                logging.error('Connection attempt of work client failed, try %d'
                              ' reason: %s', (i+1), assoc_result.failure_reason)
            else:
                logging.info('Work client connected to the AP')
                self.ssid = assoc_params.ssid
                break
        return success


    def cleanup(self):
        """Teardown work_client"""
        self.work_client.shill.disconnect(self.ssid)
        self.work_client.shill.clean_profiles()


    def run(self, client):
        """Executes the connection worker

        @param client: WiFiClient object representing the DUT

        """
        raise NotImplementedError('Missing subclass implementation')


class ConnectionDuration(ConnectionWorker):
    """This test is to check the liveliness of the connection to the AP. """

    def __init__(self, duration_sec=30):
        """
        Holds WiFi connection open with periodic pings

        @param duration_sec: amount of time to hold connection in seconds

        """

        self.duration_sec = duration_sec


    @property
    def name(self):
        """@return a string: representing name of this class"""
        return 'duration'


    def run(self, client):
        """Periodically pings work client to check liveliness of the connection

        @param client: WiFiClient object representing the DUT

        """
        ping_config = ping_runner.PingConfig(self.work_client.wifi_ip, count=10)
        logging.info('Pinging work client ip: %s', self.work_client.wifi_ip)
        start_time = time.time()
        while time.time() - start_time < self.duration_sec:
            time.sleep(10)
            ping_result = client.ping(ping_config)
            logging.info('Connection liveness %r', ping_result)


class ConnectionSuspend(ConnectionWorker):
    """
    This test is to check the liveliness of the connection to the AP with
    suspend resume cycle involved.

    """

    def __init__(self, suspend_sec=30):
        """
        Construct a ConnectionSuspend.

        @param suspend_sec: amount of time to suspend in seconds

        """

        self._suspend_sec = suspend_sec


    @property
    def name(self):
        """@return a string: representing name of this class"""
        return 'suspend'


    def run(self, client):
        """
        Check the liveliness of the connection to the AP by pinging the work
        client before and after a suspend resume.

        @param client: WiFiClient object representing the DUT

        """
        ping_config = ping_runner.PingConfig(self.work_client.wifi_ip, count=10)
        # pinging work client to ensure we have a connection
        logging.info('work client ip: %s', self.work_client.wifi_ip)
        ping_result = client.ping(ping_config)
        logging.info('before suspend:%r', ping_result)
        client.do_suspend(self._suspend_sec)
        # After resume, DUT could either be in a connected state from before or
        # would be in process of connecting to the AP. Let us wait for five
        # seconds before we start querying the connection state.
        time.sleep(5)

        # Wait for WAIT_FOR_CONNECTION time before trying to ping.
        success, state, elapsed_time = client.wait_for_service_states(
                self.ssid, ('ready', 'portal', 'online'), WAIT_FOR_CONNECTION)
        if not success:
            raise error.TestFail('DUT failed to connect to AP (%s state) after'
                                 'resume in %d seconds' %
                                 (state, WAIT_FOR_CONNECTION))
        else:
            logging.info('DUT entered %s state after %s seconds',
                         state, elapsed_time)
            # ping work client to ensure we have connection after resume.
            ping_result = client.ping(ping_config)
            logging.info('after resume:%r', ping_result)
