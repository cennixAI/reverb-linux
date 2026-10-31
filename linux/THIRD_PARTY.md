# Linux distribution notices

Reverb source is MIT licensed; see the included LICENSE. The Linux speech model is
separate from the Mac Core ML weights. This installer contains unmodified upstream
components and their license files wherever supplied by the upstream archives
and Python distributions.

* Parakeet TDT 0.6B v2, Copyright NVIDIA Corporation, CC BY 4.0. Model and source:
  https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2
  License: https://creativecommons.org/licenses/by/4.0/legalcode.en
  This distribution uses the upstream ONNX int8 conversion without further changes.
  Conversion: https://github.com/k2-fsa/sherpa-onnx/tree/master/scripts/nemo/parakeet-tdt-0.6b-v2
* sherpa-onnx 1.13.8, Apache 2.0, with third-party notices and sources:
  https://github.com/k2-fsa/sherpa-onnx/tree/v1.13.8
* ONNX Runtime, MIT: https://github.com/microsoft/onnxruntime
* PySide6 / Shiboken6 / Qt 6.8.3, LGPL 3.0 (and applicable third-party notices):
  https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.8.3
  https://download.qt.io/archive/qt/6.8/6.8.3/single/
  Shared libraries are included without modification and may be replaced in
  /opt/reverb/_internal. Reverb imposes no restriction on debugging modifications
  to these LGPL libraries. Qt source and license notices are distributed upstream.
* NumPy, BSD 3-Clause: https://github.com/numpy/numpy/tree/v2.2.6
* python-sounddevice, MIT: https://github.com/spatialaudio/python-sounddevice
* python-xlib, LGPL 2.1 or later: https://github.com/python-xlib/python-xlib
* dbus-next, MIT: https://github.com/altdesktop/python-dbus-next
* Python, PSF license: https://docs.python.org/3/license.html
* PyInstaller, GPL with a bootloader exception permitting bundled applications:
  https://pyinstaller.org/en/stable/license.html

The downloaded model is pinned by SHA-256 in models.json. The runtime does not
download weights or executable code, and has no network client.
