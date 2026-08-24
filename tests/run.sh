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

cat >"$mock_bin/mmsg" <<'EOF'
#!/usr/bin/env bash
test "$*" = "get all-clients"
printf '%s\n' '{"clients":[{"is_visible":true,"x":0,"y":0,"width":500,"height":400},{"is_visible":true,"x":5,"y":10,"width":100,"height":80},{"is_visible":false,"x":9,"y":19,"width":5,"height":5}]}'
EOF

chmod +x "$mock_bin"/*

export PATH="$mock_bin:$PATH"
export TEST_GRIM_ARGS="$test_dir/grim.args"
export TEST_PKILL_ARGS="$test_dir/pkill.args"

rgb=$(
  "$repo_dir/screen-toolkit/scripts/color-picker.sh" "$test_dir/pixel.png"
)
test "$rgb" = "17 34 51"
test "$(cat "$TEST_GRIM_ARGS")" = "-g 10,20 1x1 -t png $test_dir/pixel.png"

geometry=$(
  "$repo_dir/screen-toolkit/scripts/capture.sh" annotate-window
)
test "$geometry" = "5,10 100x80"
test "$(cat "$TEST_GRIM_ARGS")" = "-g 5,10 100x80 /tmp/screen-toolkit-annotate.png"

"$repo_dir/screen-toolkit/scripts/record.sh" stop gpu-screen-recorder
test "$(cat "$TEST_PKILL_ARGS")" = "-INT -f ^(/.*/)?gpu-screen-recorder"

printf '%s\n' 'screen-toolkit tests: ok'
