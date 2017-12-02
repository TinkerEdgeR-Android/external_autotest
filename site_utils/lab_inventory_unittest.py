#!/usr/bin/env python
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import itertools
import logging
import os
import unittest

import common
from autotest_lib.server.lib import status_history
from autotest_lib.site_utils import lab_inventory


class _FakeHost(object):
    """Class to mock `Host` in _FakeHostHistory for testing."""

    def __init__(self, hostname, labels):
        self.hostname = hostname
        self.labels = labels


class _FakeHostHistory(object):
    """Class to mock `HostJobHistory` for testing."""

    def __init__(self, board=None, model=None, pool=None, status=None,
                 hostname=''):
        self.host_board = board
        self.host_pool = pool
        self.status = status
        self.host = _FakeHost(
                hostname,
                labels=[
                        'board:%s' % board,
                        'model:%s' % model,
                        'pool:%s' % pool,
                ],
        )


    def last_diagnosis(self):
        """Return the recorded diagnosis."""
        return self.status, None


class _FakeHostLocation(object):
    """Class to mock `HostJobHistory` for location sorting."""

    _HOSTNAME_FORMAT = 'chromeos%d-row%d-rack%d-host%d'


    def __init__(self, location):
        self.hostname = self._HOSTNAME_FORMAT % location


    @property
    def host(self):
        """Return a fake host object with a hostname."""
        return self


# Status values that may be returned by `HostJobHistory`.
#
# _NON_WORKING_STATUS_LIST - The complete list (as of this writing)
#     of status values that the lab_inventory module treats as
#     "broken".
# _WORKING - A value that counts as "working" for purposes
#     of the lab_inventory module.
# _BROKEN - A value that counts as "broken" for the lab_inventory
#     module.  Since there's more than one valid choice here, we've
#     picked one to stand for all of them.

_NON_WORKING_STATUS_LIST = [
    status_history.UNUSED,
    status_history.BROKEN,
    status_history.UNKNOWN,
]

_WORKING = status_history.WORKING
_UNUSED = _NON_WORKING_STATUS_LIST[0]
_BROKEN = _NON_WORKING_STATUS_LIST[1]
_UNKNOWN = _NON_WORKING_STATUS_LIST[2]


class CachedHostJobHistoriesTestCase(unittest.TestCase):
    """Unit tests for class `_CachedHostJobHistories`.

    Coverage is quite basic:  mostly just enough to make sure every
    function gets called, and to make sure that the counting knows
    the difference between 0 and 1.

    The testing also ensures that all known status values that
    can be returned by `HostJobHistory` are counted as expected.

    """

    def setUp(self):
        super(CachedHostJobHistoriesTestCase, self).setUp()
        self.histories = lab_inventory._CachedHostJobHistories()


    def _add_host(self, status):
        fake = _FakeHostHistory(pool=lab_inventory.SPARE_POOL, status=status)
        self.histories.record_host(fake)


    def _check_counts(self, working, broken, idle):
        """Check that pool counts match expectations.

        Checks that `get_working()` and `get_broken()` return the
        given expected values.  Also check that `get_total()` is the
        sum of working and broken devices.

        @param working The expected total of working devices.
        @param broken  The expected total of broken devices.

        """
        self.assertEqual(self.histories.get_working(), working)
        self.assertEqual(self.histories.get_broken(), broken)
        self.assertEqual(self.histories.get_idle(), idle)
        self.assertEqual(self.histories.get_total(),
                         working + broken + idle)


    def test_empty(self):
        """Test counts when there are no DUTs recorded."""
        self._check_counts(0, 0, 0)


    def test_broken(self):
        """Test counting for status: BROKEN."""
        self._add_host(_BROKEN)
        self._check_counts(0, 1, 0)


    def test_idle(self):
        """Testing counting for idle status values."""
        self._add_host(_UNUSED)
        self._check_counts(0, 0, 1)
        self._add_host(_UNKNOWN)
        self._check_counts(0, 0, 2)


    def test_working_then_broken(self):
        """Test counts after adding a working and then a broken DUT."""
        self._add_host(_WORKING)
        self._check_counts(1, 0, 0)
        self._add_host(_BROKEN)
        self._check_counts(1, 1, 0)


    def test_broken_then_working(self):
        """Test counts after adding a broken and then a working DUT."""
        self._add_host(_BROKEN)
        self._check_counts(0, 1, 0)
        self._add_host(_WORKING)
        self._check_counts(1, 1, 0)


