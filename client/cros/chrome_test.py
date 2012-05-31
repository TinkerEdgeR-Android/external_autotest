# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, pwd, re, shutil, stat, subprocess, tempfile

import common, constants, cros_ui
from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import ownership

class ChromeTestBase(test.test):
    home_dir = None
    chrome_restart_disabled = False

    _PYAUTO_DEP = 'pyauto_dep'
    _CHROME_TEST_DEP = 'chrome_test'

    _MINIDUMPS_FILE = '/mnt/stateful_partition/etc/enable_chromium_minidumps'


    def setup(self):
        self.job.setup_dep([self._PYAUTO_DEP])
        self.job.setup_dep([self._CHROME_TEST_DEP])
        # create a empty srcdir to prevent the error that checks .version file
        if not os.path.exists(self.srcdir):
            os.mkdir(self.srcdir)


    def nuke_chrome(self):
        try:
            open(constants.DISABLE_BROWSER_RESTART_MAGIC_FILE, 'w').close()
            self.chrome_restart_disabled = True
        except IOError, e:
            logging.debug(e)
            raise error.TestError('Failed to disable browser restarting.')
        utils.nuke_process_by_name(name=constants.BROWSER, with_prejudice=True)


    def initialize(self, nuke_browser_norestart=True, skip_deps=False):
        self.home_dir = tempfile.mkdtemp()
        os.chmod(self.home_dir, stat.S_IROTH | stat.S_IWOTH |stat.S_IXOTH)
        chrome_test_dep_dir = os.path.join(
                self.autodir, 'deps', self._CHROME_TEST_DEP)
        pyauto_dep_dir = os.path.join(self.autodir, 'deps', self._PYAUTO_DEP)
        if not skip_deps:
            self.job.install_pkg(self._PYAUTO_DEP, 'dep', pyauto_dep_dir)
            self.job.install_pkg(self._CHROME_TEST_DEP, 'dep',
                                 chrome_test_dep_dir)
        self.cr_source_dir = '%s/test_src' % chrome_test_dep_dir
        self.test_binary_dir = '%s/out/Release' % self.cr_source_dir
        if nuke_browser_norestart:
            self.nuke_chrome()
        try:
            setup_cmd = ('/bin/bash %s/test_src/out/Release/'
                         'setup_test_links.sh' % pyauto_dep_dir)
            utils.system(setup_cmd)  # this might raise an exception
            setup_cmd = ('/bin/bash %s/setup_test_links.sh'
                         % self.test_binary_dir)
            utils.system(setup_cmd)  # this might raise an exception
        except error.CmdError, e:
            raise error.TestError(e)


    def setup_suid_python(self):
        """Setup suid python binary that can enable chrome testing interface."""
        suid_python = os.path.join(self.test_binary_dir, 'suid-python')
        py_path = utils.system_output('which python')
        py_path = py_path.strip()
        assert os.path.exists(py_path), 'Could not find python'
        if os.path.islink(py_path):
            linkto = os.readlink(py_path)
            py_path = os.path.join(os.path.dirname(py_path), linkto)
        shutil.copy(py_path, suid_python)
        os.chown(suid_python, 0, 0)
        os.chmod(suid_python, 04755)


    def setup_for_pyauto(self):
        assert os.geteuid() == 0, 'Need superuser privileges'

        deps_dir = os.path.join(self.autodir, 'deps')
        utils.system('chown -R chronos ' + self.cr_source_dir)

        # chronos should own the current dir.
        chronos_id = pwd.getpwnam('chronos')
        os.chown(os.getcwd(), chronos_id.pw_uid, chronos_id.pw_gid)

        # Make sure Chrome minidumps are written locally.
        if not os.path.exists(self._MINIDUMPS_FILE):
            open(self._MINIDUMPS_FILE, 'w').close()
            # Allow browser restart by its babysitter (session_manager).
            if os.path.exists(constants.DISABLE_BROWSER_RESTART_MAGIC_FILE):
                os.remove(constants.DISABLE_BROWSER_RESTART_MAGIC_FILE)
            cros_ui.nuke()
        assert os.path.exists(self._MINIDUMPS_FILE)

        # Disallow further browser restart by its babysitter.
        if not os.path.exists(constants.DISABLE_BROWSER_RESTART_MAGIC_FILE):
            open(constants.DISABLE_BROWSER_RESTART_MAGIC_FILE, 'w').close()
        assert os.path.exists(constants.DISABLE_BROWSER_RESTART_MAGIC_FILE)

        # The UI must be taken down to ensure that no stale state persists.
        cros_ui.stop()
        # Clear ownership before login.
        ownership.clear_ownership()
        cros_ui.start(wait_for_login_prompt=False)


    def filter_bad_tests(self, tests, blacklist=None):
        matcher = re.compile(".+\.(FLAKY|FAILS|DISABLED).+")
        if blacklist:
          return filter(lambda(x): not matcher.match(x) and x not in blacklist,
                        tests)
        else:
          return filter(lambda(x): not matcher.match(x), tests)


    def list_chrome_tests(self, test_binary):
        all_tests = []
        try:
            cmd = '%s/%s --gtest_list_tests' % (self.test_binary_dir,
                                                test_binary)
            cmd = 'HOME=%s CR_SOURCE_ROOT=%s %s' % (self.home_dir,
                                                    self.cr_source_dir,
                                                    cros_ui.xcommand(cmd))
            logging.debug("Running %s" % cmd)
            test_proc = subprocess.Popen(cmd,
                                         shell=True,
                                         stdout=subprocess.PIPE)
            last_suite = None
            skipper = re.compile('YOU HAVE')
            for line in test_proc.stdout:
                stripped = line.lstrip()
                if stripped == '' or skipper.match(stripped):
                    continue
                elif (stripped == line):
                    last_suite = stripped.rstrip()
                else:
                  all_tests.append(last_suite+stripped.rstrip())
        except OSError, e:
            logging.debug(e)
            raise error.TestFail('Failed to list tests in %s!' % test_binary)
        return all_tests


    def run_chrome_test(self, test_to_run, extra_params='', prefix=''):
        try:
            os.chdir(self.home_dir)
            cmd = '%s/%s %s' % (self.test_binary_dir, test_to_run, extra_params)
            cmd = 'HOME=%s CR_SOURCE_ROOT=%s %s' % (self.home_dir,
                                                    self.cr_source_dir,
                                                    prefix + cmd)
            cros_ui.xsystem_as(cmd)
        except error.CmdError, e:
            logging.debug(e)
            raise error.TestFail('%s failed!' % test_to_run)


    def generate_test_list(self, binary, group, total_groups):
        all_tests = self.list_chrome_tests(self.binary_to_run)
        group_size = len(all_tests)/total_groups + 1  # to be safe
        return all_tests[group*group_size:group*group_size+group_size]


    def cleanup(self):
        if self.chrome_restart_disabled:
            # Allow chrome to be restarted again.
            os.unlink(constants.DISABLE_BROWSER_RESTART_MAGIC_FILE)
        # Reset the UI.
        cros_ui.nuke()
        if self.home_dir:
            shutil.rmtree(self.home_dir, ignore_errors=True)
        test.test.cleanup(self)
