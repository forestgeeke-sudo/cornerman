#!/usr/bin/env bash
# Install without launching an activity, opening a mirror or injecting input.
set -euo pipefail
TASK_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
REPO_DIR="$(cd -- "$TASK_DIR/../.." && pwd)"
APK="$REPO_DIR/.cache/android-launcher/cornerman-launcher.apk"
DEVICE="${1:-}"
if [[ -z "$DEVICE" ]]; then
  "$HOME/bin/phone-adb" >/dev/null
  DEVICE="$(cat "$HOME/.local/state/phone-adb/endpoint")"
fi
[[ -f "$APK" ]] || { echo 'Build the launcher first with launchers/android/build.sh' >&2; exit 1; }
[[ "$(adb -s "$DEVICE" shell getprop ro.product.model | tr -d '\r')" == 'SM-G991U' ]] || {
  echo 'Expected the authorized Galaxy S21; refusing another device.' >&2; exit 1;
}
BEFORE="$(adb -s "$DEVICE" shell dumpsys window | sed -n '/mCurrentFocus=/p')"
adb -s "$DEVICE" install -r "$APK"
adb -s "$DEVICE" shell cmd package resolve-activity --brief -a android.intent.action.MAIN \
  -c android.intent.category.LAUNCHER dev.forest.cornerman
AFTER="$(adb -s "$DEVICE" shell dumpsys window | sed -n '/mCurrentFocus=/p')"
if [[ "$BEFORE" == "$AFTER" ]]; then
  echo 'Installed Cornerman; foreground window unchanged. No activity was launched.'
else
  echo 'Installed Cornerman. Foreground changed during installation; no screen input or activity launch was performed.'
fi