class ManagedPoolsHostJobHistoriesTestCase(unittest.TestCase):
    """Unit tests for class `_ManagedPoolsHostJobHistories`.

    Coverage is quite basic:  just enough to make sure every
    function gets called, and to make sure that the counting
    knows the difference between 0 and 1.

    The tests make sure that both individual pool counts and
    totals are counted correctly.

    """

    def setUp(self):
        super(ManagedPoolsHostJobHistoriesTestCase, self).setUp()
        self._board_counts = lab_inventory._ManagedPoolsHostJobHistories()


    def _add_host(self, pool, status):
        fake = _FakeHostHistory(pool=pool, status=status)
        self._board_counts.record_host(fake)


    def _check_all_counts(self, working, broken):
        """Check that total counts for all pools match expectations.

        Checks that `get_working()` and `get_broken()` return the
        given expected values when called without a pool specified.
        Also check that `get_total()` is the sum of working and
        broken devices.

        Additionally, call the various functions for all the pools
        individually, and confirm that the totals across pools match
        the given expectations.

        @param working The expected total of working devices.
        @param broken  The expected total of broken devices.

        """
        self.assertEqual(self._board_counts.get_working(), working)
        self.assertEqual(self._board_counts.get_broken(), broken)
        self.assertEqual(self._board_counts.get_total(),
                         working + broken)
        count_working = 0
        count_broken = 0
        count_total = 0
        for pool in lab_inventory.MANAGED_POOLS:
            count_working += self._board_counts.get_working(pool)
            count_broken += self._board_counts.get_broken(pool)
            count_total += self._board_counts.get_total(pool)
        self.assertEqual(count_working, working)
        self.assertEqual(count_broken, broken)
        self.assertEqual(count_total, working + broken)


    def _check_pool_counts(self, pool, working, broken):
        """Check that counts for a given pool match expectations.

        Checks that `get_working()` and `get_broken()` return the
        given expected values for the given pool.  Also check that
        `get_total()` is the sum of working and broken devices.

        @param pool    The pool to be checked.
        @param working The expected total of working devices.
        @param broken  The expected total of broken devices.

        """
        self.assertEqual(self._board_counts.get_working(pool),
                         working)
        self.assertEqual(self._board_counts.get_broken(pool),
                         broken)
        self.assertEqual(self._board_counts.get_total(pool),
                         working + broken)


    def test_empty(self):
        """Test counts when there are no DUTs recorded."""
        self._check_all_counts(0, 0)
        for pool in lab_inventory.MANAGED_POOLS:
            self._check_pool_counts(pool, 0, 0)


    def test_all_working_then_broken(self):
        """Test counts after adding a working and then a broken DUT.

        For each pool, add first a working, then a broken DUT.  After
        each DUT is added, check counts to confirm the correct values.

        """
        working = 0
        broken = 0
        for pool in lab_inventory.MANAGED_POOLS:
            self._add_host(pool, _WORKING)
            working += 1
            self._check_pool_counts(pool, 1, 0)
            self._check_all_counts(working, broken)
            self._add_host(pool, _BROKEN)
            broken += 1
            self._check_pool_counts(pool, 1, 1)
            self._check_all_counts(working, broken)


    def test_all_broken_then_working(self):
        """Test counts after adding a broken and then a working DUT.

        For each pool, add first a broken, then a working DUT.  After
        each DUT is added, check counts to confirm the correct values.

        """
        working = 0
        broken = 0
        for pool in lab_inventory.MANAGED_POOLS:
            self._add_host(pool, _BROKEN)
            broken += 1
            self._check_pool_counts(pool, 0, 1)
            self._check_all_counts(working, broken)
            self._add_host(pool, _WORKING)
            working += 1
            self._check_pool_counts(pool, 1, 1)
            self._check_all_counts(working, broken)


class LocationSortTests(unittest.TestCase):
    """Unit tests for `_sort_by_location()`."""

    def setUp(self):
        super(LocationSortTests, self).setUp()


    def _check_sorting(self, *locations):
        """Test sorting a given list of locations.

        The input is an already ordered list of lists of tuples with
        row, rack, and host numbers.  The test converts the tuples
        to hostnames, preserving the original ordering.  Then it
        flattens and scrambles the input, runs it through
        `_sort_by_location()`, and asserts that the result matches
        the original.

        """
        lab = 0
        expected = []
        for tuples in locations:
            lab += 1
            expected.append(
                    [_FakeHostLocation((lab,) + t) for t in tuples])
        scrambled = [e for e in itertools.chain(*expected)]
        scrambled = [e for e in reversed(scrambled)]
        actual = lab_inventory._sort_by_location(scrambled)
        # The ordering of the labs in the output isn't guaranteed,
        # so we can't compare `expected` and `actual` directly.
        # Instead, we create a dictionary keyed on the first host in
        # each lab, and compare the dictionaries.
        self.assertEqual({l[0]: l for l in expected},
                         {l[0]: l for l in actual})


    def test_separate_labs(self):
        """Test that sorting distinguishes labs."""
        self._check_sorting([(1, 1, 1)], [(1, 1, 1)], [(1, 1, 1)])


    def test_separate_rows(self):
        """Test for proper sorting when only rows are different."""
        self._check_sorting([(1, 1, 1), (9, 1, 1), (10, 1, 1)])


    def test_separate_racks(self):
        """Test for proper sorting when only racks are different."""
        self._check_sorting([(1, 1, 1), (1, 9, 1), (1, 10, 1)])


    def test_separate_hosts(self):
        """Test for proper sorting when only hosts are different."""
        self._check_sorting([(1, 1, 1), (1, 1, 9), (1, 1, 10)])


    def test_diagonal(self):
        """Test for proper sorting when all parts are different."""
        self._check_sorting([(1, 1, 2), (1, 2, 1), (2, 1, 1)])


