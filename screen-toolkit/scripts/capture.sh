#!/usr/bin/env bash
# capture.sh <action> [args...]
#
# Actions:
#   annotate-region          — freeze the desktop, select and crop a region
#   annotate-window          — freeze the desktop, select and crop a Mango window
#                              output: /tmp/screen-toolkit-annotate.png
#                              stdout: "X,Y WxH" geometry string
#   palette   <geometry>     — extract 8 dominant hex colours from a captured region
#                              stdout: one "#RRGGBB" per line
#   qr        <geometry>     — capture a region and decode any QR / barcode found
#                              stdout: decoded text
#
# Exit codes:
#   1 — missing / invalid arguments
#   2 — capture or decode failed
#   3 — missing dependency
#   130 — frozen selection cancelled
#
# Used by: service.luau

set -euo pipefail

ACTION="${1:-}"
GRIM_CURSOR_ARGS=()
[ "${SCREEN_TOOLKIT_CAPTURE_CURSOR:-0}" = "1" ] && GRIM_CURSOR_ARGS+=(-c)

_require() {
    command -v "$1" >/dev/null 2>&1 \
        || { echo "ERROR: missing dependency: $1" >&2; exit 3; }
}

case "$ACTION" in

  annotate-region|annotate-window)
    SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    ARGS=(--output "${2:-/tmp/screen-toolkit-annotate.png}")
    [ "$ACTION" = "annotate-window" ] && ARGS+=(--window)
    [ "${SCREEN_TOOLKIT_CAPTURE_CURSOR:-0}" = "1" ] && ARGS+=(--cursor)
    exec "$SCRIPT_DIR/frozen-capture.py" "${ARGS[@]}"
    ;;

  palette)
    GEOMETRY="${2:-}"
    [ -n "$GEOMETRY" ] || { echo "ERROR: palette: missing <geometry>" >&2; exit 1; }
    _require grim
    _require magick

    FILE="/tmp/screen-toolkit-palette.png"

     sleep 0.15
     grim "${GRIM_CURSOR_ARGS[@]}" -g "$GEOMETRY" "$FILE" 2>/dev/null \
        || { echo "ERROR: palette: grim capture failed" >&2; exit 2; }

    magick "$FILE" -alpha off +dither -colors 8 -unique-colors txt:- 2>/dev/null \
        | grep -v '^#' \
        | grep -oP '#[0-9a-fA-F]{6}' \
        | head -8
    ;;

  qr)
    GEOMETRY="${2:-}"
    [ -n "$GEOMETRY" ] || { echo "ERROR: qr: missing <geometry>" >&2; exit 1; }
    _require grim
    _require zbarimg

     sleep 0.15
     grim "${GRIM_CURSOR_ARGS[@]}" -g "$GEOMETRY" /tmp/screen-toolkit-qr.png 2>/dev/null \
        || { echo "ERROR: qr: grim capture failed" >&2; exit 2; }

    zbarimg -q --raw /tmp/screen-toolkit-qr.png 2>/dev/null
    ;;

  *)
    echo "ERROR: unknown action '${ACTION}'. Expected: annotate-region | annotate-window | palette | qr" >&2
    exit 1
    ;;

esac
