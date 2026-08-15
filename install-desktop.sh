#!/usr/bin/env bash
# Install Cornerman as a desktop app: its own launcher, its own window, its
# own icon. Chrome runs it in app mode so there's no tab strip or URL bar.
#
#   ./install-desktop.sh https://<you>.github.io/cornerman/
#
# Re-run any time to point it somewhere else.

set -euo pipefail

URL="${1:-}"
if [[ -z "$URL" ]]; then
  echo "usage: $0 <url-of-the-published-app>" >&2
  echo "example: $0 https://forestgeeke-sudo.github.io/cornerman/" >&2
  exit 1
fi

APP_ID="cornerman"
ICON_SRC="$(cd "$(dirname "$0")" && pwd)/docs/icon.svg"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
DESKTOP="$HOME/.local/share/applications/${APP_ID}.desktop"

BROWSER=""
for b in google-chrome-stable google-chrome chromium chromium-browser brave-browser; do
  if command -v "$b" >/dev/null 2>&1; then BROWSER="$b"; break; fi
done
if [[ -z "$BROWSER" ]]; then
  echo "No Chrome/Chromium found; can't create an app window." >&2
  exit 1
fi

# Same persistent split-tunnel wrap as Stremio/Steam: Mullvad's GUI
# does not remember per-app excludes, so launch via mullvad-exclude.
EXCLUDE=""
if command -v mullvad-exclude >/dev/null 2>&1; then
  EXCLUDE="mullvad-exclude "
fi

BROWSER_PATH="$(command -v "$BROWSER")"
LIBEXEC="$HOME/.local/libexec"
OPENER="$LIBEXEC/${APP_ID}-open-url"
OPEN_DESKTOP="$HOME/.local/share/applications/${APP_ID}-open.desktop"

mkdir -p "$ICON_DIR" "$(dirname "$DESKTOP")" "$LIBEXEC"
cp -f "$ICON_SRC" "$ICON_DIR/${APP_ID}.svg"

# --app windows cannot open a normal browser tab. On Fedora/Wayland a JS
# popup is a few pixels off-screen and the portal then offers Calendar.
# This handler is what "Add to calendar" / watch chips actually invoke.
cat > "$OPENER" <<PY
#!/usr/bin/env python3
import subprocess, sys, urllib.parse
BROWSER = ${BROWSER_PATH@Q}
raw = sys.argv[1] if len(sys.argv) > 1 else ""
parsed = urllib.parse.urlparse(raw)
u = (urllib.parse.parse_qs(parsed.query).get("u") or [""])[0]
if not u:
    sys.exit(1)
subprocess.Popen([BROWSER, u], start_new_session=True)
PY
chmod +x "$OPENER"

cat > "$OPEN_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Cornerman Link Opener
Exec=${OPENER} %u
NoDisplay=true
StartupNotify=false
MimeType=x-scheme-handler/x-cornerman;
EOF

xdg-mime default "${APP_ID}-open.desktop" x-scheme-handler/x-cornerman 2>/dev/null || true

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Cornerman
GenericName=Fight Schedule
Comment=Upcoming MMA and boxing cards, and where to watch them
Exec=${EXCLUDE}${BROWSER} --app=${URL} --class=${APP_ID} --name=${APP_ID}
Icon=${APP_ID}
Terminal=false
Categories=Network;Sports;News;
Keywords=MMA;UFC;boxing;fights;schedule;
StartupWMClass=${APP_ID}
EOF

chmod +x "$DESKTOP"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Installed. Look for 'Cornerman' in your app launcher."
echo "  url:     $URL"
echo "  browser: $BROWSER"
echo "  entry:   $DESKTOP"
