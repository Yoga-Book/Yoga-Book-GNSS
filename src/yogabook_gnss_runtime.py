#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validation and import helpers for the Yoga Book stock GNSS runtime."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from typing import Iterable


EXPECTED_GPSD_SHA256 = (
    "d135fc515dd3802dcd9fe807b942e1e112767f56b5a44463c64121317753c715"
)

EXPECTED_BUILD_PROPERTIES = {
    "ro.build.display.id": "YB1-X90F_USR_S100043_1709020000_WW08_BP_ROW",
    "ro.product.model": "Lenovo YB1-X90F",
    "ro.build.fingerprint": (
        "Lenovo/yeti_10_row_wifi/yeti:7.1.1/NMF26X/"
        "LenovoYB1-X90F_S100043_170902:user/release-keys"
    ),
}

RUNTIME_FILES = (
    "system/bin/linker64",
    "system/build.prop",
    "system/lib64/libEGL.so",
    "system/lib64/libGLESv2.so",
    "system/lib64/libbacktrace.so",
    "system/lib64/libbase.so",
    "system/lib64/libbinder.so",
    "system/lib64/libc++.so",
    "system/lib64/libc.so",
    "system/lib64/libcrypto.so",
    "system/lib64/libcutils.so",
    "system/lib64/libdl.so",
    "system/lib64/libgui.so",
    "system/lib64/libhardware.so",
    "system/lib64/libhardware_legacy.so",
    "system/lib64/libicuuc.so",
    "system/lib64/liblog.so",
    "system/lib64/liblzma.so",
    "system/lib64/libm.so",
    "system/lib64/libnetutils.so",
    "system/lib64/libssl.so",
    "system/lib64/libstdc++.so",
    "system/lib64/libsync.so",
    "system/lib64/libui.so",
    "system/lib64/libunwind.so",
    "system/lib64/libutils.so",
    "system/lib64/libwpa_client.so",
    "system/vendor/bin/gpsd",
    "system/vendor/etc/gps.cer",
    "system/vendor/etc/gps.conf",
    "system/vendor/etc/gps.xml",
)

OPTIONAL_RUNTIME_FILES = (
    "system/usr/share/zoneinfo/tzdata",
)


