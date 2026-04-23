@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist release rmdir /s /q release
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
for /r %%f in (*.pyc) do @if exist "%%f" del /q "%%f"
echo Cleaned.
pause
