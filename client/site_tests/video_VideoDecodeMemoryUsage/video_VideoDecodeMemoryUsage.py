# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re
import time

from math import sqrt

from telemetry.core import browser_options, browser_finder

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import httpd

TEST_PAGE = 'content.html'

# The keys to access the content of memry stats.
KEY_RENDERER = 'Renderer'
KEY_BROWSER = 'Browser'
KEY_GPU = 'Gpu'
KEY_RSS = 'WorkingSetSize'

# The number of iterations to be run before measuring the memory usage.
# Just ensure we have fill up the caches/buffers so that we can get
# a more stable/correct result.
WARMUP_COUNT = 10

# Number of iterations per measurement.
EVALUATION_COUNT = 50

# The minimal number of samples for memory-leak test.
MIN_SAMPLE_SIZE = 10

# The approximate values of the student's t-distribution at 95% confidence.
# See http://en.wikipedia.org/wiki/Student's_t-distribution
T_095 = [None, # No value for degree of freedom 0
    12.706205, 4.302653, 3.182446, 2.776445, 2.570582, 2.446912, 2.364624,
     2.306004, 2.262157, 2.228139, 2.200985, 2.178813, 2.160369, 2.144787,
     2.131450, 2.119905, 2.109816, 2.100922, 2.093024, 2.085963, 2.079614,
     2.073873, 2.068658, 2.063899, 2.059539, 2.055529, 2.051831, 2.048407,
     2.045230, 2.042272, 2.039513, 2.036933, 2.034515, 2.032245, 2.030108,
     2.028094, 2.026192, 2.024394, 2.022691, 2.021075, 2.019541, 2.018082,
     2.016692, 2.015368, 2.014103, 2.012896, 2.011741, 2.010635, 2.009575,
     2.008559, 2.007584, 2.006647, 2.005746, 2.004879, 2.004045, 2.003241,
     2.002465, 2.001717, 2.000995, 2.000298, 1.999624, 1.998972, 1.998341,
     1.997730, 1.997138, 1.996564, 1.996008, 1.995469, 1.994945, 1.994437,
     1.993943, 1.993464, 1.992997, 1.992543, 1.992102, 1.991673, 1.991254,
     1.990847, 1.990450, 1.990063, 1.989686, 1.989319, 1.988960, 1.988610,
     1.988268, 1.987934, 1.987608, 1.987290, 1.986979, 1.986675, 1.986377,
     1.986086, 1.985802, 1.985523, 1.985251, 1.984984, 1.984723, 1.984467,
     1.984217, 1.983972, 1.983731]

# The memory leak (bytes/iteration) we can tolerate.
MEMORY_LEAK_THRESHOLD = 1024 * 1024

# Regular expression used to parse the content of '/proc/meminfo'
# The content of the file looks like:
# MemTotal:       65904768 kB
# MemFree:        14248152 kB
# Buffers:          508836 kB
MEMINFO_RE = re.compile('^(\w+):\s+(\d+)', re.MULTILINE)
MEMINFO_PATH = '/proc/meminfo'

# We sum up the following values in '/proc/meminfo' to represent
# the kernel memory usage.
KERNEL_MEMORY_ENTRIES = ['Slab', 'Shmem', 'KernelStack', 'PageTables']

# Paths of files to read graphics memory usage from
X86_GEM_OBJECTS_PATH = '/sys/kernel/debug/dri/0/i915_gem_objects'
ARM_GEM_OBJECTS_PATH = '/sys/kernel/gebug/dri/0/exynos_gem_objects'

GEM_OBJECTS_PATH = {'x86_64': X86_GEM_OBJECTS_PATH,
                    'i386'  : X86_GEM_OBJECTS_PATH,
                    'arm'   : ARM_GEM_OBJECTS_PATH}

# To parse the content of the files abvoe. The first line looks like:
# "432 objects, 272699392 bytes"
GEM_OBJECTS_RE = re.compile('(\d+)\s+objects,\s+(\d+)\s+bytes')

# The default sleep time, in seconds.
SLEEP_TIME = 3

