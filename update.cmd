@echo off
rem Runs scripts\update-ytdlp.ps1 with a process-scoped execution policy: it changes no system setting.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update-ytdlp.ps1" %*
exit /b %ERRORLEVEL%
