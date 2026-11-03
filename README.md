# Arch Control Center

Unified system control center designed for Arch Linux desktop environments.

Arch Control Center combines the clean navigation of GNOME Control Center, the granular hardware and subsystem depth of KDE System Settings, and the speed of XFCE Settings Manager into a single native application.

## Overview

Arch Control Center directly reads and manages core Arch Linux subsystems:

- Connectivity: NetworkManager (Wi-Fi, 2.4/5 GHz band pinning, Hotspot sharing, MTU, IPv4/IPv6, Cloudflare WARP, WireGuard, and Tailscale mesh).
- Bluetooth: BlueZ device discovery, pairing, trust toggles, and device battery telemetry.
- Audio: PipeWire and WirePlumber sink/source routing, overdrive boost up to 150%, per-app audio stream sliders, MPRIS media playback controls, and EasyEffects integration.
- Displays: Multi-monitor configuration, resolution, refresh rate, fractional scaling, UI text scaling stops, and blue-light night filtering.
- Compositor: Window gaps, border radius, active and inactive opacity, Dual-Kawase blur, and shader effects.
- Input: Touchpad natural scrolling, sensitivity curves, keyboard repeat rate and delay, and searchable desktop keybindings.
- Security and Hardware: LUKS2 disk volume status, Howdy IR facial recognition test, biometric fingerprint sensor, UFW firewall, and SSH server.
- Power: CPU power profile governor, battery charge limit ceiling, auto power-saver thresholds, and idle timers.
- Maintenance: Hardware memory purge (drop_caches), hugepage zone compaction, swap and ZRAM decompression, systemd journal vacuuming, package cache pruning, and NVMe disk speed testing.
- Themes and Appearance: Desktop wallpaper cycling, desktop and lock screen widget status, system font selection, and default applications.

## Requirements

- Arch Linux or Arch-based distributions
- Python 3.10+
- GTK 3 and WebKit2GTK 4.1 (`webkit2gtk-4.1` on Arch Linux)
- Core tools: `networkmanager`, `bluez`, `pipewire`, `wireplumber`

## Installation

### From Source

Clone the repository and run the installer:

```bash
git clone https://github.com/harisawan-bit/arch-control-center.git
cd arch-control-center
sudo make install
```

This installs:
- Executable: `/usr/local/bin/arch-control-center`
- Application data: `/usr/local/share/arch-control-center/`
- Desktop shortcut: `/usr/local/share/applications/arch-control-center.desktop`
- Icon: `/usr/local/share/icons/hicolor/scalable/apps/arch-control-center.svg`

### Running

Launch from your application launcher (Rofi, Walker, GNOME, KDE, or Hyprland) or execute directly from your terminal:

```bash
arch-control-center
```

## Uninstallation

```bash
sudo make uninstall
```

## Architecture

Arch Control Center runs an internal local communication service communicating over JSON RPC to execute system calls through standard Linux command-line utilities and system APIs. Changes take effect immediately without requiring full desktop restarts.

## License

MIT License. See [LICENSE](LICENSE) for details.
