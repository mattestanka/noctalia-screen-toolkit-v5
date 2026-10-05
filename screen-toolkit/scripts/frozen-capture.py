#!/usr/bin/python3
"""Show one frozen desktop frame behind slurp, then crop that same frame.

Use the distro Python: virtualenv/mise interpreters often lack the system GI
bindings. Geometry is global and logical; PNG coordinates are device pixels.
"""

import argparse
import json
import math
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_geometry(text):
    match = re.fullmatch(r"(-?\d+),(-?\d+) (\d+)x(\d+)", text.strip())
    if not match:
        raise ValueError("invalid selection geometry")
    rect = tuple(map(int, match.groups()))
    if rect[2] <= 0 or rect[3] <= 0:
        raise ValueError("empty selection")
    return rect


def window_at(clients, x, y):
    """Prefer the smallest visible Mango client containing the click."""
    matches = []
    for client in clients:
        if not client.get("is_visible"):
            continue
        rect = tuple(math.floor(client.get(key, 0)) for key in ("x", "y", "width", "height"))
        cx, cy, width, height = rect
        if width > 0 and height > 0 and cx <= x < cx + width and cy <= y < cy + height:
            matches.append(rect)
    if not matches:
        raise ValueError("no window at that point")
    return min(matches, key=lambda rect: rect[2] * rect[3])


def desktop_bounds(rects):
    left = min(rect[0] for rect in rects)
    top = min(rect[1] for rect in rects)
    right = max(rect[0] + rect[2] for rect in rects)
    bottom = max(rect[1] + rect[3] for rect in rects)
    return left, top, right - left, bottom - top


def crop_snapshot(cairo, snapshot, bounds, rect, destination):
    """Crop in logical coordinates, preserving grim's captured pixel scale."""
    bx, by, bw, bh = bounds
    x, y, width, height = rect
    left, top = max(x, bx), max(y, by)
    right, bottom = min(x + width, bx + bw), min(y + height, by + bh)
    if right <= left or bottom <= top:
        raise ValueError("selection is outside the desktop")
    sx, sy = snapshot.get_width() / bw, snapshot.get_height() / bh
    px, py = round((left - bx) * sx), round((top - by) * sy)
    pw = round((right - bx) * sx) - px
    ph = round((bottom - by) * sy) - py
    cropped = cairo.ImageSurface(cairo.FORMAT_ARGB32, pw, ph)
    cr = cairo.Context(cropped)
    cr.set_source_surface(snapshot, -px, -py)
    cr.paint()
    cropped.write_to_png(str(destination))
    return left, top, right - left, bottom - top


def select_frozen(Gtk, GLib, GLibUnix, LayerShell, cairo, display, monitors, rects, snapshot, bounds, point):
    windows = []
    pending = set(range(len(monitors)))
    state = {"process": None, "selection": None, "error": None}

    def cancel():
        Gtk.main_quit()
        return True

    def poll_selector():
        process = state["process"]
        if process.poll() is None:
            return True
        stdout, _ = process.communicate()
        if process.returncode == 0:
            state["selection"] = stdout.strip()
        Gtk.main_quit()
        return False

    def start_selector():
        try:
            args = ["slurp", "-p"] if point else ["slurp", "-f", "%x,%y %wx%h"]
            state["process"] = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            GLib.timeout_add(30, poll_selector)
        except OSError as exc:
            state["error"] = exc
            Gtk.main_quit()
        return False

    def draw(_widget, cr, index):
        bx, by, bw, bh = bounds
        x, y, _, _ = rects[index]
        cr.scale(bw / snapshot.get_width(), bh / snapshot.get_height())
        cr.set_source_surface(snapshot, -(x - bx) * snapshot.get_width() / bw,
                              -(y - by) * snapshot.get_height() / bh)
        cr.paint()
        if index in pending:
            pending.remove(index)
            if not pending:
                # Let every output commit the frozen image before slurp maps.
                GLib.timeout_add(100, start_selector)
        return False

    signal_sources = []
    try:
        for index, monitor in enumerate(monitors):
            window = Gtk.Window()
            windows.append(window)
            window.set_decorated(False)
            window.set_app_paintable(True)
            window.set_visual(window.get_screen().get_rgba_visual())
            LayerShell.init_for_window(window)
            LayerShell.set_namespace(window, "screen-toolkit-freeze")
            LayerShell.set_monitor(window, monitor)
            LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
            LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.NONE)
            LayerShell.set_exclusive_zone(window, -1)
            for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
                LayerShell.set_anchor(window, edge, True)
            window.connect("draw", draw, index)
            window.connect("realize", lambda w: w.input_shape_combine_region(cairo.Region()))
            window.show_all()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal_sources.append(GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signum, cancel))
        Gtk.main()
    finally:
        for source in signal_sources:
            GLib.source_remove(source)
        process = state["process"]
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for window in windows:
            window.destroy()
        display.flush()
    if state["error"]:
        raise state["error"]
    return state["selection"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", action="store_true")
    parser.add_argument("--cursor", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    for command in ("grim", "slurp") + (("mmsg",) if args.window else ()):
        if shutil.which(command) is None:
            print(f"ERROR: missing dependency: {command}", file=sys.stderr)
            return 3
    try:
        import cairo
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("GLibUnix", "2.0")
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import Gdk, GLib, GLibUnix, Gtk, GtkLayerShell
    except (ImportError, ValueError) as exc:
        print(f"ERROR: frozen capture needs python-gobject, python-cairo, gtk3 and gtk-layer-shell: {exc}", file=sys.stderr)
        return 3
    try:
        display = Gdk.Display.get_default()
        if display is None or not GtkLayerShell.is_supported():
            raise ValueError("frozen capture requires a Wayland layer-shell compositor")
        monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
        if not monitors:
            raise ValueError("no monitors available")
        rects = [(r.x, r.y, r.width, r.height) for r in (m.get_geometry() for m in monitors)]
        bounds = desktop_bounds(rects)
        clients = []
        if args.window:
            clients = json.loads(subprocess.check_output(["mmsg", "get", "all-clients"], text=True))["clients"]
        with tempfile.TemporaryDirectory(prefix="screen-toolkit-freeze-") as temp:
            path = Path(temp) / "desktop.png"
            bx, by, bw, bh = bounds
            command = ["grim"] + (["-c"] if args.cursor else [])
            subprocess.run(command + ["-g", f"{bx},{by} {bw}x{bh}", str(path)], check=True)
            snapshot = cairo.ImageSurface.create_from_png(str(path))
            selection = select_frozen(Gtk, GLib, GLibUnix, GtkLayerShell, cairo, display, monitors, rects,
                                      snapshot, bounds, args.window)
            if not selection:
                return 130
            rect = parse_geometry(selection)
            if args.window:
                rect = window_at(clients, rect[0], rect[1])
            rect = crop_snapshot(cairo, snapshot, bounds, rect, args.output)
            print(f"{rect[0]},{rect[1]} {rect[2]}x{rect[3]}")
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, cairo.Error) as exc:
        print(f"ERROR: frozen capture failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
