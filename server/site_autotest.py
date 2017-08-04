# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import tempfile

from autotest_lib.client.common_lib import error, global_config
from autotest_lib.client.common_lib.cros import dev_server
from autotest_lib.server import installable_object, autoserv_parser
from autotest_lib.server import utils as server_utils
from autotest_lib.server.cros.dynamic_suite import tools
from autotest_lib.server.cros.dynamic_suite.constants import JOB_REPO_URL


_PARSER = autoserv_parser.autoserv_parser


class SiteAutotest(installable_object.InstallableObject):
    """Site implementation of Autotest."""

    def get(self, location=None):
        if not location:
            location = os.path.join(self.serverdir, '../client')
            location = os.path.abspath(location)
        installable_object.InstallableObject.get(self, location)
        self.got = True


    def _get_fetch_location_from_host_attribute(self):
        """Get repo to use for packages from host attribute, if possible.

        Hosts are tagged with an attribute containing the URL
        from which to source packages when running a test on that host.
        If self.host is set, attempt to look this attribute in the host info.

        @returns value of the 'job_repo_url' host attribute, if present.
        """
        if not self.host:
            return None

        try:
            info = self.host.host_info_store.get()
        except Exception as e:
            # TODO(pprabhu): We really want to catch host_info.StoreError here,
            # but we can't import host_info from this module.
            #   - autotest_lib.hosts.host_info pulls in (naturally)
            #   autotest_lib.hosts.__init__
            #   - This pulls in all the host classes ever defined
            #   - That includes abstract_ssh, which depends on autotest
            logging.warning('Failed to obtain host info: %r', e)
            logging.warning('Skipping autotest fetch location based on %s',
                            JOB_REPO_URL)
            return None

        job_repo_url = info.attributes.get(JOB_REPO_URL, '')
        if not job_repo_url:
            logging.warning("No %s for %s", JOB_REPO_URL, self.host)
            return None

        logging.info('Got job repo url from host attributes: %s',
                        job_repo_url)
        return job_repo_url


    def get_fetch_location(self):
        """Generate list of locations where autotest can look for packages.

        Old n' busted: Autotest packages are always stored at a URL that can
        be derived from the one passed via the voodoo magic --image argument.
        New hotness: Hosts are tagged with an attribute containing the URL
        from which to source packages when running a test on that host.

        @returns the list of candidate locations to check for packages.
        """
        repos = super(SiteAutotest, self).get_fetch_location()

        if _PARSER.options.image:
            image_opt = _PARSER.options.image
            if image_opt.startswith('http://'):
                # A devserver HTTP url was specified, set that as the repo_url.
                repos.append(image_opt.replace(
                    'update', 'static').rstrip('/') + '/autotest')
            else:
                # An image_name like stumpy-release/R27-3437.0.0 was specified,
                # set this as the repo_url for the host. If an AFE is not being
                # run, this will ensure that the installed build uses the
                # associated artifacts for the test specified when running
                # autoserv with --image. However, any subsequent tests run on
                # the host will no longer have the context of the image option
                # and will revert back to utilizing test code/artifacts that are
                # currently present in the users source checkout.
                # devserver selected must be in the same subnet of self.host, if
                # the host is in restricted subnet. Otherwise, host may not be
                # able to reach the devserver and download packages from the
                # repo_url.
                hostname = self.host.hostname if self.host else None
                devserver_url = dev_server.ImageServer.resolve(
                        image_opt, hostname).url()
                repo_url = tools.get_package_url(devserver_url, image_opt)
                repos.append(repo_url)
        elif not server_utils.is_inside_chroot():
            # Only try to get fetch location from host attribute if the test
            # is not running inside chroot.
            # No --image option was specified, look for the repo url via
            # the host attribute. If we are not running with a full AFE
            # autoserv will fall back to serving packages itself from whatever
            # source version it is sync'd to rather than using the proper
            # artifacts for the build on the host.
            found_repo = self._get_fetch_location_from_host_attribute()
            if found_repo is not None:
                # Add our new repo to the end, the package manager will
                # later reverse the list of repositories resulting in ours
                # being first
                repos.append(found_repo)

        return repos


    def install(self, host=None, autodir=None, use_packaging=True):
        """Install autotest.  If |host| is not None, stores it in |self.host|.

        @param host A Host instance on which autotest will be installed
        @param autodir Location on the remote host to install to
        @param use_packaging Enable install modes that use the packaging system.

        """
        if host:
            self.host = host

        super(SiteAutotest, self).install(host=host, autodir=autodir,
                                          use_packaging=use_packaging)


    def _install(self, host=None, autodir=None, use_autoserv=True,
                 use_packaging=True):
        """
        Install autotest.  If get() was not called previously, an
        attempt will be made to install from the autotest svn
        repository.

        @param host A Host instance on which autotest will be installed
        @param autodir Location on the remote host to install to
        @param use_autoserv Enable install modes that depend on the client
            running with the autoserv harness
        @param use_packaging Enable install modes that use the packaging system

        @exception AutoservError if a tarball was not specified and
            the target host does not have svn installed in its path
        """
        # TODO(milleral): http://crbug.com/258161
        super(SiteAutotest, self)._install(host, autodir, use_autoserv,
                                           use_packaging)
        # Send over the most recent global_config.ini after installation if one
        # is available.
        # This code is a bit duplicated from
        # _Run._create_client_config_file, but oh well.
        if self.installed and self.source_material:
            logging.info('Installing updated global_config.ini.')
            destination = os.path.join(self.host.get_autodir(),
                                       'global_config.ini')
            with tempfile.NamedTemporaryFile() as client_config:
                config = global_config.global_config
                client_section = config.get_section_values('CLIENT')
                client_section.write(client_config)
                client_config.flush()
                self.host.send_file(client_config.name, destination)


    def run_static_method(self, module, method, results_dir='.', host=None,
                          *args):
        """Runs a non-instance method with |args| from |module| on the client.

        This method runs a static/class/module autotest method on the client.
        For example:
          run_static_method("autotest_lib.client.cros.cros_ui", "reboot")

        Will run autotest_lib.client.cros.cros_ui.reboot() on the client.

        @param module: module name as you would refer to it when importing in a
            control file. e.g. autotest_lib.client.common_lib.module_name.
        @param method: the method you want to call.
        @param results_dir: A str path where the results should be stored
            on the local filesystem.
        @param host: A Host instance on which the control file should
            be run.
        @param args: args to pass to the method.
        """
        control = "\n".join(["import %s" % module,
                             "%s.%s(%s)\n" % (module, method,
                                              ','.join(map(repr, args)))])
        self.run(control, results_dir=results_dir, host=host)
