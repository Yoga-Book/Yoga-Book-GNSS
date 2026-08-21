# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yogabook_gnss_runtime as runtime


XML = """<?xml version="1.0"?>
<glgps>
  <hal PortName="wrong" BaudRate="1" LogEnabled="true"
       GpioNStdbyPath="wrong" GpioDelayMs="1" SuplEnable="true"
       HttpSyncLto="true" />
  <gll FrqPlan="FROM_PROPERTY" RfType="FROM_PROPERTY" />
</glgps>
"""

BUILD_PROP = "\n".join(
    f"{name}={value}" for name, value in runtime.EXPECTED_BUILD_PROPERTIES.items()
) + "\n"


class RuntimeImportTests(unittest.TestCase):
    def make_archive(
        self,
        directory: Path,
        extra: str | None = None,
        build_prop: str = BUILD_PROP,
    ) -> tuple[Path, str]:
        archive_path = directory / "runtime.tar"
        gpsd_content = b"test vendor daemon\n"
        with tarfile.open(archive_path, "w") as archive:
            for name in runtime.RUNTIME_FILES:
                if name == "system/vendor/bin/gpsd":
                    content = gpsd_content
                    mode = 0o755
                elif name == "system/vendor/etc/gps.xml":
                    content = XML.encode()
                    mode = 0o644
                elif name == "system/build.prop":
                    content = build_prop.encode()
                    mode = 0o644
                else:
                    content = f"fixture:{name}\n".encode()
                    mode = 0o644
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = mode
                archive.addfile(info, io.BytesIO(content))
            if extra is not None:
                content = b"unexpected\n"
                info = tarfile.TarInfo(extra)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
        return archive_path, hashlib.sha256(gpsd_content).hexdigest()

    def test_import_validates_and_configures_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive, expected = self.make_archive(base)
            target = base / "state/root"

            provenance = runtime.import_runtime(archive, target, expected)

            config = (target / "system/vendor/etc/gps.xml").read_text()
            self.assertIn('PortName="/dev/gps/ttyGPS"', config)
            self.assertIn('BaudRate="921600"', config)
            self.assertIn('LogEnabled="false"', config)
            self.assertIn('GpioNStdbyPath="/dev/rfkill"', config)
            self.assertIn('GpioDelayMs="130"', config)
            self.assertIn('SuplEnable="false"', config)
            self.assertIn('HttpSyncLto="false"', config)
            self.assertIn('FrqPlan="FRQ_PLAN_26MHZ_2PPM"', config)
            self.assertIn('RfType="GL_RF_4752_BRCM_EXT_LNA"', config)
            self.assertEqual(
                (target / "system/etc/gps.conf").read_bytes(),
                (target / "system/vendor/etc/gps.conf").read_bytes(),
            )
            self.assertTrue((target / "dev/gps/ttyGPS").is_file())
            self.assertEqual(target.stat().st_mode & 0o777, 0o755)
            self.assertEqual(provenance["gpsd_sha256"], expected)
            self.assertEqual(
                provenance["source_build"], runtime.EXPECTED_BUILD_PROPERTIES
            )
            self.assertTrue((target.parent / "runtime-provenance.json").is_file())

    def test_rejects_unexpected_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive, expected = self.make_archive(base, "system/vendor/bin/other")
            with self.assertRaisesRegex(runtime.RuntimeError, "unexpected runtime file"):
                runtime.import_runtime(archive, base / "root", expected)

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive, expected = self.make_archive(base, "../escape")
            with self.assertRaisesRegex(runtime.RuntimeError, "unsafe archive path"):
                runtime.import_runtime(archive, base / "root", expected)

    def test_rejects_wrong_daemon_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive, _ = self.make_archive(base)
            with self.assertRaisesRegex(runtime.RuntimeError, "unsupported gpsd"):
                runtime.import_runtime(archive, base / "root", "0" * 64)

    def test_rejects_wrong_source_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive, expected = self.make_archive(
                base,
                build_prop="ro.build.display.id=unsupported\n",
            )
            with self.assertRaisesRegex(
                runtime.RuntimeError, "unsupported source build property"
            ):
                runtime.import_runtime(archive, base / "root", expected)

    def test_dmi_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dmi = Path(temporary)
            (dmi / "sys_vendor").write_text("LENOVO\n")
            (dmi / "product_name").write_text("Lenovo YB1-X91L\n")
            runtime.validate_dmi(dmi)
            (dmi / "product_name").write_text("Different\n")
            with self.assertRaisesRegex(runtime.RuntimeError, "unsupported machine"):
                runtime.validate_dmi(dmi)


if __name__ == "__main__":
    unittest.main()
