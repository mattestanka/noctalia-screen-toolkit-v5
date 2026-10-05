#!/usr/bin/python3
"""Exercise the saved frame crop, including shifted and scaled monitors."""

import importlib.util
import tempfile
import sys
import unittest
from pathlib import Path

import cairo

sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location(
    "frozen_capture", Path(__file__).resolve().parents[1] / "screen-toolkit/scripts/frozen-capture.py"
)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class FrozenCaptureTests(unittest.TestCase):
    def test_signed_geometry(self):
        self.assertEqual(capture.parse_geometry("-1920,-100 600x400\n"), (-1920, -100, 600, 400))
        for invalid in ("", "0,0 0x10", "0,0 10x0", "0,0 10x10; bad"):
            with self.assertRaises(ValueError):
                capture.parse_geometry(invalid)

    def test_window_selection_prefers_visible_floating_client(self):
        clients = [
            dict(is_visible=True, x=-100, y=-50, width=500, height=400),
            dict(is_visible=True, x=-50, y=-20, width=100, height=80),
            dict(is_visible=False, x=-49, y=-19, width=5, height=5),
        ]
        self.assertEqual(capture.window_at(clients, -48, -18), (-50, -20, 100, 80))
        # Adjacent windows do not share a boundary pixel.
        self.assertEqual(capture.window_at(clients, 50, -18), (-100, -50, 500, 400))
        with self.assertRaises(ValueError):
            capture.window_at(clients, 900, 900)

    def test_crop_uses_frozen_pixels_at_capture_scale(self):
        # Two outputs: one above/left of zero, one shifted down. grim captured
        # both at 2x scale; crops must use that scale and the global origin.
        bounds = capture.desktop_bounds([(-100, -20, 100, 80), (0, 0, 100, 80)])
        self.assertEqual(bounds, (-100, -20, 200, 100))
        snapshot = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 200)
        cr = cairo.Context(snapshot)
        cr.set_source_rgb(1, 0, 0)
        cr.paint()
        cr.set_source_rgb(0, 1, 0)
        cr.rectangle(200, 40, 200, 160)
        cr.fill()
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "crop.png"
            rect = capture.crop_snapshot(cairo, snapshot, bounds, (-10, 0, 20, 10), dest)
            self.assertEqual(rect, (-10, 0, 20, 10))
            image = cairo.ImageSurface.create_from_png(str(dest))
            self.assertEqual((image.get_width(), image.get_height()), (40, 20))
            data = image.get_data()
            # Endianness independent: compare pixels with the source frame.
            source = snapshot.get_data()
            self.assertEqual(bytes(data[:4]), bytes(source[40 * snapshot.get_stride() + 180 * 4:][:4]))
            self.assertEqual(bytes(data[30 * 4:][:4]), bytes(source[40 * snapshot.get_stride() + 210 * 4:][:4]))
            self.assertNotEqual(bytes(data[:4]), bytes(data[30 * 4:][:4]))

    def test_window_outside_monitor_is_clipped(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 100)
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "crop.png"
            rect = capture.crop_snapshot(cairo, surface, (0, 0, 100, 50), (-10, -10, 30, 30), dest)
            self.assertEqual(rect, (0, 0, 20, 20))
            image = cairo.ImageSurface.create_from_png(str(dest))
            self.assertEqual((image.get_width(), image.get_height()), (40, 40))
            with self.assertRaises(ValueError):
                capture.crop_snapshot(cairo, surface, (0, 0, 100, 50), (300, 300, 10, 10), dest)


if __name__ == "__main__":
    unittest.main()
