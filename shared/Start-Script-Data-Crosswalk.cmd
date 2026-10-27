@echo off
setlocal
set "FIRO_CROSSWALK_PATH=%~dp0Script-Data-Crosswalk.ps1"
powershell.exe -NoProfile -STA -ExecutionPolicy RemoteSigned -Command "Unblock-File -LiteralPath $env:FIRO_CROSSWALK_PATH; & $env:FIRO_CROSSWALK_PATH"
if errorlevel 1 pause
endlocal
