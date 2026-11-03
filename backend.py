#!/usr/bin/env python3
"""
Omarchy Unified Control Center — Complete Backend Server & Live System API
Merges:
  1. All Omarchy Top-Bar & Service Plugins:
     - haris.network (Wi-Fi, Band Pinning 2.4/5/6/auto, Speedtest, QR, Hotspot omhotspot, WARP MASQUE/TCP/WG, WireGuard .conf)
     - omarchy.tailscale (Tailnet status, Peers, Exit Nodes, Mullvad Regions, Taildrop, MagicDNS)
     - io.github.hugorolimf.bluetooth (BlueZ adapter, discoverable, scan, pair/connect/trust/disconnect, battery)
     - io.github.kingokeke.audio-boost (PipeWire sinks/sources, 0-150% boost, per-app streams, MPRIS media, speaker DSP tuning, EasyEffects)
     - omarchy.monitor (Monitors, brightness, text-size stops [9..20], scale presets [1..4], internal/mirror toggles, Hyprsunset nightlight)
     - paulbob.super-battery (UPower telemetry, chargeLimit 80%, saverLevel 30%, warningLevel 20%, criticalLevel 10%, alert sounds, powerprofilesctl, idle timers)
     - io.github.ofa14-prog.dynamic-island (All 25+ dynamic-island.json keys: hoverExpand, glass, ambient, ambientAudio, priority, clockFormat, etc.)
     - jovibe.notify-center (~/.config/omarchy-notify-center/config.toml: position, timeout, critical_timeout, sticky_critical, max_visible, dnd, muted apps, history)
     - pomodoro-omarchy (state.json & work/break/autoStart/soundAlert)
     - omarchy.agents (~/.local/state/omarchy/agents/usage/*.json quotas & provider configs)
     - haris.glass-drive (Native C binary status/login/sync/mount/pin/cache) + iCloud Drive / Rclone
  2. Full GNOME Control Center + KDE System Settings + XFCE Settings Manager Depth:
     - Network IPv4/IPv6/MTU/MAC/DNS/Firewall/Routes
     - Hyprland Compositor (looknfeel.lua, input.lua, bindings.lua, hyprglass liquid glass shader, window rules)
     - System Optimization & Hardware Purge (RAM PageCache/Dentries/Inodes, Memory Compaction, Swap/ZRAM flush, Journal vacuum, Pacman prune, Disk Speedtest)
     - Cyber Security, LUKS2 Encryption, UFW Firewall, SSHD, FIDO2, Fingerprint, Sudoers
     - System Updates, Snapper Btrfs Snapshots, Themes, Fonts, Subsystems
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import time
import urllib.parse

HOME = Path.home()
STATIC_DIR = Path(__file__).resolve().parent / "ui"
GLASS_BIN = HOME / "Documents/Codex/2026-11-01/make/outputs/glass-drive/build/glass-drive"
NETWORK_CTRL = HOME / ".config/omarchy/plugins/haris.network/network-control.py"
SHELL_JSON = HOME / ".config/omarchy/shell.json"
ISLAND_JSON = HOME / ".config/omarchy/dynamic-island.json"
NOTIFY_TOML = HOME / ".config/omarchy-notify-center/config.toml"
NOTIFY_HIST = HOME / ".local/state/omarchy-notify-center/history.json"
AGENTS_DIR = HOME / ".local/state/omarchy/agents/usage"
POMODORO_STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "omarchy-pomodoro/state.json"


def run(cmd, shell=False, timeout=8, input_text=None):
    try:
        res = sp.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )
        return res.returncode == 0, (res.stdout or "").strip(), (res.stderr or "").strip()
    except Exception as e:
        return False, "", str(e)


def read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


# -------------------------------------------------------------------------
# 1. NETWORK, WI-FI, HOTSPOT, WARP, TAILSCALE
# -------------------------------------------------------------------------
def get_network_state():
    ok, saved_out, _ = run([
        "nmcli", "-t", "-f",
        "NAME,UUID,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY,DEVICE",
        "connection", "show"
    ])
    saved = {}
    ethernet = []
    vpns = []
    for line in saved_out.splitlines():
        parts = line.split(":")
        if len(parts) >= 6:
            name, uuid, ctype, auto, prio, dev = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
            if "wireless" in ctype or "wifi" in ctype:
                # Inspect band & ipv4 method for active/saved wifi if needed
                saved[name] = {
                    "uuid": uuid,
                    "autoconnect": auto == "yes",
                    "priority": int(prio) if prio.lstrip("-").isdigit() else 0,
                    "device": dev,
                }
            elif "ethernet" in ctype:
                ethernet.append({
                    "name": name,
                    "uuid": uuid,
                    "autoconnect": auto == "yes",
                    "priority": int(prio) if prio.lstrip("-").isdigit() else 0,
                    "device": dev,
                    "connected": bool(dev and dev != "--"),
                })
            elif ctype in ("vpn", "wireguard"):
                vpns.append({"name": name, "uuid": uuid, "type": ctype, "active": bool(dev and dev != "--")})

    ok, wifi_out, _ = run([
        "nmcli", "-t", "-f",
        "IN-USE,SSID,BSSID,SECURITY,SIGNAL,FREQ,CHAN,RATE",
        "dev", "wifi", "list", "--rescan", "no"
    ])
    networks = []
    seen = set()
    for line in wifi_out.splitlines():
        parts = line.replace("\\:", "_COLON_").split(":")
        if len(parts) >= 8:
            in_use = parts[0] == "*"
            ssid = parts[1].replace("_COLON_", ":")
            bssid = parts[2].replace("_COLON_", ":")
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            sec = parts[3]
            sig = int(parts[4]) if parts[4].isdigit() else 0
            freq = parts[5]
            chan = parts[6]
            rate = parts[7]
            s_info = saved.get(ssid, {})
            band_val = "auto"
            ip_method = "auto"
            ip_addr = ""
            gateway = ""
            dns_servers = ""
            mtu = "auto"
            cloned_mac = ""
            if in_use or ssid in saved:
                _, det_out, _ = run([
                    "nmcli", "-t", "-f",
                    "802-11-wireless.band,ipv4.method,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,802-11-wireless.mtu,802-11-wireless.cloned-mac-address",
                    "connection", "show", ssid
                ])
                for dline in det_out.splitlines():
                    if dline.startswith("802-11-wireless.band:"):
                        b = dline.split(":", 1)[1].strip()
                        band_val = "5" if b == "a" else ("2.4" if b == "bg" else "auto")
                    elif dline.startswith("ipv4.method:"):
                        ip_method = dline.split(":", 1)[1].strip() or "auto"
                    elif dline.startswith("IP4.ADDRESS"):
                        ip_addr = dline.split(":", 1)[1].strip()
                    elif dline.startswith("IP4.GATEWAY:"):
                        gateway = dline.split(":", 1)[1].strip()
                    elif dline.startswith("IP4.DNS"):
                        dns_servers = dline.split(":", 1)[1].strip()
                    elif dline.startswith("802-11-wireless.mtu:"):
                        mtu = dline.split(":", 1)[1].strip() or "auto"
                    elif dline.startswith("802-11-wireless.cloned-mac-address:"):
                        cloned_mac = dline.split(":", 1)[1].strip()

            networks.append({
                "ssid": ssid,
                "bssid": bssid,
                "connected": in_use,
                "security": sec or "Open",
                "signal": sig,
                "freq": freq,
                "channel": chan,
                "rate": rate,
                "known": ssid in saved,
                "autoconnect": s_info.get("autoconnect", True),
                "priority": s_info.get("priority", 0),
                "uuid": s_info.get("uuid", ""),
                "band": band_val,
                "ipMethod": ip_method,
                "ipAddress": ip_addr,
                "gateway": gateway,
                "dnsServers": dns_servers,
                "mtu": mtu,
                "clonedMac": cloned_mac,
            })
    networks.sort(key=lambda x: (not x["connected"], not x["known"], -x["signal"]))

    hotspot = {}
    if NETWORK_CTRL.exists():
        ok, hs_out, _ = run(["python3", str(NETWORK_CTRL), "status"])
        if ok and hs_out:
            try:
                hotspot = json.loads(hs_out)
            except Exception:
                pass

    # Tailscale state
    tailscale = {"installed": shutil.which("tailscale") is not None, "active": False, "self": {}, "peers": [], "exitNode": ""}
    if tailscale["installed"]:
        ok, ts_json, _ = run(["tailscale", "status", "--json"], timeout=4)
        if ok and ts_json:
            try:
                ts_data = json.loads(ts_json)
                backend_state = ts_data.get("BackendState", "")
                tailscale["active"] = backend_state == "Running"
                tailscale["backendState"] = backend_state
                tailscale["magicDns"] = ts_data.get("MagicDNSSuffix", "")
                self_node = ts_data.get("Self", {})
                tailscale["self"] = {
                    "hostName": self_node.get("HostName", ""),
                    "dnsName": self_node.get("DNSName", ""),
                    "ips": self_node.get("TailscaleIPs", []),
                    "os": self_node.get("OS", ""),
                }
                for _, p in (ts_data.get("Peer") or {}).items():
                    is_exit = bool(p.get("ExitNode"))
                    if is_exit:
                        tailscale["exitNode"] = p.get("HostName", "")
                    tailscale["peers"].append({
                        "id": p.get("ID", ""),
                        "hostName": p.get("HostName", ""),
                        "dnsName": p.get("DNSName", ""),
                        "ips": p.get("TailscaleIPs", []),
                        "os": p.get("OS", ""),
                        "online": bool(p.get("Online")),
                        "exitNode": is_exit,
                        "exitNodeOption": bool(p.get("ExitNodeOption")),
                    })
            except Exception:
                pass

    _, dns_provider, _ = run(["omarchy-dns"])
    _, net_status, _ = run(["omarchy-network-status", "--verbose"])
    _, hostname, _ = run(["hostnamectl", "--static"])

    return {
        "hostname": hostname or "omarchy",
        "networks": networks,
        "ethernet": ethernet,
        "vpns": vpns,
        "hotspot": hotspot,
        "tailscale": tailscale,
        "dns": dns_provider or "DHCP",
        "details": net_status,
    }


# -------------------------------------------------------------------------
# 2. BLUETOOTH
# -------------------------------------------------------------------------
def get_bluetooth_state():
    _, power_out, _ = run(["omarchy-bluetooth-power", "is-on"])
    enabled = power_out.strip().lower() in ("true", "on", "1", "yes")
    _, bt_show, _ = run(["bluetoothctl", "show"])
    discoverable = "Discoverable: yes" in bt_show
    pairable = "Pairable: yes" in bt_show
    alias_m = re.search(r"Alias:\s+(.+)", bt_show)

    _, devs_out, _ = run(["bluetoothctl", "devices"])
    devices = []
    for line in devs_out.splitlines():
        m = re.match(r"Device\s+([0-9A-F:]{17})\s+(.*)", line)
        if m:
            addr, name = m.group(1), m.group(2)
            _, info, _ = run(["bluetoothctl", "info", addr])
            connected = "Connected: yes" in info
            paired = "Paired: yes" in info
            trusted = "Trusted: yes" in info
            blocked = "Blocked: yes" in info
            batt_m = re.search(r"Battery Percentage:.*\((\d+)\)", info)
            icon_m = re.search(r"Icon:\s+(\S+)", info)
            devices.append({
                "address": addr,
                "name": name,
                "connected": connected,
                "paired": paired,
                "trusted": trusted,
                "blocked": blocked,
                "battery": int(batt_m.group(1)) if batt_m else None,
                "icon": icon_m.group(1) if icon_m else "audio-card",
            })
    devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"]))
    return {
        "enabled": enabled,
        "discoverable": discoverable,
        "pairable": pairable,
        "adapterAlias": alias_m.group(1).strip() if alias_m else "Omarchy Bluetooth",
        "devices": devices,
    }


# -------------------------------------------------------------------------
# 3. AUDIO, PIPEWIRE, PER-APP STREAMS, MPRIS, EASYEFFECTS
# -------------------------------------------------------------------------
def get_audio_state():
    _, vol_out, _ = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    vol = 50
    muted = False
    if vol_out:
        m = re.search(r"Volume:\s+([\d.]+)", vol_out)
        if m:
            vol = int(round(float(m.group(1)) * 100))
        muted = "[MUTED]" in vol_out

    _, mic_out, _ = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"])
    mic_vol = 50
    mic_muted = False
    if mic_out:
        m = re.search(r"Volume:\s+([\d.]+)", mic_out)
        if m:
            mic_vol = int(round(float(m.group(1)) * 100))
        mic_muted = "[MUTED]" in mic_out

    _, def_sink, _ = run(["pactl", "get-default-sink"])
    _, def_source, _ = run(["pactl", "get-default-source"])

    sinks = []
    _, sinks_json, _ = run(["pactl", "-f", "json", "list", "sinks"])
    try:
        for s in json.loads(sinks_json):
            vols = s.get("volume", {})
            first_ch = next(iter(vols.values()), {})
            v_pct = int(first_ch.get("value_percent", "50%").rstrip("%"))
            sinks.append({
                "id": s.get("index"),
                "name": s.get("name"),
                "description": s.get("description"),
                "mute": bool(s.get("mute")),
                "volume": v_pct,
                "default": s.get("name") == def_sink,
                "activePort": (s.get("active_port") or ""),
            })
    except Exception:
        pass

    sources = []
    _, sources_json, _ = run(["pactl", "-f", "json", "list", "sources"])
    try:
        for s in json.loads(sources_json):
            if ".monitor" not in s.get("name", ""):
                vols = s.get("volume", {})
                first_ch = next(iter(vols.values()), {})
                v_pct = int(first_ch.get("value_percent", "50%").rstrip("%"))
                sources.append({
                    "id": s.get("index"),
                    "name": s.get("name"),
                    "description": s.get("description"),
                    "mute": bool(s.get("mute")),
                    "volume": v_pct,
                    "default": s.get("name") == def_source,
                })
    except Exception:
        pass

    # Per-application playback streams (sink-inputs)
    streams = []
    _, streams_json, _ = run(["pactl", "-f", "json", "list", "sink-inputs"])
    try:
        for st in json.loads(streams_json):
            props = st.get("properties", {})
            app_name = props.get("application.name") or props.get("media.name") or f"Stream #{st.get('index')}"
            if "omarchy_speaker_tuning" in app_name.lower():
                continue
            vols = st.get("volume", {})
            first_ch = next(iter(vols.values()), {})
            v_pct = int(first_ch.get("value_percent", "100%").rstrip("%"))
            streams.append({
                "id": st.get("index"),
                "app": app_name,
                "media": props.get("media.name", ""),
                "sink": st.get("sink"),
                "volume": v_pct,
                "mute": bool(st.get("mute")),
            })
    except Exception:
        pass

    # MPRIS active media players
    mpris = []
    if shutil.which("playerctl"):
        _, players_out, _ = run(["playerctl", "-l"])
        for pl in players_out.splitlines():
            pl = pl.strip()
            if not pl:
                continue
            _, st_out, _ = run(["playerctl", "-p", pl, "status"])
            _, title_out, _ = run(["playerctl", "-p", pl, "metadata", "xesam:title"])
            _, artist_out, _ = run(["playerctl", "-p", pl, "metadata", "xesam:artist"])
            mpris.append({
                "player": pl,
                "status": st_out,
                "title": title_out or pl,
                "artist": artist_out or "",
            })

    _, tuning_status, _ = run(["omarchy-audio-tuning", "status"])
    ee_running = run(["pgrep", "-x", "easyeffects"])[0]
    _, ee_presets, _ = run(["easyeffects", "-p"])

    return {
        "volume": vol,
        "muted": muted,
        "micVolume": mic_vol,
        "micMuted": mic_muted,
        "defaultSink": def_sink,
        "defaultSource": def_source,
        "sinks": sinks,
        "sources": sources,
        "streams": streams,
        "mpris": mpris,
        "speakerTuning": tuning_status or "off",
        "easyeffectsRunning": ee_running,
        "easyeffectsPresets": ee_presets,
    }


# -------------------------------------------------------------------------
# 4. DISPLAYS, HYPRLAND COMPOSITOR, HYPRGLASS, INPUT, KEYBINDINGS
# -------------------------------------------------------------------------
def get_displays_hyprland():
    _, mon_json, _ = run(["hyprctl", "monitors", "all", "-j"])
    monitors = []
    try:
        monitors = json.loads(mon_json)
    except Exception:
        pass

    _, bri_out, _ = run(["omarchy-brightness-display"])
    bri = 70
    m = re.search(r"(\d+)", bri_out)
    if m:
        bri = int(m.group(1))

    _, text_size_out, _ = run(["omarchy-display-text-size"])
    text_size = int(text_size_out) if text_size_out.strip().isdigit() else 12

    look_path = HOME / ".config/hypr/looknfeel.lua"
    look_text = look_path.read_text() if look_path.exists() else ""
    input_path = HOME / ".config/hypr/input.lua"
    input_text = input_path.read_text() if input_path.exists() else ""
    binds_path = HOME / ".config/hypr/bindings.lua"
    binds_text = binds_path.read_text() if binds_path.exists() else ""

    def extract_num(text, key, default):
        m = re.search(rf"\b{key}\s*=\s*([-0-9.]+)", text)
        return float(m.group(1)) if m else default

    def extract_bool(text, key, default):
        m = re.search(rf"\b{key}\s*=\s*(true|false)", text)
        return (m.group(1) == "true") if m else default

    def extract_str(text, key, default):
        m = re.search(rf'\b{key}\s*=\s*"([^"]*)"', text)
        return m.group(1) if m else default

    bindings = []
    for line in binds_text.splitlines():
        line_s = line.strip()
        if line_s.startswith("o.bind("):
            m = re.match(r'o\.bind\(\s*"([^"]+)"\s*,\s*("[^"]*"|nil)\s*,\s*(.+)\)', line_s)
            if m:
                bindings.append({
                    "keys": m.group(1),
                    "desc": m.group(2).strip('"') if m.group(2) != "nil" else "System Action",
                    "action": m.group(3),
                })

    _, night_status, _ = run(["omarchy-toggle-nightlight", "--status"])
    night_active = "on" in night_status.lower() or run(["pgrep", "-x", "hyprsunset"])[0]

    return {
        "monitors": monitors,
        "brightness": bri,
        "textSize": text_size,
        "textSizeStops": [9, 10, 11, 12, 14, 16, 20],
        "scalePresets": ["1", "1.25", "1.6", "2", "3", "4"],
        "nightlight": night_active,
        "look": {
            "gaps_in": int(extract_num(look_text, "gaps_in", 6)),
            "gaps_out": int(extract_num(look_text, "gaps_out", 10)),
            "border_size": int(extract_num(look_text, "border_size", 1)),
            "rounding": int(extract_num(look_text, "rounding", 14)),
            "active_opacity": extract_num(look_text, "active_opacity", 0.94),
            "inactive_opacity": extract_num(look_text, "inactive_opacity", 0.84),
            "blur_enabled": extract_bool(look_text, "enabled", True),
            "blur_size": int(extract_num(look_text, "size", 10)),
            "blur_passes": int(extract_num(look_text, "passes", 3)),
            "blur_noise": extract_num(look_text, "noise", 0.02),
            "blur_contrast": extract_num(look_text, "contrast", 1.05),
            "blur_vibrancy": extract_num(look_text, "vibrancy", 0.25),
            "glass_preset": extract_str(look_text, "preset", "clear"),
            "specular_strength": extract_num(look_text, "specular_strength", 0.7),
            "refraction_strength": extract_num(look_text, "refraction_strength", 0.5),
            "chromatic_aberration": extract_num(look_text, "chromatic_aberration", 0.35),
            "fresnel_strength": extract_num(look_text, "fresnel_strength", 0.55),
            "bevel_size": extract_num(look_text, "bevel_size", 0.08),
            "bevel_strength": extract_num(look_text, "bevel_strength", 0.7),
            "lens_distortion": extract_num(look_text, "lens_distortion", 0.3),
        },
        "input": {
            "kb_layout": extract_str(input_text, "kb_layout", "us"),
            "repeat_rate": int(extract_num(input_text, "repeat_rate", 40)),
            "repeat_delay": int(extract_num(input_text, "repeat_delay", 600)),
            "sensitivity": extract_num(input_text, "sensitivity", 0.4),
            "accel_profile": extract_str(input_text, "accel_profile", "adaptive"),
            "natural_scroll": extract_bool(input_text, "natural_scroll", True),
            "scroll_factor": extract_num(input_text, "scroll_factor", 1.0),
            "clickfinger_behavior": extract_bool(input_text, "clickfinger_behavior", True),
            "tap_to_click": extract_bool(input_text, "tap-to-click", True),
            "disable_while_typing": extract_bool(input_text, "disable_while_typing", False),
        },
        "bindings": bindings,
    }


# -------------------------------------------------------------------------
# 5. TOP BAR, DYNAMIC ISLAND, NOTIFICATIONS, POMODORO, AGENTS
# -------------------------------------------------------------------------
def parse_simple_toml(text: str):
    out = {}
    section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            full_key = f"{section}.{k}" if section else k
            if v.startswith('"') and v.endswith('"'):
                out[full_key] = v[1:-1]
            elif v in ("true", "false"):
                out[full_key] = v == "true"
            elif v.startswith("[") and v.endswith("]"):
                try:
                    out[full_key] = json.loads(v)
                except Exception:
                    out[full_key] = []
            elif v.lstrip("-").isdigit():
                out[full_key] = int(v)
            else:
                out[full_key] = v
    return out


def get_shell_and_topbar():
    shell_cfg = read_json(SHELL_JSON, {})
    island_defaults = {
        "hoverExpand": False,
        "hoverDelay": 380,
        "collapseDelay": 650,
        "reduceMotion": False,
        "idleClock": True,
        "clockFormat": "ddd d MMM  HH:mm",
        "language": "en",
        "priority": ["agent", "recording", "timer", "music"],
        "compactHeight": 32,
        "topOffset": 2,
        "expandedWidth": 540,
        "appearance": "dark",
        "color": "#000000",
        "lightColor": "#ffffff",
        "glass": True,
        "glassOpacity": 0.56,
        "glassOpacityLight": 0.26,
        "ambient": True,
        "ambientAudio": True,
        "peekOnTrackChange": True,
        "peekOnAgentDone": True,
        "autoExpandPermission": True,
        "hideOnFullscreen": True,
        "agent": "",
        "agentQuietSeconds": 180,
    }
    island_user = read_json(ISLAND_JSON, {})
    island_cfg = {**island_defaults, **island_user}

    # Notification Center config & history
    notify_raw = NOTIFY_TOML.read_text() if NOTIFY_TOML.exists() else ""
    notify_parsed = parse_simple_toml(notify_raw)
    notify_cfg = {
        "position": notify_parsed.get("general.position", "right"),
        "timeout": notify_parsed.get("general.timeout", 5),
        "critical_timeout": notify_parsed.get("general.critical_timeout", 5),
        "sticky_critical": notify_parsed.get("general.sticky_critical", False),
        "max_visible": notify_parsed.get("general.max_visible", 3),
        "max_stack": notify_parsed.get("general.max_stack", 50),
        "history_limit": notify_parsed.get("general.history_limit", 200),
        "animation": notify_parsed.get("general.animation", True),
        "width": notify_parsed.get("general.width", 380),
        "dnd": notify_parsed.get("general.dnd", False),
        "muted_apps": notify_parsed.get("mute.apps", []),
    }
    notify_hist = read_json(NOTIFY_HIST, [])
    if isinstance(notify_hist, dict):
        notify_hist = notify_hist.get("entries", [])

    # Pomodoro runtime state
    pomo = read_json(POMODORO_STATE, {
        "phase": "idle",
        "running": False,
        "paused": False,
        "workMinutes": 25,
        "breakMinutes": 5,
        "cycleCount": 0,
    })

    # AI Coding Agents usage records
    agents = []
    if AGENTS_DIR.exists():
        for f in sorted(AGENTS_DIR.glob("*.json")):
            rec = read_json(f, None)
            if isinstance(rec, dict):
                agents.append({
                    "id": f.stem,
                    "provider": rec.get("provider", f.stem),
                    "updatedAt": rec.get("updatedAt", ""),
                    "windows": rec.get("windows", []),
                    "models": rec.get("models", []),
                    "balance": rec.get("balance"),
                })

    _, current_theme, _ = run(["omarchy-theme-current"])
    _, themes_out, _ = run(["omarchy-theme-list"])
    _, current_font, _ = run(["omarchy-font-current"])
    _, fonts_out, _ = run(["omarchy-font-list"])
    _, plugins_json, _ = run(["omarchy-plugin-list", "--json"])
    plugins = []
    try:
        plugins = json.loads(plugins_json)
    except Exception:
        pass

    _, def_browser, _ = run(["omarchy-default-browser"])
    _, def_editor, _ = run(["omarchy-default-editor"])
    _, def_term, _ = run(["omarchy-default-terminal"])
    _, def_agent, _ = run(["omarchy-default-agent"])
    _, current_bg, _ = run(["omarchy-theme-bg-current"])

    # Glyph widgets / lockscreen config
    glyph_rice = read_json(HOME / ".config/glyph-widgets/rice.json", {})

    return {
        "shell": shell_cfg,
        "island": island_cfg,
        "wallpaper": {
            "current": current_bg,
        },
        "widgets": {
            "glyphRice": glyph_rice,
        },
        "notifications": {
            "config": notify_cfg,
            "historyCount": len(notify_hist) if isinstance(notify_hist, list) else 0,
            "recent": (notify_hist[:12] if isinstance(notify_hist, list) else []),
        },
        "pomodoro": pomo,
        "agents": agents,
        "currentTheme": current_theme,
        "themes": [t.strip() for t in themes_out.splitlines() if t.strip()],
        "currentFont": current_font,
        "fonts": [f.strip() for f in fonts_out.splitlines() if f.strip()],
        "plugins": plugins,
        "defaults": {
            "browser": def_browser,
            "editor": def_editor,
            "terminal": def_term,
            "agent": def_agent,
        },
    }


# -------------------------------------------------------------------------
# 6. CLOUD SYNC: GLASS DRIVE & ICLOUD DRIVE
# -------------------------------------------------------------------------
def get_cloud_state():
    glass = {"accounts": [], "pins": [], "job": {}}
    if GLASS_BIN.exists():
        ok, out, _ = run([str(GLASS_BIN), "status"])
        if ok and out:
            try:
                glass = json.loads(out)
            except Exception:
                pass

    _, remotes_out, _ = run(["rclone", "listremotes"])
    remotes = [r.strip(":") for r in remotes_out.splitlines() if r.strip()]
    icloud_dir = HOME / "iCloudDrive"
    icloud_mounted = icloud_dir.exists() and any(icloud_dir.iterdir()) if icloud_dir.exists() else False

    return {
        "glassDrive": glass,
        "rcloneRemotes": remotes,
        "icloud": {
            "path": str(icloud_dir),
            "mounted": icloud_mounted,
            "cliInstalled": shutil.which("icloud") is not None or (HOME / ".local/share/mise/installs/python/latest/bin/icloud").exists(),
        },
    }


# -------------------------------------------------------------------------
# 7. POWER, SUPER-BATTERY, OPTIMIZATION, SECURITY & UPDATES
# -------------------------------------------------------------------------
def get_system_and_security():
    _, free_out, _ = run(["free", "-b"])
    mem = {"total": 16, "used": 8, "free": 4, "cached": 4, "available": 8, "swapTotal": 30, "swapUsed": 1}
    for line in free_out.splitlines():
        if line.startswith("Mem:"):
            p = line.split()
            mem["total"] = int(p[1])
            mem["used"] = int(p[2])
            mem["free"] = int(p[3])
            mem["cached"] = int(p[5])
            mem["available"] = int(p[6])
        elif line.startswith("Swap:"):
            p = line.split()
            mem["swapTotal"] = int(p[1])
            mem["swapUsed"] = int(p[2])

    _, zram_out, _ = run(["zramctl", "--output-all", "--json"])
    zram = []
    try:
        zram = json.loads(zram_out).get("blockdevices", [])
    except Exception:
        pass

    # Battery sysfs + Super-Battery config from shell.json
    bat_dir = Path("/sys/class/power_supply/BAT0")
    bat_cap = int((bat_dir / "capacity").read_text().strip()) if (bat_dir / "capacity").exists() else 100
    bat_stat = (bat_dir / "status").read_text().strip() if (bat_dir / "status").exists() else "Full"
    bat_cycles = int((bat_dir / "cycle_count").read_text().strip()) if (bat_dir / "cycle_count").exists() else 0
    power_now_uw = int((bat_dir / "power_now").read_text().strip()) if (bat_dir / "power_now").exists() else 0
    energy_full = int((bat_dir / "energy_full").read_text().strip()) if (bat_dir / "energy_full").exists() else 100
    energy_design = int((bat_dir / "energy_full_design").read_text().strip()) if (bat_dir / "energy_full_design").exists() else 100
    bat_health = round((energy_full / energy_design) * 100, 1) if energy_design > 0 else 100.0
    _, pp_out, _ = run(["powerprofilesctl", "get"])

    # Extract paulbob.super-battery inline settings from shell.json
    shell_cfg = read_json(SHELL_JSON, {})
    super_battery = {
        "chargeLimit": 80,
        "chargeLimitOn": True,
        "saverLevel": 30,
        "saverOn": True,
        "warningLevel": 20,
        "warningOn": True,
        "warningSound": "builtin:gentle-chime.wav",
        "criticalLevel": 10,
        "criticalOn": True,
        "criticalSound": "builtin:urgent-beep.wav",
        "notify": True,
        "repeatMinutes": 5,
        "showPercentage": True,
        "volume": 80,
    }
    for item in shell_cfg.get("bar", {}).get("right", []):
        if isinstance(item, dict) and item.get("plugin") == "paulbob.super-battery":
            super_battery.update(item.get("settings", {}))
            break

    idle_cfg = shell_cfg.get("idle", {"lock": 300, "screensaver": 150})

    _, lsblk_json, _ = run(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL"])
    disks = []
    try:
        disks = json.loads(lsblk_json).get("blockdevices", [])
    except Exception:
        pass

    _, channel, _ = run(["omarchy-channel-current"])
    _, version, _ = run(["omarchy-version"])
    _, timezone, _ = run(["timedatectl", "show", "-p", "Timezone", "--value"])
    _, ntp, _ = run(["timedatectl", "show", "-p", "NTP", "--value"])
    _, local_time, _ = run(["date", "+%Y-%m-%d %H:%M:%S %Z"])
    sshd_enabled = run(["systemctl", "is-active", "sshd"])[0]
    fprint_installed = shutil.which("fprintd-enroll") is not None
    howdy_installed = shutil.which("howdy") is not None
    howdy_active = False
    if howdy_installed:
        _, h_out, _ = run(["howdy", "status"])
        howdy_active = "Face matched" in h_out or "active" in h_out.lower()
    ufw_installed = shutil.which("ufw") is not None
    ufw_active = run(["systemctl", "is-active", "ufw"])[0]

    pkg_cache = Path("/var/cache/pacman/pkg")
    cache_bytes = sum(f.stat().st_size for f in pkg_cache.glob("*") if f.is_file()) if pkg_cache.exists() else 0

    _, cpu_model, _ = run("lscpu | awk -F: '/Model name/ {gsub(/^[ \t]+/,\"\",$2); print $2; exit}'", shell=True)
    _, kernel_ver, _ = run(["uname", "-r"])
    _, load_avg, _ = run(["cat", "/proc/loadavg"])

    return {
        "cpu": {"model": cpu_model, "kernel": kernel_ver, "loadavg": load_avg.split()[:3] if load_avg else []},
        "memory": mem,
        "zram": zram,
        "battery": {
            "capacity": bat_cap,
            "status": bat_stat,
            "cycles": bat_cycles,
            "watts": round(power_now_uw / 1_000_000, 2),
            "health": bat_health,
            "profile": pp_out or "balanced",
            "superBattery": super_battery,
            "idle": idle_cfg,
        },
        "disks": disks,
        "omarchy": {
            "version": version,
            "channel": channel or "stable",
            "pacmanCacheBytes": cache_bytes,
        },
        "security": {
            "sshd": sshd_enabled,
            "fingerprint": fprint_installed,
            "howdy": {"installed": howdy_installed, "active": howdy_active},
            "luksActive": "crypt" in lsblk_json,
            "ufwInstalled": ufw_installed,
            "ufwActive": ufw_active,
        },
        "datetime": {
            "timezone": timezone or "Asia/Karachi",
            "ntp": ntp == "yes",
            "localTime": local_time,
        },
    }


def collect_all_state():
    return {
        "network": get_network_state(),
        "bluetooth": get_bluetooth_state(),
        "audio": get_audio_state(),
        "hyprland": get_displays_hyprland(),
        "shell": get_shell_and_topbar(),
        "cloud": get_cloud_state(),
        "system": get_system_and_security(),
    }


# -------------------------------------------------------------------------
# ACTION DISPATCHER
# -------------------------------------------------------------------------
def update_super_battery_in_shell(updates: dict):
    cfg = read_json(SHELL_JSON, {})
    right = cfg.get("bar", {}).get("right", [])
    found = False
    for item in right:
        if isinstance(item, dict) and item.get("plugin") == "paulbob.super-battery":
            st = item.get("settings", {})
            st.update(updates)
            item["settings"] = st
            found = True
            break
    if not found:
        right.append({"plugin": "paulbob.super-battery", "settings": updates})
    write_json(SHELL_JSON, cfg)


def write_notify_toml(cfg: dict):
    NOTIFY_TOML.parent.mkdir(parents=True, exist_ok=True)
    muted_json = json.dumps(cfg.get("muted_apps", []))
    text = (
        "# omarchy-notify-center configuration.\n"
        "# Changes reload live; no shell restart needed.\n\n"
        "[general]\n"
        f'position = "{cfg.get("position", "right")}"\n'
        f'timeout = {int(cfg.get("timeout", 5))}\n'
        f'critical_timeout = {int(cfg.get("critical_timeout", 5))}\n'
        f'sticky_critical = {"true" if cfg.get("sticky_critical") else "false"}\n'
        f'max_visible = {int(cfg.get("max_visible", 3))}\n'
        f'max_stack = {int(cfg.get("max_stack", 50))}\n'
        f'history_limit = {int(cfg.get("history_limit", 200))}\n'
        f'animation = {"true" if cfg.get("animation", True) else "false"}\n'
        f'width = {int(cfg.get("width", 380))}\n'
        f'dnd = {"true" if cfg.get("dnd") else "false"}\n\n'
        "[mute]\n"
        f"apps = {muted_json}\n"
    )
    NOTIFY_TOML.write_text(text)


def handle_action(payload):
    act = payload.get("action", "")

    # --- Wi-Fi & Network ---
    if act == "wifi.connect":
        ssid = payload.get("ssid", "")
        pw = payload.get("password", "")
        if pw:
            run(["nmcli", "connection", "modify", "id", ssid, "802-11-wireless-security.psk", pw])
            ok, out, err = run(["nmcli", "dev", "wifi", "connect", ssid, "password", pw], timeout=20)
        else:
            ok, out, err = run(["nmcli", "connection", "up", "id", ssid], timeout=15)
        return {"ok": ok, "message": out or err or f"Connected to {ssid}"}

    if act == "wifi.disconnect":
        ssid = payload.get("ssid", "")
        ok, out, err = run(["nmcli", "connection", "down", "id", ssid])
        return {"ok": ok, "message": out or err or f"Disconnected {ssid}"}

    if act == "wifi.forget":
        ssid = payload.get("ssid", "")
        ok, out, err = run(["nmcli", "connection", "delete", "id", ssid])
        return {"ok": ok, "message": out or err or f"Forgotten {ssid}"}

    if act == "wifi.autoconnect":
        ssid = payload.get("ssid", "")
        enable = "yes" if payload.get("enabled") else "no"
        ok, out, err = run(["nmcli", "connection", "modify", "id", ssid, "connection.autoconnect", enable])
        return {"ok": ok, "message": f"Auto-connect for {ssid} set to {enable}"}

    if act == "wifi.password":
        ssid = payload.get("ssid", "")
        pw = payload.get("password", "")
        ok, out, err = run(["nmcli", "connection", "modify", "id", ssid, "802-11-wireless-security.psk", pw])
        if ok:
            run(["nmcli", "connection", "up", "id", ssid], timeout=15)
        return {"ok": ok, "message": out or err or f"Updated password for {ssid}"}

    if act == "wifi.band":
        ssid = payload.get("ssid", "")
        band = payload.get("band", "auto")
        ok, out, err = run(["omarchy-wifi-band", ssid, band])
        return {"ok": ok, "message": out or err or f"Set {ssid} band to {band}"}

    if act == "wifi.advanced":
        ssid = payload.get("ssid", "")
        prio = str(payload.get("priority", 0))
        mtu = str(payload.get("mtu", "auto"))
        mac = str(payload.get("clonedMac", ""))
        ip_method = str(payload.get("ipMethod", "auto"))
        args = ["nmcli", "connection", "modify", "id", ssid, "connection.autoconnect-priority", prio]
        if mtu and mtu != "auto" and mtu.isdigit():
            args += ["802-11-wireless.mtu", mtu]
        if mac:
            args += ["802-11-wireless.cloned-mac-address", mac]
        if ip_method in ("auto", "manual", "disabled"):
            args += ["ipv4.method", ip_method]
            if ip_method == "manual" and payload.get("ipAddress"):
                args += ["ipv4.addresses", payload.get("ipAddress"), "ipv4.gateway", payload.get("gateway", "")]
        ok, out, err = run(args)
        return {"ok": ok, "message": out or err or f"Saved advanced profile settings for {ssid}"}

    if act == "wifi.scan":
        run(["nmcli", "dev", "wifi", "rescan"])
        return {"ok": True, "message": "Wi-Fi radio rescan completed"}

    if act == "wifi.speedtest":
        ok, out, err = run(["omarchy-network-speedtest"], timeout=35)
        return {"ok": ok, "message": out or err or "Speedtest completed", "data": out}

    if act == "hotspot.toggle":
        if payload.get("enabled"):
            data = json.dumps({
                "ssid": payload.get("ssid", "Omarchy"),
                "password": payload.get("password", ""),
                "band": payload.get("band", "2.4"),
            })
            ok, out, err = run(["python3", str(NETWORK_CTRL), "start"], input_text=data, timeout=20)
        else:
            ok, out, err = run(["python3", str(NETWORK_CTRL), "stop"], input_text="{}", timeout=15)
        return {"ok": ok, "message": out or err or "Hotspot updated"}

    if act == "vpn.toggle":
        uuid = payload.get("uuid", "")
        op = "vpn-on" if payload.get("enabled") else "vpn-off"
        ok, out, err = run(["python3", str(NETWORK_CTRL), op], input_text=json.dumps({"uuid": uuid}), timeout=20)
        return {"ok": ok, "message": out or err or "VPN state updated"}

    if act == "warp.protocol":
        proto = payload.get("protocol", "MASQUE")
        ok, out, err = run(["python3", str(NETWORK_CTRL), "warp-protocol"], input_text=json.dumps({"protocol": proto}), timeout=15)
        return {"ok": ok, "message": out or err or f"WARP protocol set to {proto}"}

    if act == "vpn.import":
        path = payload.get("path", "")
        ok, out, err = run(["python3", str(NETWORK_CTRL), "import"], input_text=json.dumps({"path": path}), timeout=15)
        return {"ok": ok, "message": out or err or f"Imported WireGuard config {path}"}

    if act == "tailscale.toggle":
        cmd = "up" if payload.get("enabled") else "down"
        ok, out, err = run(["tailscale", cmd], timeout=15)
        return {"ok": ok, "message": out or err or f"Tailscale {cmd}"}

    if act == "tailscale.exitnode":
        node = payload.get("node", "")
        ok, out, err = run(["tailscale", "set", f"--exit-node={node}"], timeout=10)
        return {"ok": ok, "message": out or err or (f"Exit node set to {node}" if node else "Cleared exit node")}

    if act == "dns.set":
        provider = payload.get("provider", "DHCP")
        ok, out, err = run(["omarchy-dns", provider])
        return {"ok": ok, "message": f"DNS provider set to {provider}"}

    # --- Bluetooth ---
    if act == "bt.power":
        state = "on" if payload.get("enabled") else "off"
        ok, out, err = run(["omarchy-bluetooth-power", state])
        return {"ok": ok, "message": f"Bluetooth turned {state}"}

    if act == "bt.discoverable":
        state = "on" if payload.get("enabled") else "off"
        ok, out, err = run(["bluetoothctl", "discoverable", state])
        return {"ok": ok, "message": f"Bluetooth discoverable {state}"}

    if act == "bt.scan":
        run(["bluetoothctl", "--timeout", "4", "scan", "on"], timeout=6)
        return {"ok": True, "message": "Bluetooth device discovery scan finished"}

    if act == "bt.device":
        sub = payload.get("sub", "connect")
        addr = payload.get("address", "")
        if sub in ("trust", "untrust", "block", "unblock", "remove"):
            ok, out, err = run(["bluetoothctl", sub, addr])
        else:
            ok, out, err = run(["omarchy-bluetooth-device", sub, addr], timeout=15)
        return {"ok": ok, "message": out or err or f"Bluetooth {sub} {addr}"}

    # --- Audio, PipeWire & EasyEffects ---
    if act == "audio.volume":
        val = int(payload.get("value", 75))
        run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{val}%"])
        return {"ok": True, "message": f"Output volume set to {val}%"}

    if act == "audio.mute":
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
        return {"ok": True, "message": "Output mute toggled"}

    if act == "audio.mic_volume":
        val = int(payload.get("value", 75))
        run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", f"{val}%"])
        return {"ok": True, "message": f"Microphone gain set to {val}%"}

    if act == "audio.mic_mute":
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"])
        return {"ok": True, "message": "Microphone mute toggled"}

    if act == "audio.sink":
        name = payload.get("name", "")
        run(["pactl", "set-default-sink", name])
        return {"ok": True, "message": f"Switched default audio output to {name}"}

    if act == "audio.source":
        name = payload.get("name", "")
        run(["pactl", "set-default-source", name])
        return {"ok": True, "message": f"Switched default audio input to {name}"}

    if act == "audio.stream_volume":
        sid = str(payload.get("id", ""))
        val = int(payload.get("value", 100))
        run(["pactl", "set-sink-input-volume", sid, f"{val}%"])
        return {"ok": True, "message": f"Stream #{sid} volume set to {val}%"}

    if act == "audio.stream_mute":
        sid = str(payload.get("id", ""))
        run(["pactl", "set-sink-input-mute", sid, "toggle"])
        return {"ok": True, "message": f"Toggled mute on stream #{sid}"}

    if act == "audio.mpris":
        player = payload.get("player", "")
        cmd = payload.get("cmd", "play-pause")
        args = ["playerctl"] + (["-p", player] if player else []) + [cmd]
        ok, out, err = run(args)
        return {"ok": ok, "message": f"Sent {cmd} to {player or 'media player'}"}

    if act == "audio.tuning":
        state = "on" if payload.get("enabled") else "off"
        ok, out, err = run(["omarchy-audio-tuning", state])
        return {"ok": ok, "message": f"Laptop speaker DSP tuning: {state}"}

    if act == "easyeffects.launch":
        sp.Popen(["uwsm-app", "--", "easyeffects"])
        return {"ok": True, "message": "Launched EasyEffects DSP Studio"}

    # --- Displays, Monitors & Hyprland ---
    if act == "display.brightness":
        val = int(payload.get("value", 75))
        run(["omarchy-brightness-display", f"{val}%"])
        return {"ok": True, "message": f"Display brightness set to {val}%"}

    if act == "display.textsize":
        px = int(payload.get("size", 12))
        ok, out, err = run(["omarchy-display-text-size", str(px)])
        return {"ok": ok, "message": f"Global UI text size set to {px} px"}

    if act == "display.scale":
        scale = str(payload.get("scale", "1"))
        ok, out, err = run(["omarchy-hyprland-monitor-scaling", scale])
        return {"ok": ok, "message": f"Monitor fractional scale set to {scale}x"}

    if act == "display.internal":
        state = "on" if payload.get("enabled") else "off"
        ok, out, err = run(["omarchy-hyprland-display-internal", state])
        return {"ok": ok, "message": f"Internal laptop display turned {state}"}

    if act == "display.mirror":
        state = "on" if payload.get("enabled") else "off"
        ok, out, err = run(["omarchy-hyprland-display-mirror", state])
        return {"ok": ok, "message": f"Display mirroring turned {state}"}

    if act == "nightlight.toggle":
        ok, out, err = run(["omarchy-toggle-nightlight"])
        return {"ok": ok, "message": out or "Hyprsunset Nightlight toggled"}

    if act == "hyprland.live":
        gaps_in = int(payload.get("gaps_in", 6))
        gaps_out = int(payload.get("gaps_out", 10))
        border = int(payload.get("border_size", 1))
        rounding = int(payload.get("rounding", 14))
        active_op = float(payload.get("active_opacity", 0.94))
        inactive_op = float(payload.get("inactive_opacity", 0.84))
        blur = "true" if payload.get("blur_enabled", True) else "false"
        bsize = int(payload.get("blur_size", 10))
        passes = int(payload.get("blur_passes", 3))
        lua = (
            f"hl.config({{ general = {{ gaps_in = {gaps_in}, gaps_out = {gaps_out}, border_size = {border} }}, "
            f"decoration = {{ rounding = {rounding}, active_opacity = {active_op}, inactive_opacity = {inactive_op}, "
            f"blur = {{ enabled = {blur}, size = {bsize}, passes = {passes} }} }} }})"
        )
        ok, out, err = run(["hyprctl", "eval", lua])
        return {"ok": ok, "message": "Applied live Hyprland compositor geometry, opacity & blur"}

    if act == "hyprglass.live":
        preset = payload.get("preset", "clear")
        spec = float(payload.get("specular_strength", 0.7))
        refr = float(payload.get("refraction_strength", 0.5))
        chrom = float(payload.get("chromatic_aberration", 0.35))
        fres = float(payload.get("fresnel_strength", 0.55))
        bevel = float(payload.get("bevel_strength", 0.7))
        lens = float(payload.get("lens_distortion", 0.3))
        lua = (
            f'hl.config({{ plugin = {{ hyprglass = {{ preset = "{preset}", specular_strength = {spec}, '
            f'refraction_strength = {refr}, chromatic_aberration = {chrom}, fresnel_strength = {fres}, '
            f'bevel_strength = {bevel}, lens_distortion = {lens} }} }} }})'
        )
        ok, out, err = run(["hyprctl", "eval", lua])
        return {"ok": ok, "message": f"Updated Hyprglass liquid-glass shader ({preset})"}

    if act == "input.live":
        sens = float(payload.get("sensitivity", 0.4))
        nat = "true" if payload.get("natural_scroll", True) else "false"
        sfac = float(payload.get("scroll_factor", 1.0))
        dwt = "true" if payload.get("disable_while_typing", False) else "false"
        rate = int(payload.get("repeat_rate", 40))
        delay = int(payload.get("repeat_delay", 600))
        lua = (
            f"hl.config({{ input = {{ sensitivity = {sens}, repeat_rate = {rate}, repeat_delay = {delay}, "
            f"touchpad = {{ natural_scroll = {nat}, scroll_factor = {sfac}, disable_while_typing = {dwt} }} }} }})"
        )
        ok, out, err = run(["hyprctl", "eval", lua])
        return {"ok": ok, "message": "Applied live mouse, touchpad & keyboard repeat parameters"}

    # --- Top Bar, Dynamic Island, Notifications, Pomodoro ---
    if act == "bar.position":
        pos = payload.get("position", "top")
        ok, out, err = run(["omarchy-bar", "position", pos])
        return {"ok": ok, "message": f"Moved Omarchy bar to {pos}"}

    if act == "bar.transparent":
        ok, out, err = run(["omarchy-bar", "transparent", "toggle"])
        return {"ok": ok, "message": "Toggled top bar transparency"}

    if act == "island.save":
        existing = read_json(ISLAND_JSON, {})
        for k in (
            "compactHeight", "topOffset", "expandedWidth", "hoverExpand", "hoverDelay",
            "collapseDelay", "reduceMotion", "idleClock", "clockFormat", "appearance",
            "glass", "glassOpacity", "ambient", "ambientAudio", "peekOnTrackChange",
            "peekOnAgentDone", "autoExpandPermission", "hideOnFullscreen", "agentQuietSeconds"
        ):
            if k in payload:
                existing[k] = payload[k]
        write_json(ISLAND_JSON, existing)
        return {"ok": True, "message": "Saved Dynamic Island settings to dynamic-island.json (hot-reloaded)"}

    if act == "notify.save":
        write_notify_toml(payload)
        return {"ok": True, "message": "Saved Notification Center config.toml (hot-reloaded)"}

    if act == "notify.clear":
        if NOTIFY_HIST.exists():
            NOTIFY_HIST.write_text("[]\n")
        return {"ok": True, "message": "Cleared notification history"}

    if act == "agents.refresh":
        ok, out, err = run(["omarchy-agent-usage-update"], timeout=20)
        return {"ok": ok, "message": "Refreshed AI coding agent quotas & token usage"}

    if act == "theme.set":
        t = payload.get("theme", "")
        ok, out, err = run(["omarchy-theme-set", t], timeout=20)
        return {"ok": ok, "message": f"Applied Omarchy theme: {t}"}

    if act == "font.set":
        f = payload.get("font", "")
        ok, out, err = run(["omarchy-font-set", f], timeout=15)
        return {"ok": ok, "message": f"Set system monospace font to {f}"}

    if act == "plugin.toggle":
        pid = payload.get("id", "")
        cmd = "enable" if payload.get("enabled") else "disable"
        ok, out, err = run(["omarchy-plugin", cmd, pid])
        return {"ok": ok, "message": f"Plugin {pid} {cmd}d"}

    if act == "default.set":
        kind = payload.get("kind", "browser")
        val = payload.get("value", "")
        if kind in ("browser", "editor", "terminal", "agent"):
            ok, out, err = run([f"omarchy-default-{kind}", val])
            return {"ok": ok, "message": f"Default {kind} set to {val}"}

    # --- Cloud Drives ---
    if act == "glass.cmd":
        args = payload.get("args", ["status"])
        ok, out, err = run([str(GLASS_BIN)] + [str(a) for a in args], timeout=30)
        return {"ok": ok, "message": out or err or "Glass Drive operation completed"}

    if act == "icloud.mount":
        icloud_dir = HOME / "iCloudDrive"
        icloud_dir.mkdir(parents=True, exist_ok=True)
        remote = payload.get("remote", "icloud:")
        sp.Popen(["rclone", "mount", remote, str(icloud_dir), "--vfs-cache-mode", "writes", "--daemon"])
        return {"ok": True, "message": f"Mounted {remote} to {icloud_dir}"}

    # --- Power & Super-Battery ---
    if act == "power.profile":
        prof = payload.get("profile", "balanced")
        ok, out, err = run(["powerprofilesctl", "set", prof])
        return {"ok": ok, "message": f"Power governor set to {prof}"}

    if act == "superbattery.save":
        updates = {}
        for k in (
            "chargeLimit", "chargeLimitOn", "saverLevel", "saverOn",
            "warningLevel", "warningOn", "criticalLevel", "criticalOn",
            "notify", "repeatMinutes", "showPercentage", "volume"
        ):
            if k in payload:
                updates[k] = payload[k]
        update_super_battery_in_shell(updates)
        return {"ok": True, "message": "Updated Super-Battery thresholds & automation in shell.json"}

    if act == "idle.save":
        cfg = read_json(SHELL_JSON, {})
        cfg["idle"] = {
            "screensaver": int(payload.get("screensaver", 150)),
            "lock": int(payload.get("lock", 300)),
        }
        write_json(SHELL_JSON, cfg)
        return {"ok": True, "message": "Saved idle & screensaver timers to shell.json"}

    if act == "power.action":
        sub = payload.get("sub", "lock")
        if sub == "lock":
            run(["omarchy-system-lock"])
        elif sub == "suspend":
            run(["systemctl", "suspend"])
        elif sub == "reboot":
            run(["omarchy-system-reboot"])
        elif sub == "shutdown":
            run(["omarchy-system-shutdown"])
        return {"ok": True, "message": f"Triggered system {sub}"}

    # --- Wallpaper, Lockscreen & Widgets ---
    if act == "wallpaper.set":
        bg = payload.get("wallpaper", "")
        if bg == "next":
            ok, out, err = run(["omarchy-theme-bg-next"])
        else:
            ok, out, err = run(["omarchy-theme-bg-set", bg])
        return {"ok": ok, "message": out or err or "Updated desktop wallpaper"}

    if act == "lockscreen.trigger":
        ok, out, err = run(["omarchy-system-lock"])
        return {"ok": ok, "message": "Triggered lock screen test"}

    if act == "howdy.test":
        ok, out, err = run(["howdy", "test"])
        return {"ok": ok, "message": out or err or "Tested Howdy facial authentication"}

    # --- System Optimization & Purge ---
    if act == "optimize.purge":
        target = payload.get("target", "all")
        msgs = []
        if target in ("ram", "all"):
            ok, _, err = run("sync && echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null", shell=True)
            msgs.append("RAM PageCache/Dentries/Inodes purged" if ok else f"PageCache: {err}")
        if target in ("compact", "all"):
            ok, _, err = run("echo 1 | sudo tee /proc/sys/vm/compact_memory >/dev/null", shell=True)
            msgs.append("Physical RAM zones compacted" if ok else f"Compact: {err}")
        if target in ("swap", "all"):
            ok, _, err = run("sudo swapoff -a && sudo swapon -a", shell=True, timeout=25)
            msgs.append("Swap & ZRAM decompressed/flushed" if ok else f"Swap: {err}")
        if target in ("journal", "all"):
            ok, _, err = run("sudo journalctl --vacuum-time=2d", shell=True)
            msgs.append("Systemd journal vacuumed (2d)" if ok else f"Journal: {err}")
        if target in ("pacman", "all"):
            ok, _, err = run(["omarchy-update-pkg-prune"], timeout=20)
            msgs.append("Pacman cache pruned" if ok else "Checked package cache")
        return {"ok": True, "message": " · ".join(msgs)}

    if act == "disk.speedtest":
        ok, out, err = run(["omarchy-disk-speedtest"], timeout=35)
        return {"ok": ok, "message": out or err or "Disk speedtest complete", "data": out}

    # --- Security, Channel & Subsystems ---
    if act == "channel.set":
        ch = payload.get("channel", "stable")
        ok, out, err = run(["omarchy-channel-set", ch])
        return {"ok": ok, "message": f"Omarchy release channel set to {ch}"}

    if act == "restart.service":
        svc = payload.get("service", "shell")
        allowed = ("shell", "wifi", "bluetooth", "audio", "hyprctl", "hyprsunset", "trackpad", "walker")
        if svc in allowed:
            ok, out, err = run([f"omarchy-restart-{svc}"], timeout=15)
            return {"ok": ok, "message": f"Restarted {svc} subsystem"}

    return {"ok": False, "message": f"Unknown action: {act}"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/state":
            self._send_json(collect_all_state())
            return

        rel = parsed.path.lstrip("/") or "index.html"
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR)) or not target.is_file():
            target = STATIC_DIR / "index.html"
        content = target.read_bytes()
        ctype = "text/html; charset=utf-8"
        if target.suffix == ".css":
            ctype = "text/css"
        elif target.suffix == ".js":
            ctype = "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if self.path == "/api/action":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
                res = handle_action(payload)
                self._send_json(res)
            except Exception as e:
                self._send_json({"ok": False, "message": str(e)}, status=500)
            return
        self._send_json({"ok": False, "message": "Not found"}, status=404)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 4455), Handler)
    print("Omarchy System Control Center API + UI listening on http://localhost:4455", flush=True)
    server.serve_forever()
