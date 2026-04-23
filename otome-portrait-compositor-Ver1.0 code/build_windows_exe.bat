@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt pyinstaller
py -3 -m PyInstaller --clean otome_tlg_json_sinfo_compositor.spec

echo.
echo Build finished.
echo Output: dist\OtomePortraitCompositor_Ver1.0\
pause
