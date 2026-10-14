#!/bin/sh
# A contact sheet of a clip, for checking footage at a glance:  video/sheet.sh <file.mp4> [every-n-frames] [columns]
HERE="$(cd "$(dirname "$0")" && pwd)"
FF="$(ls "$HERE"/tools.nosync/py/imageio_ffmpeg/binaries/ffmpeg* | head -1)"
IN="$1"; N="${2:-45}"; COLS="${3:-4}"; W="${4:-480}"
OUT="$HERE/cache.nosync/sheet_$(basename "$IN" .mp4).jpg"
"$FF" -y -loglevel error -i "$IN" -vf "select=not(mod(n\,$N)),scale=$W:-1,tile=${COLS}x${5:-4}:padding=4:color=0x202020" -frames:v 1 -q:v 4 "$OUT" && echo "$OUT"