class InventoryScoringTests(unittest.TestCase):
    """Unit tests for `_score_repair_set()`."""

    def setUp(self):
        super(InventoryScoringTests, self).setUp()


    def _make_buffer_counts(self, *counts):
        """Create a dictionary suitable as `buffer_counts`.

        @param counts List of tuples with board count data.

        """
        self._buffer_counts = dict(counts)


    def _make_history_list(self, repair_counts):
        """Create a list suitable as `repair_list`.

        @param repair_counts List of (board, count) tuples.

        """
        pool = lab_inventory.SPARE_POOL
        histories = []
        for board, count in repair_counts:
            for i in range(0, count):
                histories.append(
                    _FakeHostHistory(board=board, pool=pool, status=_BROKEN))
        return histories


    def _check_better(self, repair_a, repair_b):
        """Test that repair set A scores better than B.

        Contruct repair sets from `repair_a` and `repair_b`,
        and score both of them using the pre-existing
        `self._buffer_counts`.  Assert that the score for A is
        better than the score for B.

        @param repair_a Input data for repair set A
        @param repair_b Input data for repair set B

        """
        score_a = lab_inventory._score_repair_set(
                self._buffer_counts,
                self._make_history_list(repair_a))
        score_b = lab_inventory._score_repair_set(
                self._buffer_counts,
                self._make_history_list(repair_b))
        self.assertGreater(score_a, score_b)


    def _check_equal(self, repair_a, repair_b):
        """Test that repair set A scores the same as B.

        Contruct repair sets from `repair_a` and `repair_b`,
        and score both of them using the pre-existing
        `self._buffer_counts`.  Assert that the score for A is
        equal to the score for B.

        @param repair_a Input data for repair set A
        @param repair_b Input data for repair set B

        """
        score_a = lab_inventory._score_repair_set(
                self._buffer_counts,
                self._make_history_list(repair_a))
        score_b = lab_inventory._score_repair_set(
                self._buffer_counts,
                self._make_history_list(repair_b))
        self.assertEqual(score_a, score_b)


    def test_improve_worst_board(self):
        """Test that improving the worst board improves scoring.

        Construct a buffer counts dictionary with all boards having
        different counts.  Assert that it is both necessary and
        sufficient to improve the count of the worst board in order
        to improve the score.

        """
        self._make_buffer_counts(('lion', 0),
                                 ('tiger', 1),
                                 ('bear', 2))
        self._check_better([('lion', 1)], [('tiger', 1)])
        self._check_better([('lion', 1)], [('bear', 1)])
        self._check_better([('lion', 1)], [('tiger', 2)])
        self._check_better([('lion', 1)], [('bear', 2)])
        self._check_equal([('tiger', 1)], [('bear', 1)])


    def test_improve_worst_case_count(self):
        """Test that improving the number of worst cases improves the score.

        Construct a buffer counts dictionary with all boards having
        the same counts.  Assert that improving two boards is better
        than improving one.  Assert that improving any one board is
        as good as any other.

        """
        self._make_buffer_counts(('lion', 0),
                                 ('tiger', 0),
                                 ('bear', 0))
        self._check_better([('lion', 1), ('tiger', 1)], [('bear', 2)])
        self._check_equal([('lion', 2)], [('tiger', 1)])
        self._check_equal([('tiger', 1)], [('bear', 1)])


# Each item is the number of DUTs in that status.
STATUS_CHOICES = (_WORKING, _BROKEN, _UNUSED)
StatusCounts = collections.namedtuple('StatusCounts', ['good', 'bad', 'unused'])
# Each item is a StatusCounts tuple specifying the number of DUTs per status in
# the that pool.
CRITICAL_POOL = lab_inventory.CRITICAL_POOLS[0]
SPARE_POOL = lab_inventory.SPARE_POOL
POOL_CHOICES = (CRITICAL_POOL, SPARE_POOL)
PoolStatusCounts = collections.namedtuple('PoolStatusCounts',
                                          ['critical', 'spare'])

def create_inventory(data, by_board=True):
    """Initialize a `_LabInventory` instance for testing.

    This function allows the construction of a complete `_LabInventory` object
    from a simplified input representation.

    A single 'critical pool' is arbitrarily chosen for purposes of
    testing; there's no coverage for testing arbitrary combinations
    in more than one critical pool.

    @param data: dict {key: PoolStatusCounts}. key_type determines what key
            represents.
    @param by_board: Whether to create LabInventory based on board.  This
            function can be used to create _LabInventory based on exactly one of
            board or model. When creating by board, a dummy model is chosen and
            vice-versa.

    @returns: lab_inventory._LabInventory object.

    """
    histories = []
    for key, counts in data.iteritems():
        for p, pool in enumerate(POOL_CHOICES):
            for s, status in enumerate(STATUS_CHOICES):
                if by_board:
                    board = key
                    model = 'dummy_model'
                else:
                    board = 'dummy_board'
                    model = key
                histories.extend(
                        [_FakeHostHistory(board, model, pool, status)] *
                        counts[p][s])
    inventory = lab_inventory._LabInventory(histories)
    return inventory

