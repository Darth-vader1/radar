@echo off
rem Starts the RADAR dev stack. Double-click, or run from a terminal: scripts\dev.cmd [-NoBrowser] [-SkipMigrations]
rem (Wraps dev.ps1 so it runs regardless of the PowerShell script execution policy.)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
if "%~1"=="" pause
