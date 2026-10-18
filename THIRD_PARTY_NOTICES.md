# Third-party components

MultiGrid Viewer remains MIT licensed. Its portable ZIP keeps the following
unmodified libraries as external files in `_internal`; do not remove this folder.
The actual Python package versions are recorded in `VERSIONS.txt`.

- Qt / PySide6 / Shiboken: LGPL-3.0 open-source libraries. Project and source:
  https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://code.qt.io/cgit/qt/.
  Licensing: https://doc.qt.io/qt-6/licensing.html.
- Qt Multimedia's FFmpeg backend uses separate `avcodec`, `avformat`, `avutil`,
  `swresample`, and `swscale` DLLs supplied by the PySide6 Windows wheel.
  These are not embedded in `MultiGridViewer.exe`; an additional `ffmpeg.exe`
  command-line program is not required for playback.
  FFmpeg source: https://git.ffmpeg.org/ffmpeg.git.
  Qt's third-party component/license listing:
  https://doc.qt.io/qt-6/qtmultimedia-index.html#licenses-and-attributions.
- Pillow: MIT-CMU. Source: https://github.com/python-pillow/Pillow.
- pillow-heif / libheif: BSD-3-Clause / LGPL-3.0, plus the codecs listed in the
  distribution's notices. Source: https://github.com/bigcat88/pillow_heif and
  https://github.com/strukturag/libheif.
- Python: PSF license. Source: https://www.python.org/downloads/source/.

Package-provided license files are copied into `licenses/` in the portable ZIP.
External shared libraries may be replaced with compatible builds under their
respective license terms. This application imposes no restriction on reverse
engineering needed to debug modifications to those libraries.
