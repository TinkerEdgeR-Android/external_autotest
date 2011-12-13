#!/bin/bash
# Copyright (c) 2011 The Chromium OS Authors.
#
# Based on:
# http://bazaar.launchpad.net/~ubuntu-bugcontrol/qa-regression-testing/master/view/head:/scripts/kernel-security/ptrace/ptrace-restrictions.sh
# Copyright (C) 2010-2011 Canonical Ltd.
# License: GPLv3
# Author: Kees Cook <kees.cook@canonical.com>
set -x
set -e
if [ "$(whoami)" = "root" ]; then
    echo "Cannot be root for this test" >&2
    exit 1
fi

export LANG=C

rc=0

# Check we can see direct children.
OUT=$(gdb -ex run -ex quit --batch ./sleeper </dev/null 2>&1)
if echo "$OUT" | grep -q 'Quit anyway'; then
    echo "ok: children correctly allow ptrace"
else
    echo "FAIL: Children unexpectedly not allow ptrace"
    rc=1
fi

# Check we can't see cousins.
sleep 120 &
pid=$!
OUT=$(gdb -ex "attach $pid" -ex "quit" --batch </dev/null 2>&1)
if echo "$OUT" | grep -q 'Operation not permitted'; then
    echo "ok: cousins correctly not allow ptrace"
else
    echo "FAIL: cousins unexpectedly allow ptrace"
    rc=1
fi

# Validate we can see cousin /proc entries.
if ls -la /proc/$pid/exe >/dev/null 2>&1; then
    echo "ok: cousins correctly visible in /proc"
else
    echo "FAIL: cousins unexpectedly invisible in /proc"
    rc=1
fi

# Check we can't attach to init.
OUT=$(gdb -ex "attach 1" -ex "quit" --batch </dev/null 2>&1)
if echo "$OUT" | grep -q 'Operation not permitted'; then
    echo "ok: init correctly not allowing ptrace"
else
    echo "FAIL: init unexpectedly allowed ptrace"
    rc=1
fi

# Check we can't see init.
if ! ls -la /proc/1/exe >/dev/null 2>&1; then
    echo "ok: init correctly invisible in /proc"
else
    echo "FAIL: init unexpectedly visible in /proc"
    rc=1
fi

# Drop the sleep process and destroy it without disrupting the shell.
disown $pid
kill $pid

# Validate that prctl(PR_SET_PTRACER, 0, ...) works to delete tracer.
./sleeper 0 120 &
pid=$!
OUT=$(gdb -ex "attach $pid" -ex "quit" --batch </dev/null 2>&1)
prctl="prctl(PR_SET_PTRACER, 0, ...)"
if echo "$OUT" | grep -q 'Operation not permitted'; then
    echo "ok: $prctl correctly not allowed ptrace"
else
    echo "FAIL: $prctl unexpectedly allowed ptrace"
    rc=1
fi
disown $pid
kill $pid

# Validate near ancestor allowed with PR_SET_PTRACER use.
./sleeper $$ 120 &
pid=$!
OUT=$(gdb -ex "attach $pid" -ex "quit" --batch </dev/null 2>&1)
prctl="prctl(PR_SET_PTRACER, parent, ...)"
if echo "$OUT" | grep -q 'Quit anyway'; then
    echo "ok: $prctl correctly allowed ptrace"
else
    echo "FAIL: $prctl unexpectedly not allowed ptrace"
    rc=1
fi
disown $pid
kill $pid

# Validate distant ancestor allowed with PR_SET_PTRACER use.
./sleeper 1 120 &
pid=$!
OUT=$(gdb -ex "attach $pid" -ex "quit" --batch </dev/null 2>&1)
prctl="prctl(PR_SET_PTRACER, 1, ...)"
if echo "$OUT" | grep -q 'Quit anyway'; then
    echo "ok: $prctl correctly allowed ptrace"
else
    echo "FAIL: $prctl unexpectedly not allowed ptrace"
    rc=1
fi
disown $pid
kill $pid

exit $rc