class LabInventoryTests(unittest.TestCase):
    """Tests for the basic functions of `_LabInventory`.

    Contains basic coverage to show that after an inventory is
    created and DUTs with known status are added, the inventory
    counts match the counts of the added DUTs.

    """

    _BOARD_OR_MODEL_LIST = [
        'lion',
        'tiger',
        'bear',
        'aardvark',
        'platypus',
        'echidna',
        'elephant',
        'giraffe',
    ]


    def _check_inventory_details(self, inventory, data, by_board=True,
                                 msg=None):
        """Some common detailed inventory checks.

        The checks here are common to many tests below. At the same time, thsese
        checks are intentionally dumb -- if you need complex logic to figure out
        what to check, explicitly check for the final value instead of
        duplicating logic in the test.

        @param inventory: _LabInventory object to check.
        @param data Inventory data to check against. Same type as
                `create_inventory`.
        @param by_board: Whether data is keyed by board (or by model). See
                create_inventory.

        """
        if by_board:
            inventory_summary = inventory.by_board
        else:
            inventory_summary = inventory.by_model
        self.assertEqual(set(inventory_summary.keys()), set(data.keys()))
        for key, histories in inventory_summary.iteritems():
            calculated_counts = PoolStatusCounts(
                    StatusCounts(
                            histories.get_working(CRITICAL_POOL),
                            histories.get_broken(CRITICAL_POOL),
                            histories.get_idle(CRITICAL_POOL),
                    ),
                    StatusCounts(
                            histories.get_working(SPARE_POOL),
                            histories.get_broken(SPARE_POOL),
                            histories.get_idle(SPARE_POOL),
                    ),
            )
            self.assertEqual(data[key], calculated_counts, msg)

            self.assertEqual(len(histories.get_working_list()),
                             sum([p.good for p in data[key]]),
                             msg)
            self.assertEqual(len(histories.get_broken_list()),
                             sum([p.bad for p in data[key]]),
                             msg)
            self.assertEqual(len(histories.get_idle_list()),
                             sum([p.unused for p in data[key]]),
                             msg)


    def test_empty(self):
        """Test counts when there are no DUTs recorded."""
        inventory = create_inventory({})
        self.assertEqual(inventory.get_num_duts(), 0)
        self.assertEqual(inventory.get_num_boards(), 0)
        self.assertEqual(inventory.get_managed_boards(), set())
        self._check_inventory_details(inventory, {}, by_board=True)
        self.assertEqual(inventory.get_num_models(), 0)
        self.assertEqual(inventory.get_managed_models(), set())
        self._check_inventory_details(inventory, {}, by_board=False)


    def test_missing_board(self):
        """Test handling when the board is `None`."""
        inventory = create_inventory({
                None: PoolStatusCounts(
                        StatusCounts(1, 1, 1),
                        StatusCounts(1, 1, 1),
                ),
        })
        self.assertEqual(inventory.get_num_duts(), 0)
        self.assertEqual(inventory.get_num_boards(), 0)
        self.assertEqual(inventory.get_managed_boards(), set())
        self._check_inventory_details(inventory, {}, by_board=True)
        self.assertEqual(inventory.get_num_models(), 0)
        self.assertEqual(inventory.get_managed_models(), set())
        self._check_inventory_details(inventory, {}, by_board=False)


    def test_board_counts(self):
        """Test counts for various numbers of boards."""
        for board_count in [1, 2, len(self._BOARD_OR_MODEL_LIST)]:
            self.parameterized_test_board_count(board_count)


    def parameterized_test_board_count(self, board_count):
        """Parameterized test for testing a specific number of boards."""
        self.longMessage = True
        msg = '[board_count: %s]' % (board_count)
        boards = self._BOARD_OR_MODEL_LIST[:board_count]
        data = {
                b: PoolStatusCounts(
                        StatusCounts(1, 1, 1),
                        StatusCounts(1, 1, 1),
                )
                for b in boards
        }
        inventory = create_inventory(data, by_board=True)
        self.assertEqual(inventory.get_num_duts(), 6 * board_count, msg)
        self.assertEqual(inventory.get_num_boards(), board_count, msg)
        self.assertEqual(inventory.get_managed_boards(), set(boards), msg)
        self._check_inventory_details(inventory, data, by_board=True, msg=msg)
        self.assertEqual(inventory.get_num_models(), 1, msg)
        self.assertEqual(inventory.get_managed_models(), {'dummy_model'}, msg)


    def test_model_counts(self):
        """Test counts for various numbers of models."""
        for model_count in [1, 2, len(self._BOARD_OR_MODEL_LIST)]:
            self.parameterized_test_model_count(model_count)


    def parameterized_test_model_count(self, model_count):
        """Parameterized test for testing a specific number of models."""
        self.longMessage = True
        msg = '[model: %s]' % (model_count)
        models = self._BOARD_OR_MODEL_LIST[:model_count]
        data = {
                m: PoolStatusCounts(
                        StatusCounts(1, 1, 1),
                        StatusCounts(1, 1, 1),
                )
                for m in models
        }
        inventory = create_inventory(data, by_board=False)
        self.assertEqual(inventory.get_num_duts(), 6 * model_count, msg)
        self.assertEqual(inventory.get_num_models(), model_count, msg)
        self.assertEqual(inventory.get_managed_models(), set(models), msg)
        self._check_inventory_details(inventory, data, by_board=False, msg=msg)
        self.assertEqual(inventory.get_num_boards(), 1, msg)
        self.assertEqual(inventory.get_managed_boards(), {'dummy_board'}, msg)


    def test_single_dut_counts(self):
        """Test counts when there is a single DUT per board, and it is good."""
        for counts in [
                PoolStatusCounts(StatusCounts(1, 0, 0), StatusCounts(0, 0, 0)),
                PoolStatusCounts(StatusCounts(0, 1, 0), StatusCounts(0, 0, 0)),
                PoolStatusCounts(StatusCounts(0, 0, 1), StatusCounts(0, 0, 0)),
                PoolStatusCounts(StatusCounts(0, 0, 0), StatusCounts(1, 0, 0)),
                PoolStatusCounts(StatusCounts(0, 0, 0), StatusCounts(0, 1, 0)),
                PoolStatusCounts(StatusCounts(0, 0, 0), StatusCounts(0, 0, 1)),
        ]:
            self.parameterized_test_single_dut_counts(counts)

    def parameterized_test_single_dut_counts(self, counts):
        """Parmeterized test for single dut counts."""
        self.longMessage = True
        board = self._BOARD_OR_MODEL_LIST[0]
        data = {board: counts}
        msg = '[data: %s]' % (data,)
        inventory = create_inventory(data)
        self.assertEqual(inventory.get_num_duts(), 1, msg)
        self.assertEqual(inventory.get_num_boards(), 1, msg)
        self.assertEqual(inventory.get_managed_boards(), set(), msg)
        self._check_inventory_details(inventory, data, by_board=True, msg=msg)


