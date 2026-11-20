@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-studio.ps1" %*
set "AUTODECISION_EXIT_CODE=%ERRORLEVEL%"
if not "%AUTODECISION_EXIT_CODE%"=="0" pause
exit /b %AUTODECISION_EXIT_CODE%
