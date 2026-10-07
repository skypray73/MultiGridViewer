@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "import PySide6, pillow_heif" 2>nul || (
  echo 第一次執行：安裝 PySide6 ...
  python -m pip install PySide6 pillow pillow-heif
)
start "" pythonw multigrid_viewer.py %*
