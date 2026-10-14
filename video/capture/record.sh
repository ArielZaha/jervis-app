#!/bin/sh
# Record one or more shots, each in its own Electron process:  video/capture/record.sh talk graph ...
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1
mkdir -p video/cache.nosync
for shot in "$@"; do
  env -u ELECTRON_RUN_AS_NODE node_modules/.bin/electron video/capture/record.js "$shot" 2>&1 \
    | grep -v "Security Warning\|security risks\|unsafe-eval\|packaged\|consult\|electronjs.org\|This warning\|Policy set\|tile_manager\|^$\|service_worker_storage"
done
