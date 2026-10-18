@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1
python build_portable.py
if errorlevel 1 exit /b 1
echo 完成！請完整解壓縮 dist\MultiGridViewer-Portable-v1.2.0.zip
pause