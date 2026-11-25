#!/usr/bin/python3
"""Draw over a live Wayland output and save the composited desktop with grim."""

import argparse
from datetime import datetime
import fcntl
from itertools import count
import math
import os
from pathlib import Path
import shutil
import signal
import tempfile

try:
    import cairo
    import gi

    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("GLibUnix", "2.0")
    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GLibUnix, Gtk, GtkLayerShell as LayerShell
except (ImportError, ValueError) as exc:
    raise SystemExit(f"ERROR: Draw Live needs python-gobject, python-cairo, gtk3 and gtk-layer-shell ({exc})")

TOOLS = {
    "pen": "Pen", "highlighter": "Highlighter", "line": "Line",
    "arrow": "Arrow", "rectangle": "Rectangle", "ellipse": "Ellipse",
}
COLORS = {
    "Red": "#ff515e", "Yellow": "#ffd43b", "Green": "#51cf66",
    "Cyan": "#3bc9db", "Blue": "#5c7cfa", "Purple": "#cc5de8",
    "White": "#ffffff", "Black": "#121212",
}


def paint_stroke(cr, tool, color, points):
    width = 16 if tool == "highlighter" else 4
    cr.set_source_rgba(color.red, color.green, color.blue, 0.4 if tool == "highlighter" else 1)
    cr.set_line_width(width)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    x, y = points[0]
    end_x, end_y = points[-1]
    dx, dy = end_x - x, end_y - y
    if tool in ("pen", "highlighter"):
        cr.move_to(x, y)
        cr.line_to(x, y)  # A click without movement still leaves a dot.
        for point in points[1:]:
            cr.line_to(*point)
    elif tool == "rectangle":
        cr.rectangle(x, y, dx, dy)
    elif tool == "ellipse":
        if not dx or not dy:
            return
        cr.save()
        cr.translate(x + dx / 2, y + dy / 2)
        cr.scale(abs(dx) / 2, abs(dy) / 2)
        cr.arc(0, 0, 1, 0, math.tau)
        cr.restore()
    else:
        cr.move_to(x, y)
        cr.line_to(end_x, end_y)
        length = math.hypot(dx, dy)
        if tool == "arrow" and length:
            angle = math.atan2(dy, dx)
            head = min(16, length / 2)
            for offset in (-0.55, 0.55):
                cr.move_to(end_x, end_y)
                cr.line_to(end_x - head * math.cos(angle + offset),
                           end_y - head * math.sin(angle + offset))
    cr.stroke()


def save_capture(source, directory, pattern):
    stem = Path(datetime.now().strftime(pattern)).name
    if stem in ("", ".", ".."):
        stem = datetime.now().strftime("live-draw-%Y-%m-%d_%H-%M-%S")
    for index in count():
        suffix = f"-{index}" if index else ""
        destination = directory / f"{stem}{suffix}.png"
        try:
            os.link(source, destination)
            return destination
        except FileExistsError:
            continue


