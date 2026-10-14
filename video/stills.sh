#!/bin/sh
# Renders single moments of the film and tiles them into one picture, for review:  video/stills.sh 3.5 7.5 11.4 ...
# (FILM=showcase video/stills.sh ...  for the showcase)
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"; cd "$ROOT"
FF="$(ls "$HERE"/tools.nosync/py/imageio_ffmpeg/binaries/ffmpeg* | head -1)"
LIST=$(echo "$@" | tr ' ' ',')
env -u ELECTRON_RUN_AS_NODE node_modules/.bin/electron video/render.js --film "${FILM:-scenes}" --stills "$LIST" 2>&1 | grep "\[film\]\|Error" | head -20
i=0; ARGS=""
for t in "$@"; do f=$(printf "$HERE/cache.nosync/stills/film_%.2f.jpg" "$t"); ARGS="$ARGS -i $f"; i=$((i+1)); done
COLS=${COLS:-2}; ROWS=$(( (i + COLS - 1) / COLS ))
"$FF" -y -loglevel error $ARGS -filter_complex "concat=n=$i:v=1:a=0,scale=${W:-960}:-1,tile=${COLS}x${ROWS}:padding=6:color=0x303030" -frames:v 1 -q:v 3 "$HERE/cache.nosync/review.jpg" && echo "$HERE/cache.nosync/review.jpg"
