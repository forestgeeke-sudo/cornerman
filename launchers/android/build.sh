#!/usr/bin/env bash
# Build the tiny, permission-free phone launcher using the existing local SDK.
set -euo pipefail
TASK_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
REPO_DIR="$(cd -- "$TASK_DIR/../.." && pwd)"
TOOLCHAIN="${CORNERMAN_ANDROID_TOOLCHAIN:-$HOME/.local/share/work-hours-toolchain}"
export JAVA_HOME="$TOOLCHAIN/jdk"
export PATH="$JAVA_HOME/bin:$PATH"
SDK_DIR="$TOOLCHAIN/sdk"
TOOLS="$SDK_DIR/build-tools/36.0.0"
ANDROID_JAR="$SDK_DIR/platforms/android-36/android.jar"
BUILD_DIR="$REPO_DIR/.cache/android-launcher"
SIGN_DIR="$HOME/.local/share/cornerman-launcher"
for executable in "$TOOLS/aapt2" "$TOOLS/d8" "$TOOLS/apksigner" "$TOOLS/zipalign" "$JAVA_HOME/bin/javac"; do
  [[ -x "$executable" ]] || { echo "Missing existing tool: $executable" >&2; exit 1; }
done
mkdir -p "$BUILD_DIR/classes" "$BUILD_DIR/dex" "$BUILD_DIR/res/drawable-nodpi"
rsvg-convert -w 512 -h 512 "$REPO_DIR/docs/icon.svg" -o "$BUILD_DIR/res/drawable-nodpi/icon.png"
"$TOOLS/aapt2" compile --dir "$BUILD_DIR/res" -o "$BUILD_DIR/resources.zip"
"$TOOLS/aapt2" link -o "$BUILD_DIR/base.apk" -I "$ANDROID_JAR" --manifest "$TASK_DIR/AndroidManifest.xml" "$BUILD_DIR/resources.zip"
javac -source 8 -target 8 -Xlint:-options -classpath "$ANDROID_JAR" -d "$BUILD_DIR/classes" "$TASK_DIR/src/dev/forest/cornerman/MainActivity.java"
"$TOOLS/d8" --lib "$ANDROID_JAR" --min-api 23 --output "$BUILD_DIR/dex" "$BUILD_DIR/classes/dev/forest/cornerman/MainActivity.class"
python3 - "$BUILD_DIR" <<'PY'
from pathlib import Path
import sys,zipfile
root=Path(sys.argv[1])
with zipfile.ZipFile(root/'base.apk','a') as apk:
    apk.write(root/'dex/classes.dex','classes.dex')
PY
"$TOOLS/zipalign" -f 4 "$BUILD_DIR/base.apk" "$BUILD_DIR/aligned.apk"
umask 077
mkdir -p "$SIGN_DIR"
if [[ ! -f "$SIGN_DIR/signing.p12" ]]; then
  python3 - "$SIGN_DIR/password" <<'PY'
from pathlib import Path
import secrets,sys
Path(sys.argv[1]).write_text(secrets.token_urlsafe(32))
PY
  keytool -genkeypair -keystore "$SIGN_DIR/signing.p12" -storetype PKCS12 -alias cornerman \
    -storepass:file "$SIGN_DIR/password" -keypass:file "$SIGN_DIR/password" \
    -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=Cornerman Personal Launcher' >/dev/null 2>&1
fi
"$TOOLS/apksigner" sign --ks "$SIGN_DIR/signing.p12" --ks-key-alias cornerman --ks-pass "file:$SIGN_DIR/password" \
  --out "$BUILD_DIR/cornerman-launcher.apk" "$BUILD_DIR/aligned.apk"
"$TOOLS/apksigner" verify --verbose "$BUILD_DIR/cornerman-launcher.apk"
"$TOOLS/aapt2" dump badging "$BUILD_DIR/cornerman-launcher.apk" | sed -n '1,10p'
echo "Ready: $BUILD_DIR/cornerman-launcher.apk"
