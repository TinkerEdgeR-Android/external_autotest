# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A utility to program Chrome OS devices' firmware using servo.

This utility expects the DUT to be connected to a servo device. This allows us
to put the DUT into the required state and to actually program the DUT's
firmware using FTDI, USB and/or serial interfaces provided by servo.

Servo state is preserved across the programming process.
"""

import glob
import logging
import os
import re
import site
import xml.etree.ElementTree

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros.faft.config.config import Config as FAFTConfig


class ProgrammerError(Exception):
    """Local exception class wrapper."""
    pass


class _BaseProgrammer(object):
    """Class implementing base programmer services.

    Private attributes:
      _servo: a servo object controlling the servo device
      _servo_prog_state: a tuple of strings of "<control>:<value>" pairs,
                         listing servo controls and their required values for
                         programming
      _servo_saved_state: a list of the same elements as _servo_prog_state,
                          those which need to be restored after programming
      _program_cmd: a string, the shell command to run on the servo host
                    to actually program the firmware. Dependent on
                    firmware/hardware type, set by subclasses.
    """

    def __init__(self, servo, req_list):
        """Base constructor.
        @param servo: a servo object controlling the servo device
        @param req_list: a list of strings, names of the utilities required
                         to be in the path for the programmer to succeed
        """
        self._servo = servo
        self._servo_prog_state = ()
        self._servo_saved_state = []
        self._program_cmd = ''
        try:
            self._servo.system('which %s' % ' '.join(req_list))
        except error.AutoservRunError:
            # TODO: We turn this exception into a warn since the fw programmer
            # is not working right now, and some systems do not package the
            # required utilities its checking for.
            # We should reinstate this exception once the programmer is working
            # to indicate the missing utilities earlier in the test cycle.
            # Bug chromium:371011 filed to track this.
            logging.warn("Ignoring exception when verify required bins : %s",
                         ' '.join(req_list))


    def _set_servo_state(self):
        """Set servo for programming, while saving the current state."""
        logging.debug("Setting servo state for programming")
        for item in self._servo_prog_state:
            key, value = item.split(':')
            present = self._servo.get(key)
            if present != value:
                self._servo_saved_state.append('%s:%s' % (key, present))
            self._servo.set(key, value)


    def _restore_servo_state(self):
        """Restore previously saved servo state."""
        logging.debug("Restoring servo state after programming")
        self._servo_saved_state.reverse()  # Do it in the reverse order.
        for item in self._servo_saved_state:
            key, value = item.split(':')
            self._servo.set(key, value)


    def program(self):
        """Program the firmware as configured by a subclass."""
        self._set_servo_state()
        try:
            logging.debug("Programmer command: %s", self._program_cmd)
            self._servo.system(self._program_cmd)
        finally:
            self._restore_servo_state()


class FlashromProgrammer(_BaseProgrammer):
    """Class for programming AP flashrom."""

    def __init__(self, servo):
        """Configure required servo state."""
        super(FlashromProgrammer, self).__init__(servo, ['flashrom',])
        self._fw_path = None
        self._tmp_path = '/tmp'
        self._fw_main = os.path.join(self._tmp_path, 'fw_main')
        self._ro_vpd = os.path.join(self._tmp_path, 'ro_vpd')
        self._rw_vpd = os.path.join(self._tmp_path, 'rw_vpd')
        self._gbb = os.path.join(self._tmp_path, 'gbb')


    def program(self):
        """Program the firmware but preserve VPD and HWID."""
        assert self._fw_path is not None
        self._set_servo_state()
        try:
            vpd_sections = [('RW_VPD', self._rw_vpd), ('RO_VPD', self._ro_vpd)]
            gbb_section = [('GBB', self._gbb)]
            servo_version = self._servo.get_servo_version()
            servo_v2_programmer = 'ft2232_spi:type=servo-v2'
            servo_v3_programmer = 'linux_spi'
            if servo_version == 'servo_v2':
                programmer = servo_v2_programmer
                if self._servo.servo_serial:
                    programmer += ',serial=%s' % self._servo.servo_serial
            elif servo_version == 'servo_v3':
                programmer = servo_v3_programmer
            else:
                raise Exception('Servo version %s is not supported.' %
                                servo_version)
            # Save needed sections from current firmware
            for section in vpd_sections + gbb_section:
                self._servo.system(' '.join([
                    'flashrom', '-V', '-p', programmer,
                    '-r', self._fw_main, '-i', '%s:%s' % section]))

            # Pack the saved VPD into new firmware
            self._servo.system('cp %s %s' % (self._fw_path, self._fw_main))
            img_size = self._servo.system_output(
                    "stat -c '%%s' %s" % self._fw_main)
            pack_cmd = ['flashrom',
                    '-p', 'dummy:image=%s,size=%s,emulate=VARIABLE_SIZE' % (
                        self._fw_main, img_size),
                    '-w', self._fw_main]
            for section in vpd_sections:
                pack_cmd.extend(['-i', '%s:%s' % section])
            self._servo.system(' '.join(pack_cmd))

            # Read original HWID. The output format is:
            #    hardware_id: RAMBI TEST A_A 0128
            gbb_hwid_output = self._servo.system_output(
                    'gbb_utility -g --hwid %s' % self._gbb)
            original_hwid = gbb_hwid_output.split(':', 1)[1].strip()

            # Write HWID to new firmware
            self._servo.system("gbb_utility -s --hwid='%s' %s" %
                    (original_hwid, self._fw_main))

            # Flash the new firmware
            self._servo.system(' '.join([
                    'flashrom', '-V', '-p', programmer,
                    '-w', self._fw_main]))
        finally:
            self._restore_servo_state()


    def prepare_programmer(self, path):
        """Prepare programmer for programming.

        @param path: a string, name of the file containing the firmware image.
        @param board: a string, used to find servo voltage setting.
        """
        faft_config = FAFTConfig(self._servo.get_board())
        self._fw_path = path
        self._servo_prog_state = (
            'spi2_vref:%s' % faft_config.spi_voltage,
            'spi2_buf_en:on',
            'spi2_buf_on_flex_en:on',
            'spi_hold:off',
            'cold_reset:on',
            )


class FlashECProgrammer(_BaseProgrammer):
    """Class for programming AP flashrom."""

    def __init__(self, servo):
        """Configure required servo state."""
        super(FlashECProgrammer, self).__init__(servo, ['flash_ec',])
        self._servo = servo


    def prepare_programmer(self, image, board=None):
        """Prepare programmer for programming.

        @param image: string with the location of the image file
        @param board: Name of the board used in EC image. Some board's name used
                      by servod might be different from EC. Default to None.
        """
        # TODO: need to not have port be hardcoded
        self._program_cmd = ('flash_ec --board=%s --image=%s --port=%s' %
                             (board or self._servo.get_board(), image, '9999'))


class ProgrammerV2(object):
    """Main programmer class which provides programmer for BIOS and EC with
    servo V2."""

    def __init__(self, servo):
        self._servo = servo
        self._valid_boards = self._get_valid_v2_boards()
        self._bios_programmer = self._factory_bios(self._servo)
        self._ec_programmer = self._factory_ec(self._servo)


    @staticmethod
    def _get_valid_v2_boards():
        """Greps servod config files to look for valid v2 boards.

        @return A list of valid board names.
        """
        site_packages_paths = site.getsitepackages()
        SERVOD_CONFIG_DATA_DIR = None
        for p in site_packages_paths:
            servo_data_path = os.path.join(p, 'servo', 'data')
            if os.path.exists(servo_data_path):
                SERVOD_CONFIG_DATA_DIR = servo_data_path
                break
        if not SERVOD_CONFIG_DATA_DIR:
            raise ProgrammerError(
                    'Unable to locate data directory of Python servo module')
        SERVOFLEX_V2_R0_P50_CONFIG = 'servoflex_v2_r0_p50.xml'
        SERVO_CONFIG_GLOB = 'servo_*_overlay.xml'
        SERVO_CONFIG_REGEXP = 'servo_(?P<board>.+)_overlay.xml'

        def is_v2_compatible_board(board_config_path):
            """Check if the given board config file is v2-compatible.

            @param board_config_path: Path to a board config XML file.

            @return True if the board is v2-compatible; False otherwise.
            """
            configs = []
            def get_all_includes(config_path):
                """Get all included XML config names in the given config file.

                @param config_path: Path to a servo config file.
                """
                root = xml.etree.ElementTree.parse(config_path).getroot()
                for element in root.findall('include'):
                    include_name = element.find('name').text
                    configs.append(include_name)
                    get_all_includes(os.path.join(
                            SERVOD_CONFIG_DATA_DIR, include_name))

            get_all_includes(board_config_path)
            return True if SERVOFLEX_V2_R0_P50_CONFIG in configs else False

        result = []
        board_overlays = glob.glob(
                os.path.join(SERVOD_CONFIG_DATA_DIR, SERVO_CONFIG_GLOB))
        for overlay_path in board_overlays:
            if is_v2_compatible_board(overlay_path):
                result.append(re.search(SERVO_CONFIG_REGEXP,
                                        overlay_path).group('board'))
        return result


    def _factory_bios(self, servo):
        """Instantiates and returns (bios, ec) programmers for the board.

        @param servo: A servo object.

        @return A programmer for ec. If the programmer is not supported
            for the board, None will be returned.
        """
        _bios_prog = None
        _board = servo.get_board()

        servo_prog_state = [
            'spi2_buf_en:on',
            'spi2_buf_on_flex_en:on',
            'spi_hold:off',
            'cold_reset:on',
            ]

        logging.debug('Setting up BIOS programmer for board: %s', _board)
        if _board in self._valid_boards:
            _bios_prog = FlashromProgrammer(servo)
        else:
            logging.warning('No BIOS programmer found for board: %s', _board)

        return _bios_prog


    def _factory_ec(self, servo):
        """Instantiates and returns ec programmer for the board.

        @param servo: A servo object.

        @return A programmer for ec. If the programmer is not supported
            for the board, None will be returned.
        """
        _ec_prog = None
        _board = servo.get_board()

        logging.debug('Setting up EC programmer for board: %s', _board)
        if _board in self._valid_boards:
            _ec_prog = FlashECProgrammer(servo)
        else:
            logging.warning('No EC programmer found for board: %s', _board)

        return _ec_prog


    def program_bios(self, image):
        """Programs the DUT with provide bios image.

        @param image: (required) location of bios image file.

        """
        self._bios_programmer.prepare_programmer(image)
        self._bios_programmer.program()


    def program_ec(self, image):
        """Programs the DUT with provide ec image.

        @param image: (required) location of ec image file.

        """
        self._ec_programmer.prepare_programmer(image)
        self._ec_programmer.program()


class ProgrammerV3(object):
    """Main programmer class which provides programmer for BIOS and EC with
    servo V3.

    Different from programmer for servo v2, programmer for servo v3 does not
    try to validate if the board can use servo V3 to update firmware. As long as
    the servod process running in beagblebone with given board, the program will
    attempt to flash bios and ec.

    """

    def __init__(self, servo):
        self._servo = servo
        self._bios_programmer = FlashromProgrammer(servo)
        self._ec_programmer = FlashECProgrammer(servo)


    def program_bios(self, image):
        """Programs the DUT with provide bios image.

        @param image: (required) location of bios image file.

        """
        self._bios_programmer.prepare_programmer(image)
        self._bios_programmer.program()


    def program_ec(self, image, board=None):
        """Programs the DUT with provide ec image.

        @param image: (required) location of ec image file.
        @param board: Name of the board used in EC image. Some board's name used
                      by servod might be different from EC. Default to None.

        """
        self._ec_programmer.prepare_programmer(image, board)
        self._ec_programmer.program()
