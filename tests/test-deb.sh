#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later

set -Eeuo pipefail

package=${1:?usage: test-deb.sh PACKAGE.deb}
temporary_root=${TMPDIR:-/tmp}
temporary=$(mktemp -d "$temporary_root/yogabook-gnss-deb.XXXXXX")
trap 'rm -rf -- "$temporary"' EXIT

dpkg-deb -x "$package" "$temporary/root"
dpkg-deb -e "$package" "$temporary/control"

test -x "$temporary/root/usr/sbin/yogabook-gnss-import"
test -x "$temporary/root/usr/sbin/yogabook-gnss-build-runtime"
test -x "$temporary/root/usr/sbin/yogabook-gnss-health"
test -x "$temporary/root/usr/libexec/yogabook-gnss-run"
test -f "$temporary/root/usr/lib/systemd/system/yogabook-gnss.service"
test -f "$temporary/root/usr/lib/systemd/system/gpsd.service.d/gpsd-yogabook.conf"
test -f "$temporary/root/usr/lib/udev/rules.d/60-yogabook-gnss.rules"
test -f "$temporary/root/etc/apparmor.d/local/yogabook-gnss-gpsd"

if find "$temporary/root" -type f -print0 | xargs -0 file | grep -q 'ELF'; then
	echo "binary package unexpectedly contains an ELF file" >&2
	exit 1
fi
if find "$temporary/root" -path '*/system/vendor/bin/gpsd' -o -path '*/system/lib64/*' | grep -q .; then
	echo "binary package contains prohibited Android runtime content" >&2
	exit 1
fi

echo "Debian payload checks passed"
