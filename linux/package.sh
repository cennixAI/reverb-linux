#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
version="${1:-0.3.1~linux1}"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo "Build this package on Linux x86_64 (or run the Linux installer GitHub workflow)." >&2
  exit 1
fi
if [[ ! "$version" =~ ^[0-9][a-zA-Z0-9.+~]*$ ]]; then
  echo "Invalid package version" >&2
  exit 1
fi
mkdir -p dist/packages
package="dist/packages/Reverb-${version}-linux-x86_64.deb"
arch_version="${version//\~/.}"
arch_package="dist/packages/reverb-${arch_version}-1-x86_64.pkg.tar.zst"
for artifact in "$package" "$arch_package"; do
  if [[ -e "$artifact" ]]; then
    echo "Refusing to overwrite existing installer: $artifact" >&2
    exit 1
  fi
done
python3 download_models.py
python3 -m PyInstaller --noconfirm --clean --onedir --name reverb \
  --collect-all sherpa_onnx --collect-all sounddevice \
  --collect-submodules Xlib --collect-submodules dbus_next \
  --copy-metadata sherpa-onnx --copy-metadata sherpa-onnx-core \
  --copy-metadata PySide6-Essentials --copy-metadata shiboken6 --copy-metadata numpy \
  --copy-metadata sounddevice --copy-metadata python-xlib --copy-metadata dbus-next \
  --add-data 'models:models' --add-data 'models.json:.' \
  --add-data '../LICENSE:.' --add-data '../NOTICE:.' \
  --add-data 'licenses:linux-licenses' --add-data 'THIRD_PARTY.md:.' main.py
dist/reverb/reverb --check-model
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/opt/reverb" "$stage/usr/bin" "$stage/usr/share/applications" "$stage/DEBIAN" "$stage/usr/share/doc/reverb"
cp -a dist/reverb/. "$stage/opt/reverb/"
ln -s /opt/reverb/reverb "$stage/usr/bin/reverb"
cp ai.cennix.Reverb.desktop "$stage/usr/share/applications/"
cp THIRD_PARTY.md "$stage/usr/share/doc/reverb/copyright"
cp -a licenses "$stage/usr/share/doc/reverb/licenses"
mkdir -p "$stage/usr/share/doc/reverb/sources"
cp -a reverb_linux main.py requirements.txt models.json download_models.py package.sh package-arch.sh "$stage/usr/share/doc/reverb/sources/"
find "$stage/usr/share/doc/reverb/sources" -name __pycache__ -prune -exec rm -rf {} +
cat > "$stage/DEBIAN/control" <<EOF
Package: reverb
Version: $version
Section: sound
Priority: optional
Architecture: amd64
Maintainer: cennixAI <support@cennix.ai>
Depends: libportaudio2, libfontconfig1, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-xinerama0, libxcb-xkb1, libxcb-xinput0, libxcb-shape0, libxcb-randr0, libxcb-xfixes0, libxkbcommon-x11-0, libegl1, libgl1, libdbus-1-3
Recommends: xdg-desktop-portal
Installed-Size: $(du -sk "$stage/opt/reverb" | cut -f1)
Description: Offline dictation
 Press Ctrl+Alt+Space, speak, and press it again: your words are typed where
 your cursor is. Speech is recognized on this computer with the bundled
 Parakeet model. No account, no cloud, no first-launch download.
EOF
dpkg-deb --root-owner-group -Zxz -z3 --build "$stage" "$package"
bash package-arch.sh "$arch_version"
(cd dist/packages && sha256sum "$(basename "$package")" "$(basename "$arch_package")" > SHA256SUMS.txt)
echo "Built $package"
