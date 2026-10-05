#!/usr/bin/python3
"""Give Satty a bounded popup and a private Screen Toolkit style profile."""

import argparse
import os
from pathlib import Path
import signal
import struct
import subprocess
import tempfile


def png_size(path):
    with Path(path).open("rb") as image:
        header = image.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("expected a PNG screenshot")
    width, height = struct.unpack(">II", header[16:24])
    if not width or not height:
        raise ValueError("empty screenshot")
    return width, height


def popup_size(image_width, image_height, monitor_width, monitor_height):
    maximum_width = max(1, int(monitor_width * 0.85))
    maximum_height = max(1, int(monitor_height * 0.82))
    minimum_width = min(1040, maximum_width)
    minimum_height = min(560, maximum_height)
    scale = min(1, max(1, maximum_width - 48) / image_width,
                max(1, maximum_height - 170) / image_height)
    width = min(maximum_width, max(minimum_width, round(image_width * scale) + 48))
    height = min(maximum_height, max(minimum_height, round(image_height * scale) + 170))
    return width, height, minimum_width, minimum_height


def prepare_profile(profile, original_config, style, minimum_width, minimum_height):
    satty = profile / "satty"
    satty.mkdir()
    # Retain the user's brushes, colors, fonts, keybindings and GTK theme.
    # Symlinks are read-only inputs here; no original configuration is edited.
    for name in ("gtk-4.0", "gtk-3.0"):
        source = original_config / name
        if source.exists():
            (profile / name).symlink_to(source, target_is_directory=True)
    config = original_config / "satty/config.toml"
    if config.exists():
        (satty / "config.toml").symlink_to(config)
    custom_css = original_config / "satty/overrides.css"
    existing = custom_css.read_text() if custom_css.exists() else ""
    dimensions = f"\nwindow.root {{ min-width: {minimum_width}px; min-height: {minimum_height}px; }}\n"
    (satty / "overrides.css").write_text(existing + "\n" + style.read_text() + dimensions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("output", nargs="?", default="")
    args = parser.parse_args()
    # The plugin passes the focused output's logical dimensions. The defaults
    # also keep direct standalone invocations comfortable on a 1080p monitor.
    monitor_width = int(os.environ.get("SCREEN_TOOLKIT_EDITOR_WIDTH", "1920"))
    monitor_height = int(os.environ.get("SCREEN_TOOLKIT_EDITOR_HEIGHT", "1080"))
    width, height, minimum_width, minimum_height = popup_size(*png_size(args.image), monitor_width, monitor_height)
    original_config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))).resolve()
    style = Path(__file__).resolve().parents[1] / "styles/satty.css"
    command = ["satty", "--filename", args.image, "--floating-hack", "--resize", f"{width}x{height}",
               "--title", "Screenshot Markup", "--no-window-decoration"]
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        command += ["--output-filename", args.output]
    with tempfile.TemporaryDirectory(prefix="screen-toolkit-editor-") as temp:
        profile = Path(temp)
        prepare_profile(profile, original_config, style, minimum_width, minimum_height)
        env = dict(os.environ, XDG_CONFIG_HOME=str(profile))
        editor = subprocess.Popen(command, env=env)
        previous = {}
        def forward(signum, _frame):
            if editor.poll() is None:
                editor.send_signal(signum)
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, forward)
            return editor.wait()
        finally:
            if editor.poll() is None:
                editor.terminate()
                editor.wait()
            for signum, handler in previous.items():
                signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
