# Yoga Book GNSS

Linux integration for the Broadcom BCM4752 GNSS receiver in the Lenovo Yoga
Book YB1-X91L.

The Debian package supplies the open integration layer: safe firmware import,
the required rfkill off-to-on sequence, an isolated Android/Bionic runtime,
UART mapping, a systemd service, a `gpsd` bridge and a health check. It contains
no Lenovo, Broadcom or Android binaries.

The package also installs a narrow AppArmor extension granting Linux `gpsd`
access only to the generated NMEA FIFO.

## Why a private runtime is required

The receiver does not emit standard NMEA immediately after opening its UART.
The stock `/system/vendor/bin/gpsd` performs the BCM4752 autobaud, version and
patch protocol. That binary is proprietary and dynamically linked against the
Android 7.1.1 Bionic runtime, so it cannot be shipped by this project or run as
a normal glibc executable.

The tested runtime is from Lenovo Android 7.1.1 build
`YB1-X90F_USR_S100043_1709020000_WW08_BP_ROW`. Its BCM4752 transport has been
physically validated on the YB1-X91L and has this daemon checksum:

```text
d135fc515dd3802dcd9fe807b942e1e112767f56b5a44463c64121317753c715
```

The importer verifies that exact source-build identity and daemon checksum, and
refuses unsafe or unexpected archive members.

## Build and install

```bash
make test
make deb
sudo apt install ../yogabook-gnss_1.0.4_all.deb
```

Mount your own extracted stock `system.img`, then build a private runtime. If
the mounted image is at `/mnt/yogabook-system`:

```bash
yogabook-gnss-build-runtime \
  /mnt/yogabook-system \
  "$HOME/yogabook-gnss-runtime.tar"

sudo yogabook-gnss-import "$HOME/yogabook-gnss-runtime.tar"
sudo yogabook-gnss-health
```

The source system-image root is expected to contain `vendor/bin/gpsd`,
`vendor/etc/gps.xml`, `bin/linker64` and `lib64/`.

## Runtime architecture

```text
BCM4752 -> /dev/ttyS5 -> isolated stock daemon -> NMEA FIFO -> Linux gpsd
                                                            -> GeoClue/apps
```

The service is DMI-scoped to `LENOVO` / `Lenovo YB1-X91L`, excludes the
dedicated UART from ModemManager, powers GPS off before every start, waits 500
ms, and lets the daemon issue the actual rfkill unblock. The receiver runs at
921600 baud with a 26 MHz, 2 ppm frequency plan and the external-LNA BCM4752 RF
profile. It is powered off when the service stops.

The stock transport consumes about 2-3% of one CPU continuously while GNSS is
enabled. The service therefore has conservative CPU, memory, task and restart
limits, and a low CPU scheduling weight so desktop audio and input remain
responsive under contention. It remains enabled continuously because stopping
the proprietary initialization transport when Linux `gpsd` has no clients
cannot yet be made transparently socket-activated without risking location
availability.

SUPL and HTTP LTO are disabled because the standalone Linux integration has no
Android RIL/network callbacks. Satellite-only positioning remains available.

## Verification

```bash
systemctl status yogabook-gnss.service gpsd.socket
gpspipe -w
cgps
sudo yogabook-gnss-health
```

The default health check proves that TPV plus raw GGA/RMC/GSV transport is
flowing.  Indoors, gpsd can intentionally suppress SKY output when visible
satellites do not yet have complete azimuth/elevation data.  Strict physical
acceptance must be tested outdoors with a clear sky view and can take several
minutes on a cold start:

```bash
sudo yogabook-gnss-health --require-sky
sudo yogabook-gnss-health --require-fix
```

## Removal

Removing the package stops the receiver and removes the integration code. The
user-supplied runtime is deliberately preserved. Remove it explicitly only if
you no longer need it:

```bash
sudo rm -rf /var/lib/yogabook-gnss
```

## References

- Lenovo Android 7.1.1 build `YB1-X90F_USR_S100043_1709020000_WW08_BP_ROW`
- Lenovo Yoga Book YB1-X91L hardware used for transport validation
- [gpsd](https://gpsd.io/)
- Linux rfkill and DesignWare APB UART interfaces

## License

The project code is GPL-2.0-or-later. Imported firmware remains under its own
vendor terms and is never copied into the Debian package.
