@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 安裝打包工具 ...
python -m pip install PySide6 pillow pillow-heif pyinstaller
echo 打包成 exe（約 1-3 分鐘）...
python -m PyInstaller --noconfirm --windowed --onefile --collect-all pillow_heif --version-file version_info.txt --name MultiGridViewer multigrid_viewer.py
echo.
echo 完成！執行檔在 dist\MultiGridViewer.exe
pause