# BOARD_MESSAGE_TEMPLATE -
# This is a sample of the output text produced by
# _generate_board_inventory_message().  This string is parsed by the
# tests below to construct a sample inventory that should produce
# the output, and then the output is generated and checked against
# this original sample.
#
# Constructing inventories from parsed sample text serves two
# related purposes:
#   - It provides a way to see what the output should look like
#     without having to run the script.
#   - It helps make sure that a human being will actually look at
#     the output to see that it's basically readable.
# This should also help prevent test bugs caused by writing tests
# that simply parrot the original output generation code.

_BOARD_MESSAGE_TEMPLATE = '''
Board                  Avail   Bad  Idle  Good Spare Total
lion                      -1    13     2    11    12    26
tiger                     -1     5     2     9     4    16
bear                       0     5     2    10     5    17
platypus                   4     2     2    20     6    24
aardvark                   7     2     2     6     9    10
'''


class BoardInventoryTests(unittest.TestCase):
    """Tests for `_generate_board_inventory_message()`.

    The tests create various test inventories designed to match the
    counts in `_BOARD_MESSAGE_TEMPLATE`, and asserts that the
    generated message text matches the original message text.

    Message text is represented as a list of strings, split on the
    `'\n'` separator.

    """

    def setUp(self):
        self.maxDiff = None
        lines = [x.strip() for x in _BOARD_MESSAGE_TEMPLATE.split('\n') if
                 x.strip()]
        self._header, self._board_lines = lines[0], lines[1:]
        self._board_data = []
        for l in self._board_lines:
            items = l.split()
            board = items[0]
            bad, idle, good, spare = [int(x) for x in items[2:-1]]
            self._board_data.append((board, (good, bad, idle, spare)))



    def _make_minimum_spares(self, counts):
        """Create a counts tuple with as few spare DUTs as possible."""
        good, bad, idle, spares = counts
        if spares > bad + idle:
            return PoolStatusCounts(
                    StatusCounts(good + bad +idle - spares, 0, 0),
                    StatusCounts(spares - bad - idle, bad, idle),
            )
        elif spares < bad:
            return PoolStatusCounts(
                    StatusCounts(good, bad - spares, idle),
                    StatusCounts(0, spares, 0),
            )
        else:
            return PoolStatusCounts(
                    StatusCounts(good, 0, idle + bad - spares),
                    StatusCounts(0, bad, spares - bad),
            )


    def _make_maximum_spares(self, counts):
        """Create a counts tuple with as many spare DUTs as possible."""
        good, bad, idle, spares = counts
        if good > spares:
            return PoolStatusCounts(
                    StatusCounts(good - spares, bad, idle),
                    StatusCounts(spares, 0, 0),
            )
        elif good + bad > spares:
            return PoolStatusCounts(
                    StatusCounts(0, good + bad - spares, idle),
                    StatusCounts(good, spares - good, 0),
            )
        else:
            return PoolStatusCounts(
                    StatusCounts(0, 0, good + bad + idle - spares),
                    StatusCounts(good, bad, spares - good - bad),
            )


    def _check_message(self, message):
        """Checks that message approximately matches expected string."""
        message = [x.strip() for x in message.split('\n') if x.strip()]
        self.assertIn(self._header, message)
        body = message[message.index(self._header) + 1:]
        self.assertEqual(body, self._board_lines)


    def test_minimum_spares(self):
        """Test message generation when the spares pool is low."""
        data = {
            board: self._make_minimum_spares(counts)
                for board, counts in self._board_data
        }
        inventory = create_inventory(data)
        message = lab_inventory._generate_board_inventory_message(inventory)
        self._check_message(message)

    def test_maximum_spares(self):
        """Test message generation when the critical pool is low."""
        data = {
            board: self._make_maximum_spares(counts)
                for board, counts in self._board_data
        }
        inventory = create_inventory(data)
        message = lab_inventory._generate_board_inventory_message(inventory)
        self._check_message(message)


    def test_ignore_no_spares(self):
        """Test that messages ignore boards with no spare pool."""
        data = {
            board: self._make_maximum_spares(counts)
                for board, counts in self._board_data
        }
        data['elephant'] = ((5, 4, 0), (0, 0, 0))
        inventory = create_inventory(data)
        message = lab_inventory._generate_board_inventory_message(inventory)
        self._check_message(message)


    def test_ignore_no_critical(self):
        """Test that messages ignore boards with no critical pools."""
        data = {
            board: self._make_maximum_spares(counts)
                for board, counts in self._board_data
        }
        data['elephant'] = ((0, 0, 0), (1, 5, 1))
        inventory = create_inventory(data)
        message = lab_inventory._generate_board_inventory_message(inventory)
        self._check_message(message)


    def test_ignore_no_bad(self):
        """Test that messages ignore boards with no bad DUTs."""
        data = {
            board: self._make_maximum_spares(counts)
                for board, counts in self._board_data
        }
        data['elephant'] = ((5, 0, 1), (5, 0, 1))
        inventory = create_inventory(data)
        message = lab_inventory._generate_board_inventory_message(inventory)
        self._check_message(message)