def _get_kernel_memory_usage():
    """Gets the kernel memory usage."""
    with file(MEMINFO_PATH) as f:
        m = {x.group(1): int(x.group(2))
                   for x in MEMINFO_RE.finditer(f.read())}

    # Sum up the usage and convert from kB to bytes
    return sum(m[key] for key in KERNEL_MEMORY_ENTRIES) * 1024


def _get_graphics_memory_usage():
    """Get the memory usage of the graphics module."""
    arch = utils.get_cpu_arch()
    try:
        path = GEM_OBJECTS_PATH[arch]
    except KeyError:
        raise error.TestError('unknown platform: %s' % arch)

    with open(path, 'r') as input:
        for line in input:
            result = GEM_OBJECTS_RE.match(line)
            if result:
                return int(result.group(2))
    raise eror.TestError('Cannot parse the content')


def _get_linear_regression_slope(x, y):
    """
    Gets slope and the confidence interval of the linear regression based on
    the given xs and ys.

    This function returns a tuple (beta, delta), where the beta is the slope
    of the linear regression and delta is the range of the confidence
    interval, i.e., confidence interval = (beta + delta, beta - delta).
    """
    assert len(x) == len(y)
    n = len(x)
    sx, sy = sum(x), sum(y)
    sxx = sum(v * v for v in x)
    syy = sum(v * v for v in y)
    sxy = sum(u * v for u, v in zip(x, y))
    beta = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    alpha = (sy - beta * sx) / n
    stderr2 = (n * syy - sy * sy -
               beta * beta * (n * sxx - sx * sx)) / (n * (n - 2))
    std_beta = sqrt((n * stderr2) / (n * sxx - sx * sx))
    t_095 = T_095[n - 2]
    delta_beta = t_095 * std_beta;
    return (beta, t_095 * std_beta)


def _assert_no_memory_leak(name, mem_usage, threshold = MEMORY_LEAK_THRESHOLD):
    """Helper function to check memory leak"""
    index = range(len(mem_usage))
    slope, delta = _get_linear_regression_slope(index, mem_usage)
    logging.info('confidence interval: %s - %s, %s',
                 name, slope - delta, slope + delta)
    if (slope - delta > threshold):
        logging.debug('memory usage for %s - %s', name, mem_usage);
        raise error.TestFail('leak detected: %s - %s' % (name, slope - delta))


class MemoryTest(object):
    """The base class of all memory tests"""

    def _get_memory_usage(self):
        """Helper function to get the memory usage.

        It returns a tuple of five elements:
            (browser_usage, renderer_usage, gpu_usage, kernel_usage,
             graphics_usage)

        browser_usage: the RSS of the browser process
        rednerers_usage: the total RSS of all renderer processes
        rednerers_usage: the total RSS of all gpu processes
        kernel_usage: the memory used in kernel
        graphics_usage: the memory usage reported by the graphics driver
        """
        # Force to collect garbage before measuring memory
        for i in xrange(len(self.browser.tabs)):
            # TODO(owenlin): Change to "for t in tabs" once
            #                http://crbug.com/239735 is resolved
            self.browser.tabs[i].CollectGarbage()

        m = self.browser.memory_stats

        result = (m[KEY_BROWSER][KEY_RSS],
                  m[KEY_RENDERER][KEY_RSS],
                  m[KEY_GPU][KEY_RSS],
                  _get_kernel_memory_usage(),
                  _get_graphics_memory_usage())

        # TODO(owenlin): Uncomment the following line once
        #                http://crbug.com/241749 is resolved
        # assert all(x > 0 for x in result) # Make sure we read values back
        return result


    def initialize(self, browser, args):
        """A callback function, executed before loop().

        @param browser: the telemetry entry for the browser under test
        @param args: extra arguments for the test
        """
        self.browser = browser
        self.args = args


    def loop(self):
        """A callback function. It is the main memory test function."""
        pass

    def cleanup(self):
        """A callback function, executed after loop()."""
        pass


    def run(self, browser, args,
            warmup_count = WARMUP_COUNT,
            eval_count = EVALUATION_COUNT):
        """Runs this memory test case.
        @param browser: the telemetry entry of the browser under test

        @param warmup_count: run loop() for warmup_count times to make sure the
               memory usage has been stabalize.

        @param eval_count: run loop() for eval_count times to measure the memory
               usage.
        """
        self.initialize(browser, args)
        try:
            for i in xrange(warmup_count):
                self.loop()

            names = ['browser', 'renderers', 'gpu', 'kernel', 'graphics']
            metrics = [[] for n in names]
            for i in xrange(eval_count):
                self.loop()
                result = self._get_memory_usage()
                for n, m, r in zip(names, metrics, result):
                    m.append(r)
                    if len(m) >= MIN_SAMPLE_SIZE:
                        _assert_no_memory_leak(n, m)
            for n, m in zip(names, metrics):
                logging.info('memory usage for %s - %s', n, m)
        finally:
            self.cleanup()


