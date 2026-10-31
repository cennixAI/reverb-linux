#!/usr/bin/env bash
set -euo pipefail
cd /tmp
reverb --check-model
reverb --diagnose
espeak-ng -v en-us -s 140 -w /tmp/sample.wav "Please send the report to the team tomorrow morning."
reverb --transcribe-file /tmp/sample.wav > /tmp/transcript.txt
python -c 'from pathlib import Path; t=Path("/tmp/transcript.txt").read_text().lower(); assert "report" in t and "tomorrow" in t, t'
reverb --niri-config > /tmp/reverb-config.kdl
niri validate --config /tmp/reverb-config.kdl
export XDG_RUNTIME_DIR
XDG_RUNTIME_DIR="$(mktemp -d)"
chmod 700 "$XDG_RUNTIME_DIR"
export XDG_CURRENT_DESKTOP=niri XDG_SESSION_TYPE=wayland LIBGL_ALWAYS_SOFTWARE=1
cat > /tmp/niri-test.kdl <<'EOF'
spawn-at-startup "/bin/bash" "/checks/niri_inside.sh"
binds {
    Ctrl+Alt+Space repeat=false { spawn "/usr/bin/touch" "/tmp/reverb-shortcut"; }
}
EOF
python -c 'import sys; sys.path.insert(0, "/checks/source"); from reverb_linux.niri import window_rules; print(window_rules())' >> /tmp/niri-test.kdl
cleanup() {
  kill "${compositor_pid:-}" "${xvfb_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT
Xvfb :99 -screen 0 1280x800x24 > /tmp/xvfb.log 2>&1 &
xvfb_pid=$!
sleep 1
DISPLAY=:99 dbus-run-session -- niri --config /tmp/niri-test.kdl > /tmp/niri.log 2>&1 &
compositor_pid=$!
for attempt in $(seq 1 60); do
  if [[ -f /tmp/reverb-niri-ok ]]; then
    echo "Arch: offline recognition, native Wayland UI, Niri shortcut and typing passed."
    exit 0
  fi
  if [[ -f /tmp/reverb-niri-failed ]] || ! kill -0 "$compositor_pid" 2>/dev/null; then
    break
  fi
  sleep 1
done
cat /tmp/niri.log
cat /tmp/reverb-niri-inside.log 2>/dev/null || true
exit 1
