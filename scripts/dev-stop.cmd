@echo off
rem Stops the RADAR dev stack. Double-click, or run from a terminal: scripts\dev-stop.cmd [-IncludeDatabase]
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev-stop.ps1" %*
if "%~1"=="" pause