def _change_source_and_play(tab, video):
    tab.EvaluateJavaScript('changeSourceAndPlay("%s")' % video)

def _preload_videos(tab, videos):
    # The python's SimpleHTTPServer doesn't support range-related response
    # headers. That causes the video gets stucked at the end.
    # See http://crbug.com/241722 for more details.
    #
    # A workaround is to preload the videos. Thereafter, the video can play
    # from the cache directly.
    for v in videos:
        _change_source_and_play(tab, v)
        time.sleep(SLEEP_TIME)

def _assert_video_is_playing(tab):
    if not tab.EvaluateJavaScript('isVideoPlaying()'):
        raise error.TestError('video is stopped')
    startTime = tab.EvaluateJavaScript('getVideoCurrentTime()')
    for i in xrange(5):
        time.sleep(0.5)
        now = tab.EvaluateJavaScript('getVideoCurrentTime()')
        if now != startTime: return
    raise error.TestError('video is stuck')


class OpenTabPlayVideo(MemoryTest):
    """A memory test case:
        Open a tab, play a video and close the tab.
    """

    def loop(self):
        browser = self.browser
        tab = browser.tabs.New()
        tab.Navigate('http://localhost:8000/%s' % TEST_PAGE)
        _change_source_and_play(tab, self.args['video'])
        _assert_video_is_playing(tab);
        time.sleep(SLEEP_TIME)
        tab.Close()

        # Wait a while for the closed tab to clean up all used resources
        time.sleep(SLEEP_TIME)


class PlayVideo(MemoryTest):
    """A memory test case: keep playing a video."""

    def initialize(self, browser, args):
        super(PlayVideo, self).initialize(browser, args)
        tab = browser.tabs.New()
        video = self.args['video']

        tab.Navigate('http://localhost:8000/%s' % TEST_PAGE)
        _preload_videos(tab, [video])
        _change_source_and_play(tab, video)
        self.activeTab = tab


    def loop(self):
        time.sleep(SLEEP_TIME)
        _assert_video_is_playing(self.activeTab);


    def cleanup(self):
        self.activeTab.Close()


class ChangeVideoSource(MemoryTest):
    """A memory test case: change the "src" property of <video> object to
    load different video sources."""


    def initialize(self, browser, args):
        super(ChangeVideoSource, self).initialize(browser, args)
        tab = browser.tabs.New()
        videos = self.args['videos']

        tab.Navigate('http://localhost:8000/%s' % TEST_PAGE)
        _preload_videos(tab, self.args['videos'])
        self.activeTab = tab


    def loop(self):
        for video in self.args['videos']:
            _change_source_and_play(self.activeTab, video);
            time.sleep(SLEEP_TIME)
            _assert_video_is_playing(self.activeTab);


    def cleanup(self):
        self.activeTab.Close()


class video_VideoDecodeMemoryUsage(test.test):
    """This is a memory leak test for video playback."""
    version = 1

    def initialize(self):
        self._listener = httpd.HTTPListener(8000, docroot = self.bindir)
        self._listener.run()


    def cleanup(self):
        self._listener.stop()


    def run_once(self, testcase, **args):
        """
        This test run one of the memory test case defined above.
        """

        default_options = browser_options.BrowserOptions()
        default_options.browser_type = 'system'
        browser_to_create = browser_finder.FindBrowser(default_options)
        logging.debug('Browser Found: %s', browser_to_create)

        test_case_class = globals()[testcase]
        with browser_to_create.Create() as browser:
            test_case_class().run(browser, args)