class _PoolInventoryTestBase(unittest.TestCase):
    """Parent class for tests relating to generating pool inventory messages.

    Func `setUp` in the class parses a given |message_template| to obtain
    header and body.
    """
    def _read_template(self, message_template):
        """Read message template for PoolInventoryTest and IdleInventoryTest.

        @param message_template: the input template to be parsed into: header
        and content (report_lines).

        """
        message_lines = message_template.split('\n')
        self._header = message_lines[1]
        self._report_lines = message_lines[2:-1]


    def _check_report_no_info(self, text):
        """Test a message body containing no reported info.

        The input `text` was created from a query to an inventory, which has
        no objects meet the query and leads to an `empty` return. Assert that
        the text consists of a single line starting with '(' and ending with ')'.

        @param text: Message body text to be tested.

        """
        self.assertTrue(len(text) == 1 and
                            text[0][0] == '(' and
                            text[0][-1] == ')')


    def _check_report(self, text):
        """Test a message against the passed |expected_content|.

        @param text: Message body text to be tested.
        @param expected_content: The ground-truth content to be compared with.

        """
        self.assertEqual(text, self._report_lines)


# _POOL_MESSAGE_TEMPLATE -
# This is a sample of the output text produced by
# _generate_pool_inventory_message().  This string is parsed by the
# tests below to construct a sample inventory that should produce
# the output, and then the output is generated and checked against
# this original sample.
#
# See the comments on _BOARD_MESSAGE_TEMPLATE above for the
# rationale on using sample text in this way.

_POOL_MESSAGE_TEMPLATE = '''
Board                    Bad  Idle  Good Total
lion                       5     2     6    13
tiger                      4     1     5    10
bear                       3     0     7    10
aardvark                   2     0     0     2
platypus                   1     1     1     3
'''

_POOL_ADMIN_URL = 'http://go/cros-manage-duts'