class LiveDraw:
    def __init__(self, monitor, args):
        self.monitor = monitor
        self.args = args
        self.strokes = []
        self.undone = []
        self.stroke = None
        self.capture = None
        self.process = None
        self.status_timer = 0

        self.window = Gtk.Window(title="Draw Live")
        self.window.set_decorated(False)
        self.window.set_app_paintable(True)
        self.window.set_visual(self.window.get_screen().get_rgba_visual())
        LayerShell.init_for_window(self.window)
        LayerShell.set_namespace(self.window, "screen-toolkit-live-draw")
        LayerShell.set_monitor(self.window, monitor)
        LayerShell.set_layer(self.window, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self.window, LayerShell.KeyboardMode.EXCLUSIVE)
        LayerShell.set_exclusive_zone(self.window, -1)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self.window, edge, True)
        self.window.connect("destroy", self.close)
        self.window.connect("key-press-event", self.key_press)
        self.window.connect("draw", self.clear_background)

        overlay = Gtk.Overlay()
        self.window.add(overlay)
        self.canvas = Gtk.DrawingArea()
        self.canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                               | Gdk.EventMask.POINTER_MOTION_MASK)
        self.canvas.connect("draw", self.draw)
        self.canvas.connect("button-press-event", self.start_stroke)
        self.canvas.connect("motion-notify-event", self.move_stroke)
        self.canvas.connect("button-release-event", self.finish_stroke)
        overlay.add(self.canvas)

        self.toolbar = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER, valign=Gtk.Align.START, margin_top=16)
        self.toolbar.set_name("live-draw-toolbar")
        style = Gtk.CssProvider()
        style.load_from_data(b"""
            #live-draw-toolbar {
                padding: 6px;
                border-radius: 10px;
                background-color: @theme_bg_color;
            }
        """)
        self.toolbar.get_style_context().add_provider(style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        overlay.add_overlay(self.toolbar)

        self.mode = Gtk.ToggleButton(label="Interact")
        self.mode.set_tooltip_text("Use apps underneath the drawing")
        self.mode.connect("toggled", self.change_mode)
        self.toolbar.pack_start(self.mode, False, False, 0)
        self.tools = Gtk.ComboBoxText()
        self.tools.set_tooltip_text("Drawing tool")
        for tool, label in TOOLS.items():
            self.tools.append(tool, label)
        self.tools.set_active_id("pen")
        self.toolbar.pack_start(self.tools, False, False, 0)
        self.colors = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str)
        for name, value in COLORS.items():
            swatch = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 16, 16)
            swatch.fill((int(value[1:], 16) << 8) | 255)
            self.colors.append((swatch, name, value))
        self.palette = Gtk.ComboBox.new_with_model(self.colors)
        self.palette.set_tooltip_text("Ink color")
        self.palette.get_accessible().set_name("Ink color")
        swatch = Gtk.CellRendererPixbuf()
        self.palette.pack_start(swatch, False)
        self.palette.add_attribute(swatch, "pixbuf", 0)
        name = Gtk.CellRendererText()
        self.palette.pack_start(name, False)
        self.palette.add_attribute(name, "text", 1)
        self.palette.set_active(0)
        self.toolbar.pack_start(self.palette, False, False, 0)
        self.undo_button = self.icon_button("edit-undo-symbolic", "Undo (Ctrl+Z)", self.undo)
        self.redo_button = self.icon_button("edit-redo-symbolic", "Redo (Ctrl+Shift+Z)", self.redo)
        self.screenshot = Gtk.Button(label="Screenshot")
        self.screenshot.set_tooltip_text("Save the desktop and ink (Ctrl+S in Draw mode)")
        self.screenshot.connect("clicked", self.start_capture)
        self.toolbar.pack_start(self.screenshot, False, False, 0)
        self.screenshot.show()
        self.screenshot.set_size_request(self.screenshot.get_preferred_width()[1], -1)
        self.icon_button("window-close-symbolic", "Close Draw Live", self.window.destroy)
        self.toolbar.connect("size-allocate", lambda *_: self.update_input_region())
        self.refresh_canvas()

    def icon_button(self, icon, label, action):
        button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
        button.set_tooltip_text(label)
        button.get_accessible().set_name(label)
        button.connect("clicked", lambda _: action())
        self.toolbar.pack_start(button, False, False, 0)
        return button

    def clear_background(self, _widget, cr):
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.restore()
        return False

    def change_mode(self, button):
        interacting = button.get_active()
        button.set_label("Draw" if interacting else "Interact")
        button.set_tooltip_text("Resume drawing" if interacting else "Use apps underneath the drawing")
        self.tools.set_sensitive(not interacting)
        self.palette.set_sensitive(not interacting)
        LayerShell.set_keyboard_mode(
            self.window, LayerShell.KeyboardMode.NONE if interacting else LayerShell.KeyboardMode.EXCLUSIVE)
        self.update_input_region()

    def update_input_region(self):
        if not self.window.get_realized():
            return
        region = None
        if self.capture is not None or self.mode.get_active():
            region = cairo.Region()
            if self.capture is None:
                rect = self.toolbar.get_allocation()
                origin = self.toolbar.translate_coordinates(self.window, 0, 0)
                if origin is not None:
                    region.union(cairo.RectangleInt(*origin, rect.width, rect.height))
        self.window.input_shape_combine_region(region)

    def draw(self, _widget, cr):
        for stroke in self.strokes:
            paint_stroke(cr, *stroke)
        if self.stroke:
            paint_stroke(cr, *self.stroke)
        return False

    def start_stroke(self, _widget, event):
        if event.button != 1 or self.mode.get_active() or self.capture is not None:
            return False
        color = Gdk.RGBA()
        color.parse(self.colors[self.palette.get_active_iter()][2])
        self.stroke = (self.tools.get_active_id(), color, [(event.x, event.y)])
        self.canvas.queue_draw()
        return True

    def move_stroke(self, _widget, event):
        if not self.stroke:
            return False
        tool, _, points = self.stroke
        if tool in ("pen", "highlighter"):
            points.append((event.x, event.y))
        else:
            points[1:] = [(event.x, event.y)]
        self.canvas.queue_draw()
        return True

    def finish_stroke(self, widget, event):
        if event.button != 1 or not self.stroke:
            return False
        self.move_stroke(widget, event)
        self.strokes.append(self.stroke)
        self.stroke = None
        self.undone.clear()
        self.refresh_canvas()
        return True

    def refresh_canvas(self):
        self.undo_button.set_sensitive(bool(self.strokes))
        self.redo_button.set_sensitive(bool(self.undone))
        self.canvas.queue_draw()

    def undo(self):
        if self.strokes:
            self.undone.append(self.strokes.pop())
            self.refresh_canvas()

    def redo(self):
        if self.undone:
            self.strokes.append(self.undone.pop())
            self.refresh_canvas()

    def key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.window.destroy()
            return True
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            key = Gdk.keyval_to_lower(event.keyval)
            if key == Gdk.KEY_s:
                self.start_capture()
                return True
            if key == Gdk.KEY_z:
                if event.state & Gdk.ModifierType.SHIFT_MASK:
                    self.redo()
                else:
                    self.undo()
                return True
        return False

    def start_capture(self, _button=None):
        if self.capture is not None:
            return
        try:
            self.args.directory.mkdir(parents=True, exist_ok=True)
            self.capture = tempfile.TemporaryDirectory(prefix=".live-draw-", dir=self.args.directory)
        except OSError as exc:
            self.capture_status("Save failed", str(exc))
            return
        self.toolbar.hide()
        self.update_input_region()
        clock = self.window.get_frame_clock()
        handler = clock.connect_after("after-paint", self.toolbar_hidden)
        self.capture_frame_handler = handler
        clock.request_phase(Gdk.FrameClockPhase.AFTER_PAINT)

    def toolbar_hidden(self, clock):
        clock.disconnect(self.capture_frame_handler)
        # Let the compositor present the frame without the toolbar before capture.
        GLib.timeout_add(100, self.run_capture)

    def run_capture(self):
        rect = self.monitor.get_geometry()
        command = ["grim"]
        if self.args.cursor:
            command.append("-c")
        if self.args.output:
            command += ["-o", self.args.output]
        else:
            command += ["-g", f"{rect.x},{rect.y} {rect.width}x{rect.height}"]
        command.append(str(Path(self.capture.name) / "capture.png"))
        try:
            self.process = Gio.Subprocess.new(command, Gio.SubprocessFlags.STDERR_PIPE)
            self.process.communicate_utf8_async(None, None, self.capture_finished)
        except GLib.Error as exc:
            self.end_capture("Save failed", exc.message)
        return GLib.SOURCE_REMOVE

    def capture_finished(self, process, result):
        if self.capture is None:
            return
        self.process = None
        try:
            _, _, error = process.communicate_utf8_finish(result)
            if not process.get_successful():
                raise OSError(error.strip() or "grim could not capture this output")
            path = save_capture(Path(self.capture.name) / "capture.png", self.args.directory, self.args.pattern)
        except (OSError, ValueError, GLib.Error) as exc:
            self.end_capture("Save failed", str(exc))
        else:
            self.end_capture("Saved", str(path))

    def end_capture(self, label, detail):
        self.capture.cleanup()
        self.capture = None
        self.capture_status(label, detail)
        self.toolbar.show()
        self.update_input_region()

    def capture_status(self, label, detail):
        if self.status_timer:
            GLib.source_remove(self.status_timer)
        self.screenshot.set_label(label)
        self.screenshot.set_tooltip_text(detail)
        self.status_timer = GLib.timeout_add_seconds(3, self.reset_capture_status)

    def reset_capture_status(self):
        self.status_timer = 0
        self.screenshot.set_label("Screenshot")
        self.screenshot.set_tooltip_text("Save the desktop and ink (Ctrl+S in Draw mode)")
        return GLib.SOURCE_REMOVE

    def close(self, *_args):
        if self.process:
            self.process.force_exit()
        if self.capture is not None:
            self.capture.cleanup()
            self.capture = None
        Gtk.main_quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--pattern", default="%Y-%m-%d_%H-%M-%S")
    parser.add_argument("--position", nargs=2, type=int, metavar=("X", "Y"))
    parser.add_argument("--output")
    parser.add_argument("--cursor", action="store_true")
    args = parser.parse_args()

    display = Gdk.Display.get_default()
    if display is None or not LayerShell.is_supported():
        raise SystemExit("ERROR: Draw Live needs a Wayland compositor with layer-shell support")
    if shutil.which("grim") is None:
        raise SystemExit("ERROR: Draw Live needs grim")
    monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
    if args.position is None:
        monitor = display.get_primary_monitor() or (monitors[0] if monitors else None)
    else:
        monitor = None
        for candidate in monitors:
            rect = candidate.get_geometry()
            if args.position == [rect.x, rect.y]:
                monitor = candidate
                break
    if monitor is None:
        raise SystemExit("ERROR: The selected display is unavailable")

    lock_path = Path(GLib.get_user_runtime_dir()) / "screen-toolkit-live-draw.lock"
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        session = LiveDraw(monitor, args)
        monitor.connect("invalidate", lambda *_: session.window.destroy())
        for signum in (signal.SIGINT, signal.SIGTERM):
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signum, session.window.destroy)
        session.window.show_all()
        Gtk.main()


if __name__ == "__main__":
    main()
