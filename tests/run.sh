#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT

mock_bin="$test_dir/bin"
mkdir -p "$mock_bin"

cat >"$mock_bin/slurp" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' '10,20 1x1'
EOF

cat >"$mock_bin/grim" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >"$TEST_GRIM_ARGS"
touch "${@: -1}"
EOF

cat >"$mock_bin/magick" <<'EOF'
#!/usr/bin/env bash
printf '%s' '17 34 51'
EOF

cat >"$mock_bin/pkill" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >"$TEST_PKILL_ARGS"
EOF

cat >"$mock_bin/satty" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >"$TEST_SATTY_ARGS"
printf '%s\n' "${GTK_CSD:-}" >"$TEST_SATTY_CSD"
printf '%s\n' "${GDK_WAYLAND_DISABLE:-}" >"$TEST_SATTY_PROTOCOLS"
printf '%s\n' "$XDG_CONFIG_HOME" >"$TEST_SATTY_PROFILE"
cat "$XDG_CONFIG_HOME/satty/overrides.css" >"$TEST_SATTY_CSS"
EOF

chmod +x "$mock_bin"/*

export PATH="$mock_bin:$PATH"
export TEST_GRIM_ARGS="$test_dir/grim.args"
export TEST_PKILL_ARGS="$test_dir/pkill.args"
export TEST_SATTY_ARGS="$test_dir/satty.args"
export TEST_SATTY_CSD="$test_dir/satty.csd"
export TEST_SATTY_PROTOCOLS="$test_dir/satty.protocols"
export TEST_SATTY_PROFILE="$test_dir/satty.profile"
export TEST_SATTY_CSS="$test_dir/satty.css"

rgb=$(
  "$repo_dir/screen-toolkit/scripts/color-picker.sh" "$test_dir/pixel.png"
)
test "$rgb" = "17 34 51"
test "$(cat "$TEST_GRIM_ARGS")" = "-g 10,20 1x1 -t png $test_dir/pixel.png"

/usr/bin/python3 "$repo_dir/tests/frozen_capture_test.py"
/usr/bin/python3 "$repo_dir/tests/popup_editor_test.py"

# Spaces and shell characters must stay literal; the save directory must exist.
image="$test_dir/a 'quoted' image.png"
output="$test_dir/new folder/a screenshot.png"
/usr/bin/python3 - "$image" <<'PY'
import cairo
import sys
cairo.ImageSurface(cairo.FORMAT_ARGB32, 102, 24).write_to_png(sys.argv[1])
PY
MANGO_INSTANCE_SIGNATURE=test GDK_WAYLAND_DISABLE=wp_viewporter SCREEN_TOOLKIT_EDITOR_WIDTH=1920 SCREEN_TOOLKIT_EDITOR_HEIGHT=1080 XDG_CONFIG_HOME="$test_dir/config" "$repo_dir/screen-toolkit/scripts/annotate.sh" "$image" "$output"
test -d "$test_dir/new folder"
mapfile -t satty_args <"$TEST_SATTY_ARGS"
test "${satty_args[0]}" = "--filename"
test "${satty_args[1]}" = "$image"
test "${satty_args[2]}" = "--floating-hack"
test "${satty_args[3]}" = "--resize"
test "${satty_args[4]}" = "1040x560"
test "${satty_args[5]}" = "--title"
test "${satty_args[6]}" = "Screenshot Markup"
test "${satty_args[7]}" = "--no-window-decoration"
test "${satty_args[8]}" = "--output-filename"
test "${satty_args[9]}" = "$output"
test "$(cat "$TEST_SATTY_PROTOCOLS")" = "wp_viewporter"
test ! -e "$(cat "$TEST_SATTY_PROFILE")"
rg -q 'min-height: 560px' "$TEST_SATTY_CSS"

MANGO_INSTANCE_SIGNATURE= XDG_CONFIG_HOME="$test_dir/config" "$repo_dir/screen-toolkit/scripts/annotate.sh" "$image"
mapfile -t satty_args <"$TEST_SATTY_ARGS"
test "${#satty_args[@]}" = 8
test "${satty_args[2]}" = "--floating-hack"
test "${satty_args[6]}" = "Screenshot Markup"

"$repo_dir/screen-toolkit/scripts/record.sh" stop gpu-screen-recorder
test "$(cat "$TEST_PKILL_ARGS")" = "-INT -f ^(/.*/)?gpu-screen-recorder"

printf '%s\n' 'screen-toolkit tests: ok'
