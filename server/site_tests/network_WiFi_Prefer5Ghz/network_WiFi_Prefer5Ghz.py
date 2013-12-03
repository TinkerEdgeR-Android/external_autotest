# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.common_lib.cros.network import xmlrpc_datatypes
from autotest_lib.server.cros.network import hostap_config
from autotest_lib.server.cros.network import wifi_cell_test_base
from autotest_lib.server.cros.network import wifi_client


class network_WiFi_Prefer5Ghz(wifi_cell_test_base.WiFiCellTestBase):
    """Test that if we see two APs in the same network, we take the 5Ghz one."""
    version = 1


    def run_once(self):
        """Body of the test."""
        mode_n = hostap_config.HostapConfig.MODE_11N_PURE
        ap_config0 = hostap_config.HostapConfig(channel=1, mode=mode_n)
        self.context.configure(ap_config0)
        ssid = self.context.router.get_ssid(instance=0)
        ap_config1 = hostap_config.HostapConfig(
                ssid=ssid, channel=48, mode=mode_n)
        self.context.configure(ap_config1, multi_interface=True)
        self.context.assert_connect_wifi(
                xmlrpc_datatypes.AssociationParameters(ssid=ssid))
        self.context.client.check_iw_link_value(
                wifi_client.WiFiClient.IW_LINK_KEY_FREQUENCY,
                str(ap_config1.frequency))
