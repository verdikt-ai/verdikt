#!/usr/bin/env bash
# run_suite.sh ATTEMPT_DIR [extra runner args...]: restart the read-only emulator instances
# from the set-up base image, then run one worker per instance until the suite is done.
set -euo pipefail
ATTEMPT="$1"; shift
SDK=${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}
ADB=$SDK/platform-tools/adb
PY=${AW_PY:?set AW_PY to the python of your android_world environment}
PORTS="${PORTS:-5580 5582 5584}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$ATTEMPT"
for p in $PORTS; do $ADB -s emulator-$p emu kill >/dev/null 2>&1 || true; done
sleep 8
for p in $PORTS; do
  nohup $SDK/emulator/emulator -avd Verdikt_AndroidWorld_Pilot -port $p -grpc $((p+3000)) -read-only \
    -no-snapshot -no-window -no-audio -no-boot-anim -gpu host > "$ATTEMPT/emu$p.log" 2>&1 &
  sleep 2
done
for p in $PORTS; do
  until [ "$($ADB -s emulator-$p shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; do sleep 3; done
done
git -C "$HERE" rev-parse HEAD > "$ATTEMPT/verdikt-commit"
cp "$HERE/benchmarks/androidworld/prompt.md" "$ATTEMPT/prompt-snapshot.md"
pids=()
for p in $PORTS; do
  # Official data helpers stage files in the host temp dir under fixed names; parallel
  # workers must not share it.
  mkdir -p "$ATTEMPT/tmp-$p"
  (cd "$HERE" && TMPDIR="$ATTEMPT/tmp-$p" GRPC_VERBOSITY=ERROR PYTHONPATH=.:src $PY -m benchmarks.androidworld.runner --attempt "$ATTEMPT" \
     --console-port $p --mcp-port $((p+2220)) "$@" > "$ATTEMPT/stdout-$p.log" 2>&1) &
  pids+=($!)
  sleep 15
done
wait "${pids[@]}"
(cd "$HERE" && python3 -m benchmarks.androidworld.summarize "$ATTEMPT" > "$ATTEMPT/summary.txt")
