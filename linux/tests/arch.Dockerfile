FROM archlinux:base
RUN pacman -Syu --noconfirm && pacman -S --noconfirm --needed \
    niri mesa xorg-server-xvfb xorg-xauth xdotool libxcursor libxrandr libxi libxinerama \
    dbus python pyside6 qt6-wayland espeak-ng
COPY packages/*.pkg.tar.zst /tmp/
RUN pacman -U --noconfirm /tmp/*.pkg.tar.zst
COPY linux/tests/niri_smoke.sh linux/tests/niri_inside.sh linux/tests/niri_integration.py /checks/
COPY linux/reverb_linux /checks/source/reverb_linux
CMD ["bash", "/checks/niri_smoke.sh"]
