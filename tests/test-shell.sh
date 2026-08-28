#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later

set -Eeuo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

bash -n \
	"$root/src/yogabook-gnss-run" \
	"$root/src/yogabook-gnss-health" \
	"$root/debian/postinst" \
	"$root/debian/prerm"
python3 -m py_compile \
	"$root/src/yogabook_gnss_runtime.py" \
	"$root/src/yogabook-gnss-import" \
	"$root/src/yogabook-gnss-build-runtime"

grep -Fq 'PrivateMounts=yes' "$root/systemd/yogabook-gnss.service"
grep -Fq 'PrivateNetwork=yes' "$root/systemd/yogabook-gnss.service"
grep -Fq 'CPUWeight=10' "$root/systemd/yogabook-gnss.service"
grep -Fq 'CPUQuota=50%' "$root/systemd/yogabook-gnss.service"
grep -Fq 'MemoryHigh=64M' "$root/systemd/yogabook-gnss.service"
grep -Fq 'MemoryMax=128M' "$root/systemd/yogabook-gnss.service"
grep -Fq 'TasksMax=32' "$root/systemd/yogabook-gnss.service"
grep -Fq 'StartLimitBurst=3' "$root/systemd/yogabook-gnss.service"
grep -Fq 'KERNELS=="8086228A:01"' "$root/udev/60-yogabook-gnss.rules"
grep -Fq 'ENV{ID_MM_DEVICE_IGNORE}="1"' "$root/udev/60-yogabook-gnss.rules"
grep -Fq '/var/lib/yogabook-gnss/root/data/gps/nmeapipe rw,' \
	"$root/apparmor/yogabook-gnss-gpsd"
grep -Fq '#include <local/yogabook-gnss-gpsd>' "$root/debian/postinst"
grep -Fq 'systemctl", "stop", "yogabook-gnss.service' \
	"$root/src/yogabook-gnss-import"
grep -Fq 'rfkill block gps' "$root/src/yogabook-gnss-run"
grep -Fq 'sleep 0.5' "$root/src/yogabook-gnss-run"
grep -Fq '/dev/ttyS5' "$root/src/yogabook-gnss-run"
grep -Fq 'Periodi' "$root/src/yogabook-gnss-run"
grep -Fq 'status == 128 + 15' "$root/src/yogabook-gnss-run"
grep -Fq -- '--require-sky' "$root/src/yogabook-gnss-health"
grep -Fq -- '--require-fix' "$root/src/yogabook-gnss-health"
grep -Fq 'NMEA GGA/RMC/GSV stream: present' "$root/src/yogabook-gnss-health"
grep -Fq 'timeout 30 gpspipe' "$root/src/yogabook-gnss-health"

if rg -n --hidden --glob '!tests/test-shell.sh' \
	'd135fc515dd3802dcd9fe807b942e1e112767f56b5a44463c64121317753c715' \
	"$root" | grep -Ev 'README.md|yogabook_gnss_runtime.py'; then
	echo "unexpected proprietary daemon hash reference" >&2
	exit 1
fi

echo "Shell and policy checks passed"
