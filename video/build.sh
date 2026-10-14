#!/bin/sh
# Builds a film from the recorded footage.
#
#   video/build.sh trailer           the 70-second trailer    -> out/Jarvis_Trailer_Final.mp4
#   video/build.sh trailer sound     only its soundtrack and final mix (the picture is not rendered again)
#   video/build.sh trailer voice     speak the narration again first (after changing a line or the voice), then the mix
#   video/build.sh showcase          the 90-second showcase   -> out/Jarvis_Showcase_Final.mp4
#   video/build.sh showcase sound    only its soundtrack and final mix
#   video/build.sh                   the first, longer film   -> out/Jarvis_Product_Demo.mp4
#   video/build.sh sound | voice     the first film: only the sound / speak its narration first (see narration.md)
#
# Every result is 1920x1080, 30 fps, H.264 + AAC, with a small preview next to it.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"
FF="${FFMPEG:-$(ls "$HERE"/tools.nosync/py/imageio_ffmpeg/binaries/ffmpeg* 2>/dev/null | head -1)}"
[ -x "$FF" ] || FF="$(command -v ffmpeg)"
[ -x "$FF" ] || { echo "ffmpeg not found. Run: venv/bin/python -m pip install --target video/tools.nosync/py imageio-ffmpeg"; exit 1; }
PY="$ROOT/venv/bin/python"
ELECTRON="env -u ELECTRON_RUN_AS_NODE $ROOT/node_modules/.bin/electron"
quiet() { grep -v "Security Warning\|security risks\|unsafe-eval\|packaged\|consult\|electronjs.org\|This warning\|Policy set\|tile_manager\|^$" || true; }
mkdir -p "$HERE/out" "$HERE/cache.nosync" "$HERE/assets/audio"

if [ "$1" = "trailer" ]; then
  FILM=trailer; MODE="$2"; AUDIO="$HERE/assets/audio/trailer"; PICTURE_FILE="$HERE/cache.nosync/film.trailer.mp4"; NAME=Jarvis_Trailer_Final
elif [ "$1" = "showcase" ]; then
  FILM=showcase; MODE="$2"; AUDIO="$HERE/assets/audio/showcase"; PICTURE_FILE="$HERE/cache.nosync/film.showcase.mp4"; NAME=Jarvis_Showcase_Final
else
  FILM=scenes; MODE="$1"; AUDIO="$HERE/assets/audio"; PICTURE_FILE="$HERE/cache.nosync/film.mp4"; NAME=Jarvis_Product_Demo
fi

if [ "$FILM" = "trailer" ]; then   # the narrator first: the edit is timed to the real length of each line
  if [ "$MODE" = "voice" ]; then "$PY" video/audio/narrator.py --all; else "$PY" video/audio/narrator.py; fi
fi
$ELECTRON video/render.js --film "$FILM" --cues 2>&1 | quiet
if [ "$FILM" != "scenes" ]; then
  "$PY" video/audio/score.py "$FILM"
  "$PY" video/audio/subtitles.py "$FILM"
else
  if [ "$MODE" = "voice" ]; then "$PY" video/audio/tts.py; fi
  "$PY" video/audio/voice.py
  "$PY" video/audio/score.py
