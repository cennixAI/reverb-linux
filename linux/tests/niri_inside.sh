#!/usr/bin/env bash
set -euo pipefail
exec > /tmp/reverb-niri-inside.log 2>&1
trap 'touch /tmp/reverb-niri-failed' ERR
export QT_QPA_PLATFORM=wayland
unset DISPLAY
reverb --smoke-ui
python /checks/niri_integration.py
touch /tmp/reverb-niri-ok