class RuntimeError(ValueError):
    """A supplied runtime is unsafe, incomplete, or incompatible."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_source_identity(root: Path) -> dict[str, str]:
    build_prop = root / "system/build.prop"
    properties: dict[str, str] = {}

    try:
        lines = build_prop.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError(f"cannot read source build identity: {error}") from error

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name in properties:
            raise RuntimeError(f"duplicate source build property: {name}")
        properties[name] = value

    for name, expected in EXPECTED_BUILD_PROPERTIES.items():
        actual = properties.get(name)
        if actual != expected:
            raise RuntimeError(
                f"unsupported source build property {name}: "
                f"expected {expected!r}, got {actual!r}"
            )

    return {name: properties[name] for name in EXPECTED_BUILD_PROPERTIES}


def validate_dmi(dmi_root: Path = Path("/sys/class/dmi/id")) -> None:
    try:
        vendor = (dmi_root / "sys_vendor").read_text(encoding="utf-8").strip()
        product = (dmi_root / "product_name").read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"cannot read DMI identity: {error}") from error

    if vendor != "LENOVO" or product != "Lenovo YB1-X91L":
        raise RuntimeError(
            f"unsupported machine: vendor={vendor!r}, product={product!r}"
        )


def _validated_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    allowed = set(RUNTIME_FILES) | set(OPTIONAL_RUNTIME_FILES)
    regular: dict[str, tarfile.TarInfo] = {}

    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"unsafe archive path: {member.name!r}")
        normalized = str(path)
        if normalized in (".", ""):
            continue
        if member.isdir():
            continue
        if not member.isfile():
            raise RuntimeError(f"unsupported archive member type: {member.name!r}")
        if normalized not in allowed:
            raise RuntimeError(f"unexpected runtime file: {normalized!r}")
        if normalized in regular:
            raise RuntimeError(f"duplicate runtime file: {normalized!r}")
        regular[normalized] = member

    missing = sorted(set(RUNTIME_FILES) - regular.keys())
    if missing:
        raise RuntimeError("runtime is missing: " + ", ".join(missing))
    return regular


def _extract_members(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    destination: Path,
) -> None:
    for name in sorted(members):
        member = members[name]
        source = archive.extractfile(member)
        if source is None:
            raise RuntimeError(f"cannot read archive member: {name}")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
        target.chmod(member.mode & 0o755)


def _replace_xml_attribute(text: str, name: str, value: str) -> str:
    pattern = rf'(\b{re.escape(name)}=")[^"]*(")'
    updated, count = re.subn(pattern, rf"\g<1>{value}\g<2>", text)
    if count != 1:
        raise RuntimeError(f"expected exactly one {name} attribute, found {count}")
    return updated


def configure_runtime(root: Path) -> None:
    # tempfile.mkdtemp() intentionally starts at 0700. Linux gpsd needs to
    # traverse the imported root to open the world-readable NMEA FIFO.
    root.chmod(0o755)
    config_path = root / "system/vendor/etc/gps.xml"
    config = config_path.read_text(encoding="utf-8")
    settings = {
        "PortName": "/dev/gps/ttyGPS",
        "BaudRate": "921600",
        "LogEnabled": "false",
        "GpioNStdbyPath": "/dev/rfkill",
        "GpioDelayMs": "130",
        "SuplEnable": "false",
        "HttpSyncLto": "false",
        "FrqPlan": "FRQ_PLAN_26MHZ_2PPM",
        "RfType": "GL_RF_4752_BRCM_EXT_LNA",
    }
    for name, value in settings.items():
        config = _replace_xml_attribute(config, name, value)
    config_path.write_text(config, encoding="utf-8")

    system_config = root / "system/etc/gps.conf"
    system_config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "system/vendor/etc/gps.conf", system_config)

    for relative in (
        "data/gps/log",
        "dev/gps",
        "dev/socket",
        "proc",
        "sdcard/log/gps/broadcom",
        "sys",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    for relative in ("dev/gps/ttyGPS", "dev/null", "dev/random", "dev/rfkill", "dev/urandom"):
        (root / relative).touch(mode=0o600, exist_ok=True)


def manifest_for(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root))] = sha256_file(path)
    return result


def import_runtime(
    archive_path: Path,
    target: Path,
    expected_gpsd_sha256: str = EXPECTED_GPSD_SHA256,
) -> dict[str, object]:
    archive_path = archive_path.resolve(strict=True)
    target_parent = target.parent
    target_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".root.import-", dir=target_parent))
    installed = False

    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            members = _validated_members(archive)
            _extract_members(archive, members, staging)

        source_build = validate_source_identity(staging)
        gpsd = staging / "system/vendor/bin/gpsd"
        actual_gpsd_sha256 = sha256_file(gpsd)
        if actual_gpsd_sha256 != expected_gpsd_sha256:
            raise RuntimeError(
                "unsupported gpsd: expected "
                f"{expected_gpsd_sha256}, got {actual_gpsd_sha256}"
            )
        if not os.access(gpsd, os.X_OK):
            raise RuntimeError("stock gpsd is not executable")

        configure_runtime(staging)
        provenance: dict[str, object] = {
            "archive": str(archive_path),
            "archive_sha256": sha256_file(archive_path),
            "gpsd_sha256": actual_gpsd_sha256,
            "source_build": source_build,
            "files": manifest_for(staging),
        }

        previous = target_parent / f"{target.name}.previous"
        if previous.exists():
            shutil.rmtree(previous)
        moved_previous = False
        if target.exists():
            target.rename(previous)
            moved_previous = True
        try:
            staging.rename(target)
        except OSError:
            if moved_previous and not target.exists():
                previous.rename(target)
            raise
        installed = True

        provenance_path = target_parent / "runtime-provenance.json"
        temporary = provenance_path.with_suffix(".json.new")
        temporary.write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(provenance_path)
        return provenance
    finally:
        if not installed:
            shutil.rmtree(staging, ignore_errors=True)


def source_paths(source_root: Path) -> Iterable[tuple[str, Path]]:
    for runtime_name in RUNTIME_FILES + OPTIONAL_RUNTIME_FILES:
        source = source_root / runtime_name.removeprefix("system/")
        if source.exists():
            yield runtime_name, source
        elif runtime_name in RUNTIME_FILES:
            raise RuntimeError(f"stock system tree is missing: {source}")
