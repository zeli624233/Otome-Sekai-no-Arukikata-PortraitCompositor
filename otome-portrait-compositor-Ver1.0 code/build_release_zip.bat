@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
call build_windows_exe.bat
if not exist dist\OtomePortraitCompositor_Ver1.0 goto :eof

set RELEASE_DIR=release\オトメ世界の歩き方_立绘合成器_Ver1.0_Windows_x64
if exist "%RELEASE_DIR%" rmdir /s /q "%RELEASE_DIR%"
mkdir "%RELEASE_DIR%"
robocopy dist\OtomePortraitCompositor_Ver1.0 "%RELEASE_DIR%" /E >nul
copy /Y README.md "%RELEASE_DIR%\README.md" >nul
copy /Y LICENSE "%RELEASE_DIR%\LICENSE" >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%RELEASE_DIR%\*' -DestinationPath 'release\オトメ世界の歩き方_立绘合成器_Ver1.0_Windows_x64.zip' -Force"

echo.
echo Release finished.
echo Folder: %RELEASE_DIR%
echo Zip   : release\オトメ世界の歩き方_立绘合成器_Ver1.0_Windows_x64.zip
pause
