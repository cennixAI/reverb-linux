#!/usr/bin/env bash
# Package the same frozen Linux build for Pond/Arch; no system Python dependency.
set -euo pipefail
cd "$(dirname "$0")"
version="${1:-0.3.1.linux1}"
if [[ ! "$version" =~ ^[0-9][a-zA-Z0-9.+]*$ ]]; then
  echo "Invalid Arch package version" >&2
  exit 1
fi
if [[ ! -x dist/reverb/reverb ]]; then
  echo "Build the Linux binary with package.sh first." >&2
  exit 1
fi
mkdir -p dist/packages
package="dist/packages/reverb-${version}-1-x86_64.pkg.tar.zst"
if [[ -e "$package" ]]; then
  echo "Refusing to overwrite existing installer: $package" >&2
  exit 1
fi
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/opt/reverb" "$stage/usr/bin" "$stage/usr/share/applications" \
         "$stage/usr/share/licenses/reverb" "$stage/usr/share/doc/reverb/sources"
cp -a dist/reverb/. "$stage/opt/reverb/"
ln -s /opt/reverb/reverb "$stage/usr/bin/reverb"
cp ai.cennix.Reverb.desktop "$stage/usr/share/applications/"
cp ../LICENSE THIRD_PARTY.md "$stage/usr/share/licenses/reverb/"
cp -a licenses "$stage/usr/share/licenses/reverb/"
cp README.md "$stage/usr/share/doc/reverb/"
cp -a reverb_linux main.py requirements.txt models.json download_models.py package.sh package-arch.sh \
   "$stage/usr/share/doc/reverb/sources/"
find "$stage/usr/share/doc/reverb/sources" -name __pycache__ -prune -exec rm -rf {} +
cat > "$stage/.PKGINFO" <<EOF
pkgname = reverb
pkgbase = reverb
pkgver = ${version}-1
pkgdesc = Offline CPU dictation with bundled Parakeet recognition
url = https://getreverb.app
builddate = $(date +%s)
packager = Cennix
size = $(du -sk "$stage" | awk '{print $1 * 1024}')
arch = x86_64
license = MIT
license = CC-BY-4.0
license = LGPL-3.0-only
depend = glibc
depend = portaudio
depend = fontconfig
depend = libxcb
depend = xcb-util-cursor
depend = xcb-util-wm
depend = xcb-util-image
depend = xcb-util-keysyms
depend = xcb-util-renderutil
depend = libxkbcommon-x11
depend = libglvnd
depend = dbus
depend = wayland
depend = wtype
depend = wl-clipboard
optdepend = xdg-desktop-portal: keyboard approval on GNOME and KDE Wayland
EOF
bsdtar --zstd --uid 0 --gid 0 -cf "$package" -C "$stage" .PKGINFO opt usr
echo "Built $package"
