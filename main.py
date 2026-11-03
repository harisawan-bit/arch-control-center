#!/usr/bin/python3
"""
Arch Control Center — Native Desktop Application Entry Point
Spawns background API server and opens native GTK/WebKit window.
"""
import os
import sys
import threading
import time
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from backend import HTTPServer, Handler

PORT = 4455

def start_server():
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()

def run_gtk():
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('WebKit2', '4.1')
    from gi.repository import Gtk, WebKit2, Gio, GLib

    win = Gtk.Window(title="Arch Control Center")
    win.set_default_size(1180, 800)
    win.set_position(Gtk.WindowPosition.CENTER)

    # Set icon if available
    icon_svg = ROOT_DIR / "assets/arch-control-center.svg"
    if icon_svg.exists():
        win.set_icon_from_file(str(icon_svg))

    # WebKit settings
    settings = WebKit2.Settings()
    settings.set_enable_developer_extras(False)
    settings.set_enable_smooth_scrolling(True)
    settings.set_javascript_can_access_clipboard(True)

    view = WebKit2.WebView.new_with_settings(settings)
    view.load_uri(f"http://127.0.0.1:{PORT}")

    win.add(view)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

def main():
    # Start server in background thread
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    time.sleep(0.4)

    try:
        run_gtk()
    except Exception as e:
        # Fallback to browser app mode if GTK/WebKit issue occurs
        print(f"GTK window error ({e}), launching in application window mode...", file=sys.stderr)
        os.system(f"google-chrome-stable --app=http://127.0.0.1:{PORT} --class=arch-control-center")

if __name__ == "__main__":
    main()
