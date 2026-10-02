@echo off
rem Runs scripts\install.ps1 with a process-scoped execution policy: it changes no system setting.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
exit /b %ERRORLEVEL%
