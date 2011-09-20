# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

class Error(Exception):
  pass


class AirStateVerifierPermissive(object):
  """An abstraction for verifying the air-side cellular state.

  This version is for commercial networks where we can't verify
  anything, so it's a no-op."""
  def AssertDataStatusIn(self, states):
    """Assert that the device's status is in states.
    Arguments:
      states:  Collection of states
    Raises:
      Error on failure."""
    # This base class is for commercial networks.  It can't verify, so
    # it doesn't
    pass


class AirStateVerifierBasestation(object):
  """An abstraction for verifying the air-side cellular state.

  This version checks with the base station emulator.
  """
  def __init__(self, base_station):
    self.base_station = base_station

  def AssertDataStatusIn(self, expected):
    actual = self.base_station.GetUeDataStatus()
    if actual not in expected:
      raise Error('Expected UE in status %s, got %s' % (
          expected, actual))
