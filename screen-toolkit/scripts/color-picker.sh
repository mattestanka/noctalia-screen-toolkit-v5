#!/usr/bin/env bash
# color-picker.sh <output-png>
# Picks a color from the screen and prints "R G B" to stdout.
#
# Select the point first, then wait for slurp's layer surface and software
# cursor frame to disappear before asking grim for the pixel. This mirrors
# wl-color-picker and avoids sampling the cursor/overlay colour on NVIDIA.
FILE="$1"
[ -z "$FILE" ] && exit 1

command -v slurp >/dev/null 2>&1 || exit 1
command -v grim >/dev/null 2>&1 || exit 1

MAGICK=""
command -v magick >/dev/null 2>&1 && MAGICK="magick"
[ -z "$MAGICK" ] && command -v convert >/dev/null 2>&1 && MAGICK="convert"
[ -z "$MAGICK" ] && exit 1

# Transparent point selector: slurp emits "X,Y 1x1".
POS=$(slurp -b 00000000 -p 2>/dev/null) || exit 1
[ -z "$POS" ] && exit 1

# Let the compositor commit a clean frame after the selector disappears.
sleep 0.4

grim -g "$POS" -t png "$FILE" 2>/dev/null || exit 1

read -r R G B < <("$MAGICK" "$FILE" -alpha off \
    -format '%[fx:int(255*p{0,0}.r)] %[fx:int(255*p{0,0}.g)] %[fx:int(255*p{0,0}.b)]' \
    info:- 2>/dev/null)

{ [ -z "$R" ] || [ -z "$G" ] || [ -z "$B" ]; } && exit 1
printf '%d %d %d\n' "$R" "$G" "$B"