class PoolInventoryTests(_PoolInventoryTestBase):
    """Tests for `_generate_pool_inventory_message()`.

    The tests create various test inventories designed to match the
    counts in `_POOL_MESSAGE_TEMPLATE`, and assert that the
    generated message text matches the format established in the
    original message text.

    The output message text is parsed against the following grammar:
        <message> -> <intro> <pool> { "blank line" <pool> }
        <intro> ->
            Instructions to depty mentioning the admin page URL
            A blank line
        <pool> ->
            <description>
            <header line>
            <message body>
        <description> ->
            Any number of lines describing one pool
        <header line> ->
            The header line from `_POOL_MESSAGE_TEMPLATE`
        <message body> ->
            Any number of non-blank lines

    After parsing messages into the parts described above, various
    assertions are tested against the parsed output, including
    that the message body matches the body from
    `_POOL_MESSAGE_TEMPLATE`.

    Parse message text is represented as a list of strings, split on
    the `'\n'` separator.

    """
    def setUp(self):
        super(PoolInventoryTests, self)._read_template(_POOL_MESSAGE_TEMPLATE)
        self._board_data = []
        for l in self._report_lines:
            items = l.split()
            board = items[0]
            bad = int(items[1])
            idle = int(items[2])
            good = int(items[3])
            self._board_data.append((board, (good, bad, idle)))


    def _create_histories(self, pools, board_data):
        """Return a list suitable to create a `_LabInventory` object.

        Creates a list of `_FakeHostHistory` objects that can be
        used to create a lab inventory.  `pools` is a list of strings
        naming pools, and `board_data` is a list of tuples of the
        form
            `(board, (goodcount, badcount))`
        where
            `board` is a board name.
            `goodcount` is the number of working DUTs in the pool.
            `badcount` is the number of broken DUTs in the pool.

        @param pools       List of pools for which to create
                           histories.
        @param board_data  List of tuples containing boards and DUT
                           counts.
        @return A list of `_FakeHostHistory` objects that can be
                used to create a `_LabInventory` object.

        """
        histories = []
        status_choices = (_WORKING, _BROKEN, _UNUSED)
        for pool in pools:
            for board, counts in board_data:
                for status, count in zip(status_choices, counts):
                    for x in range(0, count):
                        histories.append(
                            _FakeHostHistory(board, None, pool, status))
        return histories


    def _parse_pool_summaries(self, histories):
        """Parse message output according to the grammar above.

        Create a lab inventory from the given `histories`, and
        generate the pool inventory message.  Then parse the message
        and return a dictionary mapping each pool to the message
        body parsed after that pool.

        Tests the following assertions:
          * Each <description> contains a mention of exactly one
            pool in the `CRITICAL_POOLS` list.
          * Each pool is mentioned in exactly one <description>.
        Note that the grammar requires the header to appear once
        for each pool, so the parsing implicitly asserts that the
        output contains the header.

        @param histories  Input used to create the test
                          `_LabInventory` object.
        @return A dictionary mapping board names to the output
                (a list of lines) for the board.

        """
        inventory = lab_inventory._LabInventory(histories)
        message = lab_inventory._generate_pool_inventory_message(
                inventory).split('\n')
        poolset = set(lab_inventory.CRITICAL_POOLS)
        seen_url = False
        seen_intro = False
        description = ''
        board_text = {}
        current_pool = None
        for line in message:
            if not seen_url:
                if _POOL_ADMIN_URL in line:
                    seen_url = True
            elif not seen_intro:
                if not line:
                    seen_intro = True
            elif current_pool is None:
                if line == self._header:
                    pools_mentioned = [p for p in poolset
                                           if p in description]
                    self.assertEqual(len(pools_mentioned), 1)
                    current_pool = pools_mentioned[0]
                    description = ''
                    board_text[current_pool] = []
                    poolset.remove(current_pool)
                else:
                    description += line
            else:
                if line:
                    board_text[current_pool].append(line)
                else:
                    current_pool = None
        self.assertEqual(len(poolset), 0)
        return board_text


    def test_no_shortages(self):
        """Test correct output when no pools have shortages."""
        board_text = self._parse_pool_summaries([])
        for text in board_text.values():
            self._check_report_no_info(text)


    def test_one_pool_shortage(self):
        """Test correct output when exactly one pool has a shortage."""
        for pool in lab_inventory.CRITICAL_POOLS:
            histories = self._create_histories((pool,),
                                               self._board_data)
            board_text = self._parse_pool_summaries(histories)
            for checkpool in lab_inventory.CRITICAL_POOLS:
                text = board_text[checkpool]
                if checkpool == pool:
                    self._check_report(text)
                else:
                    self._check_report_no_info(text)


    def test_all_pool_shortages(self):
        """Test correct output when all pools have a shortage."""
        histories = []
        for pool in lab_inventory.CRITICAL_POOLS:
            histories.extend(
                self._create_histories((pool,),
                                       self._board_data))
        board_text = self._parse_pool_summaries(histories)
        for pool in lab_inventory.CRITICAL_POOLS:
            self._check_report(board_text[pool])


    def test_full_board_ignored(self):
        """Test that boards at full strength are not reported."""
        pool = lab_inventory.CRITICAL_POOLS[0]
        full_board = [('echidna', (5, 0, 0))]
        histories = self._create_histories((pool,),
                                           full_board)
        text = self._parse_pool_summaries(histories)[pool]
        self._check_report_no_info(text)
        board_data = self._board_data + full_board
        histories = self._create_histories((pool,), board_data)
        text = self._parse_pool_summaries(histories)[pool]
        self._check_report(text)


    def test_spare_pool_ignored(self):
        """Test that reporting ignores the spare pool inventory."""
        spare_pool = lab_inventory.SPARE_POOL
        spare_data = self._board_data + [('echidna', (0, 5, 0))]
        histories = self._create_histories((spare_pool,),
                                           spare_data)
        board_text = self._parse_pool_summaries(histories)
        for pool in lab_inventory.CRITICAL_POOLS:
            self._check_report_no_info(board_text[pool])


_IDLE_MESSAGE_TEMPLATE = '''
Hostname                       Board                Pool
chromeos4-row12-rack4-host7    tiger                bvt
chromeos1-row3-rack1-host2     lion                 bvt
chromeos3-row2-rack2-host5     lion                 cq
chromeos2-row7-rack3-host11    platypus             suites
'''


class IdleInventoryTests(_PoolInventoryTestBase):
    """Tests for `_generate_idle_inventory_message()`.

    The tests create idle duts that match the counts and pool in
    `_IDLE_MESSAGE_TEMPLATE`. In test, it asserts that the generated
    idle message text matches the format established in
    `_IDLE_MESSAGE_TEMPLATE`.

    Parse message text is represented as a list of strings, split on
    the `'\n'` separator.

    """

    def setUp(self):
        super(IdleInventoryTests, self)._read_template(_IDLE_MESSAGE_TEMPLATE)
        self._host_data = []
        for h in self._report_lines:
            items = h.split()
            hostname = items[0]
            board = items[1]
            pool = items[2]
            self._host_data.append((hostname, board, pool))
        self._histories = []
        self._histories.append(_FakeHostHistory('echidna', None, 'bvt',
                                                _BROKEN))
        self._histories.append(_FakeHostHistory('lion', None, 'bvt', _WORKING))


    def _add_idles(self):
        """Add idle duts from `_IDLE_MESSAGE_TEMPLATE`."""
        idle_histories = [_FakeHostHistory(
                board, None, pool, _UNUSED, hostname=hostname)
                        for hostname, board, pool in self._host_data]
        self._histories.extend(idle_histories)


    def _check_header(self, text):
        """Check whether header in the template `_IDLE_MESSAGE_TEMPLATE` is in
        passed text."""
        self.assertIn(self._header, text)


    def _get_idle_message(self, histories):
        """Generate idle inventory and obtain its message.

        @param histories: Used to create lab inventory.

        @return the generated idle message.

        """
        inventory = lab_inventory._LabInventory(histories)
        message = lab_inventory._generate_idle_inventory_message(
                inventory).split('\n')
        return message


    def test_check_idle_inventory(self):
        """Test that reporting all the idle DUTs for every pool, sorted by
        lab_inventory.MANAGED_POOLS.
        """
        self._add_idles()

        message = self._get_idle_message(self._histories)
        self._check_header(message)
        self._check_report(message[message.index(self._header) + 1 :])


    def test_no_idle_inventory(self):
        """Test that reporting no idle DUTs."""
        message = self._get_idle_message(self._histories)
        self._check_header(message)
        self._check_report_no_info(
                message[message.index(self._header) + 1 :])


