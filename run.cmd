@echo off
rem Runs scripts\run.ps1 with a process-scoped execution policy: it changes no system setting.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" %*
exit /b %ERRORLEVEL%
