#!/usr/bin/python3
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "popup_editor", Path(__file__).resolve().parents[1] / "screen-toolkit/scripts/popup-editor.py"
)
popup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(popup)


class PopupEditorTests(unittest.TestCase):
    def test_tiny_strip_gets_usable_canvas(self):
        self.assertEqual(popup.popup_size(102, 24, 1920, 1080), (1040, 560, 1040, 560))

    def test_large_and_portrait_captures_fit_monitor(self):
        for image in ((3840, 2160), (1080, 4000), (102, 24)):
            for monitor in ((1920, 1080), (1366, 768), (1280, 600)):
                width, height, minimum_width, minimum_height = popup.popup_size(*image, *monitor)
                self.assertLessEqual(width, int(monitor[0] * .85))
                self.assertLessEqual(height, int(monitor[1] * .82))
                self.assertGreaterEqual(width, minimum_width)
                self.assertGreaterEqual(height, minimum_height)

    def test_png_dimensions_and_bad_file(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "capture.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 102, 24))
            self.assertEqual(popup.png_size(image), (102, 24))
            image.write_text("not a screenshot")
            with self.assertRaises(ValueError):
                popup.png_size(image)

    def test_private_profile_preserves_original_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "config"
            (original / "satty").mkdir(parents=True)
            config = original / "satty/config.toml"
            config.write_text('[general]\ninitial-tool = "brush"\n')
            custom = original / "satty/overrides.css"
            custom.write_text("/* user style */")
            (original / "gtk-4.0").mkdir()
            theme = root / "toolkit.css"
            theme.write_text("/* plugin style */")
            profile = root / "profile"
            profile.mkdir()
            popup.prepare_profile(profile, original, theme, 1040, 560)
            self.assertTrue((profile / "satty/config.toml").is_symlink())
            self.assertTrue((profile / "gtk-4.0").is_symlink())
            css = (profile / "satty/overrides.css").read_text()
            self.assertIn("/* user style */", css)
            self.assertIn("/* plugin style */", css)
            self.assertIn("min-height: 560px", css)
            self.assertEqual(config.read_text(), '[general]\ninitial-tool = "brush"\n')
            self.assertEqual(custom.read_text(), "/* user style */")


if __name__ == "__main__":
    unittest.main()