class CommandParsingTests(unittest.TestCase):
    """Tests for command line argument parsing in `_parse_command()`."""

    _NULL_NOTIFY = ['--board-notify=', '--pool-notify=']

    def setUp(self):
        dirpath = '/usr/local/fubar'
        self._command_path = os.path.join(dirpath,
                                          'site_utils',
                                          'arglebargle')
        self._logdir = os.path.join(dirpath, lab_inventory._LOGDIR)


    def _parse_arguments(self, argv, notify=_NULL_NOTIFY):
        full_argv = [self._command_path] + argv + notify
        return lab_inventory._parse_command(full_argv)


    def _check_non_notify_defaults(self, notify_option):
        arguments = self._parse_arguments([], notify=[notify_option])
        self.assertEqual(arguments.duration,
                         lab_inventory._DEFAULT_DURATION)
        self.assertIsNone(arguments.recommend)
        self.assertFalse(arguments.repair_loops)
        self.assertFalse(arguments.debug)
        self.assertEqual(arguments.logdir, self._logdir)
        self.assertEqual(arguments.boardnames, [])
        return arguments


    def test_empty_arguments(self):
        """Test that an empty argument list is an error."""
        arguments = self._parse_arguments([], notify=[])
        self.assertIsNone(arguments)


    def test_argument_defaults(self):
        """Test that option defaults match expectations."""
        arguments = self._check_non_notify_defaults(self._NULL_NOTIFY[0])
        self.assertEqual(arguments.board_notify, [''])
        self.assertEqual(arguments.pool_notify, [])
        arguments = self._check_non_notify_defaults(self._NULL_NOTIFY[1])
        self.assertEqual(arguments.board_notify, [])
        self.assertEqual(arguments.pool_notify, [''])


    def test_board_arguments(self):
        """Test that non-option arguments are returned in `boardnames`."""
        boardlist = ['aardvark', 'echidna']
        arguments = self._parse_arguments(boardlist)
        self.assertEqual(arguments.boardnames, boardlist)


    def test_recommend_option(self):
        """Test parsing of the `--recommend` option."""
        for opt in ['-r', '--recommend']:
            for recommend in ['5', '55']:
                arguments = self._parse_arguments([opt, recommend])
                self.assertEqual(arguments.recommend, int(recommend))


    def test_repair_loop_option(self):
        """Test parsing of the `--repair-loops` option."""
        arguments = self._parse_arguments(['--repair-loops'])
        self.assertTrue(arguments.repair_loops)


    def test_debug_option(self):
        """Test parsing of the `--debug` option."""
        arguments = self._parse_arguments(['--debug'])
        self.assertTrue(arguments.debug)


    def test_duration(self):
        """Test parsing of the `--duration` option."""
        for opt in ['-d', '--duration']:
            for duration in ['1', '11']:
                arguments = self._parse_arguments([opt, duration])
                self.assertEqual(arguments.duration, int(duration))


    def _check_email_option(self, option, getlist):
        """Test parsing of e-mail address options.

        This is a helper function to test the `--board-notify` and
        `--pool-notify` options.  It tests the following cases:
          * `--option a1` gives the list [a1]
          * `--option ' a1 '` gives the list [a1]
          * `--option a1 --option a2` gives the list [a1, a2]
          * `--option a1,a2` gives the list [a1, a2]
          * `--option 'a1, a2'` gives the list [a1, a2]

        @param option  The option to be tested.
        @param getlist A function to return the option's value from
                       parsed command line arguments.

        """
        a1 = 'mumble@mumbler.com'
        a2 = 'bumble@bumbler.org'
        arguments = self._parse_arguments([option, a1], notify=[])
        self.assertEqual(getlist(arguments), [a1])
        arguments = self._parse_arguments([option, ' ' + a1 + ' '],
                                          notify=[])
        self.assertEqual(getlist(arguments), [a1])
        arguments = self._parse_arguments([option, a1, option, a2],
                                          notify=[])
        self.assertEqual(getlist(arguments), [a1, a2])
        arguments = self._parse_arguments(
                [option, ','.join([a1, a2])], notify=[])
        self.assertEqual(getlist(arguments), [a1, a2])
        arguments = self._parse_arguments(
                [option, ', '.join([a1, a2])], notify=[])
        self.assertEqual(getlist(arguments), [a1, a2])


    def test_board_notify(self):
        """Test parsing of the `--board-notify` option."""
        self._check_email_option('--board-notify',
                                 lambda a: a.board_notify)


    def test_pool_notify(self):
        """Test parsing of the `--pool-notify` option."""
        self._check_email_option('--pool-notify',
                                 lambda a: a.pool_notify)


    def test_logdir_option(self):
        """Test parsing of the `--logdir` option."""
        logdir = '/usr/local/whatsis/logs'
        arguments = self._parse_arguments(['--logdir', logdir])
        self.assertEqual(arguments.logdir, logdir)


if __name__ == '__main__':
    # Some of the functions we test log messages.  Prevent those
    # messages from showing up in test output.
    logging.getLogger().setLevel(logging.CRITICAL)
    unittest.main()
