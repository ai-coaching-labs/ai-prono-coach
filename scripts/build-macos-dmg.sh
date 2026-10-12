#!/usr/bin/env bash
set -euo pipefail
PRONO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$(uname -s)" == "Darwin" ]] || { echo 'Construction sur macOS requise.' >&2; exit 1; }
mkdir -p "$PRONO_ROOT/dist"
PRONO_VERSION="$(python3 -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$PRONO_ROOT/pyproject.toml")"
PRONO_BUILD="$(mktemp -d "$PRONO_ROOT/dist/macos-XXXXXXXX")"
PRONO_APP="$PRONO_BUILD/AI Prono Coach.app"
mkdir -p "$PRONO_APP/Contents/MacOS" "$PRONO_APP/Contents/Resources" "$PRONO_BUILD/payload/config"
swift "$PRONO_ROOT/macos/BuildIcon.swift" "$PRONO_BUILD/AppIcon.iconset"
iconutil -c icns "$PRONO_BUILD/AppIcon.iconset" -o "$PRONO_APP/Contents/Resources/AppIcon.icns"
# Liste explicite : aucun historique, journal, profil, clé ou configuration personnelle.
for name in src scripts agents skills templates docs; do
    ditto "$PRONO_ROOT/$name" "$PRONO_BUILD/payload/$name"
done
cp "$PRONO_ROOT/config/workspace.toml" "$PRONO_BUILD/payload/config/workspace.toml"
cp "$PRONO_ROOT/AGENTS.md" "$PRONO_ROOT/README.md" "$PRONO_ROOT/install.sh" "$PRONO_ROOT/pyproject.toml" "$PRONO_BUILD/payload/"
find "$PRONO_BUILD/payload" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$PRONO_BUILD/payload" -type f \( -name '.DS_Store' -o -name '._*' \) -delete
COPYFILE_DISABLE=1 tar -czf "$PRONO_APP/Contents/Resources/engine.tar.gz" -C "$PRONO_BUILD/payload" .
PRONO_HASH="$(shasum -a 256 "$PRONO_APP/Contents/Resources/engine.tar.gz" | awk '{print $1}')"
for arch in arm64 x86_64; do
    swiftc -swift-version 5 -O -parse-as-library -target "$arch-apple-macos13.0" -framework SwiftUI -framework AppKit -framework WebKit "$PRONO_ROOT/macos/PronoCoach.swift" -o "$PRONO_BUILD/app-$arch"
done
lipo -create "$PRONO_BUILD/app-arm64" "$PRONO_BUILD/app-x86_64" -output "$PRONO_APP/Contents/MacOS/AI Prono Coach"
python3 - "$PRONO_APP/Contents/Info.plist" "$PRONO_HASH" "$PRONO_VERSION" <<'PY'
import plistlib,sys
payload={'CFBundleName':'AI Prono Coach','CFBundleDisplayName':'AI Prono Coach','CFBundleIdentifier':'local.ai-prono-coach.desktop','CFBundleExecutable':'AI Prono Coach','CFBundlePackageType':'APPL','CFBundleIconFile':'AppIcon','CFBundleShortVersionString':sys.argv[3],'CFBundleVersion':'1','LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'LSApplicationCategoryType':'public.app-category.sports','PronoEngineBuild':sys.argv[2],'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
with open(sys.argv[1],'wb') as f:plistlib.dump(payload,f)
PY
codesign --force --deep --sign "${PRONO_CODESIGN_IDENTITY:--}" "$PRONO_APP"
mkdir -p "$PRONO_BUILD/image"
ditto "$PRONO_APP" "$PRONO_BUILD/image/AI Prono Coach.app"
ln -s /Applications "$PRONO_BUILD/image/Applications"
PRONO_DMG="$PRONO_ROOT/dist/AI-Prono-Coach-$PRONO_VERSION.dmg"
if [[ -e "$PRONO_DMG" ]]; then mv "$PRONO_DMG" "$PRONO_DMG.$(date +%Y%m%d%H%M%S).previous"; fi
hdiutil create -volname 'AI Prono Coach' -srcfolder "$PRONO_BUILD/image" -format UDZO "$PRONO_DMG" >/dev/null
codesign --force --sign "${PRONO_CODESIGN_IDENTITY:--}" "$PRONO_DMG"
if [[ -n "${PRONO_NOTARY_PROFILE:-}" ]]; then
    xcrun notarytool submit "$PRONO_DMG" --keychain-profile "$PRONO_NOTARY_PROFILE" --wait
    xcrun stapler staple "$PRONO_DMG"
fi
# Ces copies temporaires appartiennent uniquement à cette construction réussie.
# L’app finale, le DMG et les constructions antérieures sont conservés.
rm -rf "$PRONO_BUILD/payload" "$PRONO_BUILD/image" "$PRONO_BUILD/AppIcon.iconset"
rm -f "$PRONO_BUILD/app-arm64" "$PRONO_BUILD/app-x86_64"
printf 'Copies temporaires de cette construction nettoyées.\n'
printf 'DMG prêt : %s\nApp : %s\n' "$PRONO_DMG" "$PRONO_APP"