fi
# The picture is rendered in 15-second pieces, each by a fresh process and each checked for its frame count (and done
# again if short), then joined without re-encoding. A long single render can die quietly on a computer that is short
# of memory, and would leave a film that simply ends early.
render_picture() {
  CUES="$HERE/audio/cues.json"; [ "$FILM" = "scenes" ] || CUES="$HERE/audio/cues.$FILM.json"
  TOTAL=$("$PY" -c "import json,sys; print(round(json.load(open(sys.argv[1]))['duration'] * 30))" "$CUES")
  LIST="$HERE/cache.nosync/parts.$FILM.txt"; : > "$LIST"
  FROM=0; N=0
  while [ "$FROM" -lt "$TOTAL" ]; do
    TO=$((FROM + 450)); [ "$TO" -gt "$TOTAL" ] && TO=$TOTAL
    PART="$HERE/cache.nosync/part.$FILM.$N.mp4"
    for TRY in 1 2 3 4; do
      $ELECTRON video/render.js --film "$FILM" --from "$(awk "BEGIN{print $FROM/30}")" --to "$(awk "BEGIN{print $TO/30}")" --out "$PART" 2>&1 | quiet | grep -v "^frame " || true
      GOT=$("$FF" -hide_banner -i "$PART" -map 0:v -c copy -f null - 2>&1 | sed -n 's/.*frame= *\([0-9]*\).*/\1/p' | tail -1)
      [ "$GOT" = "$((TO - FROM))" ] && break
      echo "piece $N came out with ${GOT:-0} of $((TO - FROM)) frames: rendering it again (try $TRY)"
      [ "$TRY" = 4 ] && { echo "The picture could not be rendered."; exit 1; }
    done
    echo "piece $N: frames $FROM-$TO"
    echo "file '$PART'" >> "$LIST"
    FROM=$TO; N=$((N + 1))
  done
  "$FF" -y -loglevel error -f concat -safe 0 -i "$LIST" -c copy -movflags +faststart "$PICTURE_FILE"
  rm -f "$HERE"/cache.nosync/part."$FILM".*.mp4 "$LIST"
}
if [ "$MODE" != "sound" ] && { [ "$MODE" != "voice" ] || [ "$FILM" = "trailer" ]; }; then   # a new voice re-times the trailer: render it again
  render_picture
fi
[ -f "$PICTURE_FILE" ] || { echo "No rendered picture yet: run this without 'sound'."; exit 1; }

OUT="$HERE/out/$NAME.mp4"
# The mix: music + effects + whoever speaks (Jarvis's own replies in the showcase; a narrator, if recorded, in the first
# film), brought to -15 LUFS with one fixed gain (no automatic levelling), under a safety limiter.
if [ "$FILM" = "trailer" ]; then
  set -- -i "$AUDIO/music.wav" -i "$AUDIO/sfx.wav" -i "$AUDIO/jarvis.wav" -i "$AUDIO/narrator.wav"
  PICTURE=4
  MIX="[0:a][1:a][2:a][3:a]amix=inputs=4:normalize=0:weights='1 1 1.2 1.3'"
elif [ "$FILM" = "showcase" ] && [ -f "$AUDIO/jarvis.wav" ]; then
  set -- -i "$AUDIO/music.wav" -i "$AUDIO/sfx.wav" -i "$AUDIO/jarvis.wav"
  PICTURE=3
  MIX="[0:a][1:a][2:a]amix=inputs=3:normalize=0:weights='1 1 1.25'"
elif [ "$FILM" = "scenes" ] && [ -f "$AUDIO/voice.wav" ]; then
  set -- -i "$AUDIO/music.wav" -i "$AUDIO/sfx.wav" -i "$AUDIO/voice.wav"
  PICTURE=3
  MIX="[2:a]aformat=channel_layouts=stereo,asplit=2[v1][v2];[0:a][v1]sidechaincompress=threshold=0.02:ratio=6:attack=40:release=700:makeup=1[m];[m][1:a][v2]amix=inputs=3:normalize=0:weights='1 0.9 1.5'"
else
  set -- -i "$AUDIO/music.wav" -i "$AUDIO/sfx.wav"
  PICTURE=2
  MIX="[0:a][1:a]amix=inputs=2:normalize=0"
fi
LOUD=$("$FF" -hide_banner "$@" -filter_complex "$MIX,ebur128" -f null - 2>&1 | awk '$1=="I:"{v=$2} END{print v}')
GAIN=$(awk "BEGIN{printf \"%.2f\", -15.0 - ($LOUD)}")
echo "the mix measures $LOUD LUFS: applying $GAIN dB"
"$FF" -y -loglevel error "$@" -i "$PICTURE_FILE" \
  -filter_complex "$MIX,volume=${GAIN}dB,alimiter=limit=0.84:level=false[a]" \
  -map "$PICTURE:v" -map "[a]" -c:v copy -c:a aac -b:a 256k -ar 48000 -shortest -movflags +faststart "$OUT"
"$FF" -y -loglevel error -i "$OUT" -vf scale=960:540:flags=lanczos -c:v libx264 -preset medium -crf 24 -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart "$HERE/out/${NAME}_preview.mp4"
if [ "$FILM" = "trailer" ]; then   # the same file under the product's older spelling, as it was asked for
  ln -sf "$NAME.mp4" "$HERE/out/Jervis_Trailer_Final.mp4"
fi
ls -la "$HERE/out"
