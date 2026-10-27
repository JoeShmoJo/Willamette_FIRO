@echo off
setlocal
set "FIRO_TOOL_PATH=%~dp0Compare-Inputs.ps1"
powershell.exe -NoProfile -STA -ExecutionPolicy RemoteSigned -Command "Unblock-File -LiteralPath $env:FIRO_TOOL_PATH; & $env:FIRO_TOOL_PATH"
if errorlevel 1 (
  echo.
  echo The review window could not start. The error is shown above.
  pause
)
endlocal
