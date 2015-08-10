# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros.bluetooth import bluetooth_test
import uuid
import xml.etree.ElementTree as ET

class bluetooth_SDP_ServiceSearchAttributeRequest(bluetooth_test.BluetoothTest):
    """
    Verify the correct behaviour of the device when searching for services and
    attributes.
    """
    version = 1

    MIN_ATTR_BYTE_CNT                = 7
    MAX_ATTR_BYTE_CNT                = 300

    BLUETOOTH_BASE_UUID              = 0x0000000000001000800000805F9B34FB

    NON_EXISTING_SERVICE_CLASS_ID    = 0x9875
    SDP_SERVER_CLASS_ID              = 0x1000
    PUBLIC_BROWSE_GROUP_CLASS_ID     = 0x1002
    GAP_CLASS_ID                     = 0x1800
    PNP_INFORMATION_CLASS_ID         = 0x1200
    PUBLIC_BROWSE_ROOT               = 0x1002
    AVRCP_TG_CLASS_ID                = 0x110C

    NON_EXISTING_ATTRIBUTE_ID        = 0xABCD
    SERVICE_CLASS_ID_ATTRIBUTE_ID    = 0x0001
    SERVICE_DATABASE_STATE_ATTR_ID   = 0x0201
    PROTOCOL_DESCRIPTOR_LIST_ATTR_ID = 0x0004
    ICON_URL_ATTR_ID                 = 0x000C
    VERSION_NUMBER_LIST_ATTR_ID      = 0x0200
    PROFILE_DESCRIPTOR_LIST_ATTR_ID  = 0x0009
    BROWSE_GROUP_LIST_ATTR_ID        = 0x0005
    DOCUMENTATION_URL_ATTR_ID        = 0x000A
    CLIENT_EXECUTABLE_URL_ATTR_ID    = 0x000B
    ADDITIONAL_PROTOCOLLIST_ATTR_ID  = 0x000D

    L2CAP_UUID                       = 0x0100
    ATT_UUID                         = 0x0007

    ATT_PSM                          = 0x001F

    BLUEZ_URL                        = 'http://www.bluez.org/'

    FAKE_SERVICE_PATH                = '/autotest/fake_service'
    FAKE_SERVICE_CLASS_ID            = 0xCDEF
    FAKE_ATTRIBUTE_VALUE             = 42
    LANGUAGE_BASE_ATTRIBUTE_ID       = 0x0006
    FAKE_GENERAL_ATTRIBUTE_IDS       = [
                                        0x0002, # TP/SERVER/SSA/BV-07-C
                                        0x0007, # TP/SERVER/SSA/BV-09-C
                                        0x0003, # TP/SERVER/SSA/BV-10-C
                                        0x0008, # TP/SERVER/SSA/BV-14-C
                                        # TP/SERVER/SSA/BV-13-C:
                                        LANGUAGE_BASE_ATTRIBUTE_ID
                                       ]
    FAKE_LANGUAGE_ATTRIBUTE_OFFSETS  = [
                                        0x0000, # TP/SERVER/SSA/BV-16-C
                                        0x0001, # TP/SERVER/SSA/BV-17-C
                                        0x0002  # TP/SERVER/SSA/BV-18-C
                                       ]

    ERROR_CODE_INVALID_SYNTAX        = 0x0003
    ERROR_CODE_INVALID_PDU_SIZE      = 0x0004


    def build_service_record(self):
        """Build SDP record manually for the fake service.

        @return resulting record as string

        """
        value = ET.Element('uint16', {'value': str(self.FAKE_ATTRIBUTE_VALUE)})

        sdp_record = ET.Element('record')

        service_id_attr = ET.Element(
            'attribute', {'id': str(self.SERVICE_CLASS_ID_ATTRIBUTE_ID)})
        service_id_attr.append(
            ET.Element('uuid', {'value': '0x%X' % self.FAKE_SERVICE_CLASS_ID}))
        sdp_record.append(service_id_attr)

        for attr_id in self.FAKE_GENERAL_ATTRIBUTE_IDS:
            attr = ET.Element('attribute', {'id': str(attr_id)})
            attr.append(value)
            sdp_record.append(attr)

        for offset in self.FAKE_LANGUAGE_ATTRIBUTE_OFFSETS:
            attr_id = self.FAKE_ATTRIBUTE_VALUE + offset
            attr = ET.Element('attribute', {'id': str(attr_id)})
            attr.append(value)
            sdp_record.append(attr)

        sdp_record_str = ('<?xml version="1.0" encoding="UTF-8"?>' +
                          ET.tostring(sdp_record))
        return sdp_record_str


    def test_non_existing(self, class_id, attr_id):
        """Check that a single attribute of a single service does not exist

        @param class_id: Class ID of service to check.
        @param attr_id: ID of attribute to check.

        @return True if service or attribute does not exist, False otherwise

        """
        for size in 16, 32, 128:
            result = self.tester.service_search_attribute_request(
                         [class_id],
                         self.MAX_ATTR_BYTE_CNT,
                         [attr_id],
                         size)
            if result != []:
                return False

        return True


    def get_attribute(self, class_id, attr_id, size):
        """Get a single attribute of a single service using Service Search
        Attribute Request.

        @param class_id: Class ID of service to check.
        @param attr_id: ID of attribute to check.
        @param size: Preferred size of UUID.

        @return attribute value if attribute exists, None otherwise

        """
        res = self.tester.service_search_attribute_request(
                  [class_id], self.MAX_ATTR_BYTE_CNT, [attr_id], size)

        if (isinstance(res, list) and len(res) == 1 and
            isinstance(res[0], list) and len(res[0]) == 2 and
            res[0][0] == attr_id):
            return res[0][1]

        return None


    def test_attribute(self, class_id, attr_id):
        """Test a single attribute of a single service using 16-bit, 32-bit and
        128-bit size of UUID.

        @param class_id: Class ID of service to check.
        @param attr_id: ID of attribute to check.

        @return attribute value if attribute exists and values from three tests
        are equal, None otherwise

        """
        result_16 = self.get_attribute(class_id, attr_id, 16)
        for size in 32, 128:
            result_cur = self.get_attribute(class_id, attr_id, size)
            if result_16 != result_cur:
                return None

        return result_16


    def test_non_existing_service(self):
        """Implementation of test TP/SERVER/SSA/BV-01-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        return self.test_non_existing(self.NON_EXISTING_SERVICE_CLASS_ID,
                                      self.SERVICE_CLASS_ID_ATTRIBUTE_ID)


    def test_non_existing_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-02-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        return self.test_non_existing(self.PUBLIC_BROWSE_GROUP_CLASS_ID,
                                      self.NON_EXISTING_ATTRIBUTE_ID)


    def test_non_existing_service_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-03-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        return self.test_non_existing(self.NON_EXISTING_SERVICE_CLASS_ID,
                                      self.NON_EXISTING_ATTRIBUTE_ID)


    def test_existing_service_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-04-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        value = self.test_attribute(self.SDP_SERVER_CLASS_ID,
                                    self.SERVICE_CLASS_ID_ATTRIBUTE_ID)
        return value == [self.SDP_SERVER_CLASS_ID]


    def test_service_database_state_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-08-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        value = self.test_attribute(self.SDP_SERVER_CLASS_ID,
                                    self.SERVICE_DATABASE_STATE_ATTR_ID)
        return isinstance(value, int)


    def test_protocol_descriptor_list_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-11-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        value = self.test_attribute(self.GAP_CLASS_ID,
                                    self.PROTOCOL_DESCRIPTOR_LIST_ATTR_ID)

        # The first-layer protocol is L2CAP, using the PSM for ATT protocol.
        if value[0] != [self.L2CAP_UUID, self.ATT_PSM]:
            return False

        # The second-layer protocol is ATT. The additional parameters are
        # ignored, since they may reasonably vary between implementations.
        if value[1][0] != self.ATT_UUID:
            return False

        return True


    def test_browse_group_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-12-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        value = self.test_attribute(self.GAP_CLASS_ID,
                                    self.BROWSE_GROUP_LIST_ATTR_ID)
        return value == [self.PUBLIC_BROWSE_ROOT]


    def test_icon_url_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-15-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        value = self.test_attribute(self.GAP_CLASS_ID,
                                    self.ICON_URL_ATTR_ID)
        return value == self.BLUEZ_URL


    def test_version_list_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-19-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        value = self.test_attribute(self.SDP_SERVER_CLASS_ID,
                                    self.VERSION_NUMBER_LIST_ATTR_ID)
        return isinstance(value, list) and value != []


    def test_profile_descriptor_list_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-20-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        value = self.test_attribute(self.PNP_INFORMATION_CLASS_ID,
                                    self.PROFILE_DESCRIPTOR_LIST_ATTR_ID)
        return (isinstance(value, list) and len(value) == 1 and
                isinstance(value[0], list) and len(value[0]) == 2 and
                value[0][0] == self.PNP_INFORMATION_CLASS_ID)


    def test_documentation_url_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-21-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        value = self.test_attribute(self.GAP_CLASS_ID,
                                    self.DOCUMENTATION_URL_ATTR_ID)
        return value == self.BLUEZ_URL


    def test_client_executable_url_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-22-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        value = self.test_attribute(self.GAP_CLASS_ID,
                                    self.CLIENT_EXECUTABLE_URL_ATTR_ID)
        return value == self.BLUEZ_URL


    def test_additional_protocol_descriptor_list_attribute(self):
        """Implementation of test TP/SERVER/SSA/BV-23-C from SDP Specification.

        @return True if test passes, False if test fails

        """

        """AVRCP is not supported by Chromebook and no need to run this test
        value = self.test_attribute(self.AVRCP_TG_CLASS_ID,
                                    self.ADDITIONAL_PROTOCOLLIST_ATTR_ID)
        return isinstance(value, list) and value != []
        """
        return True

    def test_fake_attributes(self):
        """Test values of attributes of the fake service record.

        @return True if all tests pass, False otherwise

        """
        for attr_id in self.FAKE_GENERAL_ATTRIBUTE_IDS:
            value = self.test_attribute(self.FAKE_SERVICE_CLASS_ID, attr_id)
            if value != self.FAKE_ATTRIBUTE_VALUE:
                return False

        for offset in self.FAKE_LANGUAGE_ATTRIBUTE_OFFSETS:
            lang_base = self.test_attribute(self.FAKE_SERVICE_CLASS_ID,
                                            self.LANGUAGE_BASE_ATTRIBUTE_ID)
            attr_id = lang_base + offset
            value = self.test_attribute(self.FAKE_SERVICE_CLASS_ID, attr_id)
            if value != self.FAKE_ATTRIBUTE_VALUE:
                return False

        return True


    def test_continuation_state(self):
        """Implementation of test TP/SERVER/SSA/BV-06-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        for size in 16, 32, 128:
            # This request should generate a long response, which will be
            # split into 98 chunks.
            value = self.tester.service_search_attribute_request(
                        [self.PUBLIC_BROWSE_GROUP_CLASS_ID],
                        self.MIN_ATTR_BYTE_CNT,
                        [[0, 0xFFFF]], size)
            if not isinstance(value, list) or value == []:
                return False

        return True


    def test_invalid_request_syntax(self):
        """Implementation of test TP/SERVER/SSA/BI-01-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        for size in 16, 32, 128:
            value = self.tester.service_search_attribute_request(
                        [self.SDP_SERVER_CLASS_ID],
                        self.MAX_ATTR_BYTE_CNT,
                        [self.SERVICE_CLASS_ID_ATTRIBUTE_ID],
                        size,
                        invalid_request='9875')
            if value != self.ERROR_CODE_INVALID_SYNTAX:
                return False

        return True


    def test_invalid_pdu_size(self):
        """Implementation of test TP/SERVER/SSA/BI-02-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        for size in 16, 32, 128:
            value = self.tester.service_search_attribute_request(
                        [self.SDP_SERVER_CLASS_ID],
                        self.MAX_ATTR_BYTE_CNT,
                        [self.SERVICE_CLASS_ID_ATTRIBUTE_ID],
                        size,
                        forced_pdu_size=100)
            if value != self.ERROR_CODE_INVALID_PDU_SIZE:
                return False

        return True


    def correct_request(self):
        """Run tests for Service Search Attribute request.

        @return True if all tests finishes correctly, False otherwise

        """
        # connect to the DUT via L2CAP using SDP socket
        self.tester.connect(self.adapter['Address'])

        # TODO(arakhov): improve logging to be able to see failing test's number
        #                (issue # 426260)
        return (self.test_non_existing_service() and
                self.test_non_existing_attribute() and
                self.test_non_existing_service_attribute() and
                self.test_existing_service_attribute() and
                self.test_service_database_state_attribute() and
                self.test_protocol_descriptor_list_attribute() and
                self.test_browse_group_attribute() and
                self.test_icon_url_attribute() and
                self.test_version_list_attribute() and
                self.test_profile_descriptor_list_attribute() and
                self.test_documentation_url_attribute() and
                self.test_client_executable_url_attribute() and
                self.test_additional_protocol_descriptor_list_attribute() and
                self.test_fake_attributes() and
                self.test_continuation_state() and
                self.test_invalid_request_syntax() and
                self.test_invalid_pdu_size())


    def run_once(self):
        # Reset the adapter to the powered on, discoverable state.
        if not (self.device.reset_on() and
                self.device.set_discoverable(True)):
            raise error.TestFail('DUT could not be reset to initial state')

        self.adapter = self.device.get_adapter_properties()

        # Create a fake service record in order to test attributes,
        # that are not present in any of existing services.
        uuid128 = ((self.FAKE_SERVICE_CLASS_ID << 96) +
                   self.BLUETOOTH_BASE_UUID)
        uuid_str = str(uuid.UUID(int=uuid128))
        sdp_record = self.build_service_record()
        self.device.register_profile(self.FAKE_SERVICE_PATH,
                                     uuid_str,
                                     {"ServiceRecord": sdp_record})

        # Setup the tester as a generic computer.
        if not self.tester.setup('computer'):
            raise error.TestFail('Tester could not be initialized')

        # Since radio is involved, this test is not 100% reliable; instead we
        # repeat a few times until it succeeds.
        for failed_attempts in range(0, 5):
            if self.correct_request():
                break
        else:
            raise error.TestFail('Expected services/attributes were not found')

        # Record how many attempts this took, hopefully we'll one day figure out
        # a way to reduce this to zero and then the loop above can go away.
        self.write_perf_keyval({'failed_attempts': failed_attempts})
