#!/usr/bin/env bash
# annotate.sh <image> [save-path] — open the editor with its full UI visible.
set -euo pipefail

image=${1:?Missing image path}
output=${2:-}

if command -v satty >/dev/null 2>&1; then
    script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    exec /usr/bin/python3 "$script_dir/popup-editor.py" "$image" "$output"
elif command -v swappy >/dev/null 2>&1; then
    exec swappy -f "$image"
elif command -v gimp >/dev/null 2>&1; then
    exec gimp "$image"
else
    echo 'ERROR: no annotation editor found (install satty, swappy or gimp)' >&2
    exit 3
fi
