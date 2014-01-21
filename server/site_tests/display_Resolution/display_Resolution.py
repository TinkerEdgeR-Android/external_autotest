# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a server side resolution display test using the Chameleon board."""

import logging
import os
import time
import xmlrpclib

from autotest_lib.client.common_lib import error
from autotest_lib.server import test
from autotest_lib.server.cros.chameleon import display_client

# pylint: disable=E1101

class display_Resolution(test.test):
    """Server side external display test.

    This test talks to a Chameleon board and a DUT to set up, run, and verify
    external display function of the DUT.
    """
    version = 1
    CALIBRATION_IMAGE_SETUP_TIME = 10
    PIXEL_DIFF_MARGIN = 1
    RESOLUTION_TEST_LIST = [
            # Mix DP and HDMI together to test the converter cases.
            ('DP', 1280, 800),
            ('DP', 1440, 900),
            ('DP', 1600, 900),
            ('DP', 1680, 1050),
            ('DP', 1920, 1080),
            ('HDMI', 1280, 720),
            ('HDMI', 1920, 1080),
    ]

    def initialize(self, host):
        self._connector_id = None
        self._errors = []
        self._host = host
        self._test_data_dir = os.path.join(
                self.bindir, 'display_Resolution_test_data')
        self._display_client = display_client.DisplayClient(host)
        self._display_client.initialize(self._test_data_dir)
        self._chameleon_board = host.chameleon

    def cleanup(self):
        if self._display_client:
            self._display_client.cleanup()

    def run_once(self, host, usb_serial=None, test_mirrored=False,
                 test_suspend_resume=False):
        self._connector_id, self._connector_type = self.get_external_output()
        if self._connector_id is None:
            raise error.TestError('DUT and Chameleon board not connected')

        for resolution in self.RESOLUTION_TEST_LIST:
            try:
                self.set_up_chameleon(resolution)
                logging.info('Reconnect output...')
                self._display_client.reconnect_output_and_wait()
                logging.info('Set mirrored: %s', test_mirrored)
                self._display_client.set_mirrored(test_mirrored)

                if test_suspend_resume:
                    logging.info('Suspend and resume')
                    self._display_client.suspend_resume()
                    if self._host.wait_up(timeout=20)
                        logging.info('DUT is up')
                    else:
                        raise error.TestError('DUT is not up after resume')

                self.test_display(resolution)
            finally:
                self._chameleon_board.Reset()

        if self._errors:
            raise error.TestError(', '.join(self._errors))

    def get_external_output(self):
        """Gets the first available external output port between Chameleon
        and DUT.

        @return: A tuple (the ID of Chameleon connector,
                          the name of Chameleon connector)
        """
        # TODO(waihong): Support multiple connectors.
        for connector_id in self._chameleon_board.ProbeInputs():
            # Plug to ensure the connector is plugged.
            self._chameleon_board.Plug(connector_id)
            connector_name = self._chameleon_board.GetConnectorType(
                    connector_id)
            output = self._display_client.get_connector_name()
            # TODO(waihong): Make sure eDP work in this way.
            if output and output.startswith(connector_name):
                return (connector_id, connector_name)
        return (None, None)

    def set_up_chameleon(self, resolution):
        """Loads the EDID of the given resolution onto Chameleon.

        @param resolution: A tuple (tag, width, height) representing the
                resolution to test.
        """
        logging.info('Setting up %r on port %d (%s)...',
                     resolution, self._connector_id, self._connector_type)

        edid_filename = os.path.join(
                self._test_data_dir, 'edids', '%s_%dx%d' % resolution)
        if not os.path.exists(edid_filename):
            raise ValueError('EDID file %r does not exist' % edid_filename)

        logging.info('Create edid: %s', edid_filename)
        edid_id = self._chameleon_board.CreateEdid(
                xmlrpclib.Binary(open(edid_filename).read()))

        logging.info('Apply edid %d on port %d (%s)',
                     edid_id, self._connector_id, self._connector_type)
        self._chameleon_board.ApplyEdid(self._connector_id, edid_id)
        self._chameleon_board.DestoryEdid(edid_id)

    # TODO(waihong): Move the frame capture method to Chameleon wrapper.
    def capture_chameleon_screen(self, file_path):
        """Captures Chameleon framebuffer.

        @param file_path: The path of file for output.

        @return: The byte-array for the screen.
        """
        pixels = self._chameleon_board.DumpPixels(self._connector_id).data
        # Write to file for debug.
        open(file_path, 'w+').write(pixels)
        return pixels

    def test_display(self, resolution):
        """Main display testing logic.

        1. Open a calibration image of the given resolution, and set it to
           fullscreen on the external display.
        2. Capture the whole screen from the display buffer of Chameleon.
        3. Capture the framebuffer on DUT.
        4. Verify that the captured screen match the content of DUT
           framebuffer.

        @param resolution: A tuple (tag, width, height) representing the
                resolution to test.
        """
        logging.info('Testing %r...', resolution)
        tag, width, height = resolution
        resolution_str = '%dx%d' % (width, height)
        chameleon_image_file = 'chameleon-%s-%s.bgra' % (tag, resolution_str)
        chameleon_path = os.path.join(self.outputdir, chameleon_image_file)
        dut_image_file = 'dut-%s-%s.bgra' % (tag, resolution_str)
        dut_path = os.path.join(self.outputdir, dut_image_file)

        self._display_client.move_cursor_to_bottom_right()

        logging.info('Waiting the calibration image stable.')
        self._display_client.load_calibration_image((width, height))
        time.sleep(self.CALIBRATION_IMAGE_SETUP_TIME)

        logging.info('Capturing framebuffer on Chameleon.')
        chameleon_pixels = self.capture_chameleon_screen(chameleon_path)
        chameleon_pixels_len = len(chameleon_pixels)

        logging.info('Capturing framebuffer on DUT.')
        dut_pixels = self._display_client.capture_external_screen(dut_path)
        dut_pixels_len = len(dut_pixels)

        if chameleon_pixels_len != dut_pixels_len:
            error_message = ('Lengths of pixels not the same: %d != %d' %
                    (chameleon_pixels_len, dut_pixels_len))
            logging.error(error_message)
            self._errors.append(error_message)
            return

        logging.info('Comparing the pixels...')
        for i in xrange(len(dut_pixels)):
            chameleon_pixel = ord(chameleon_pixels[i])
            dut_pixel = ord(dut_pixels[i])
            # Skip the fourth byte, i.e. the alpha value.
            if (i % 4 != 3 and abs(chameleon_pixel - dut_pixel) >
                    self.PIXEL_DIFF_MARGIN):
                error_message = ('The pixel, offset %d, on %s '
                        'resolution %s, not match: %d != %d' %
                        (i, tag, resolution_str, chameleon_pixel, dut_pixel))
                logging.error(error_message)
                self._errors.append(error_message)
                break
        else:
            logging.info('All pixels match.')
            for file_path in (chameleon_path, dut_path):
                os.remove(file_path)

        self._display_client.close_tab()
