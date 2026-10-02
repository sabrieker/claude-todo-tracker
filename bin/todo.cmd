@echo off
rem The todo command for cmd.exe and PowerShell on Windows.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -X utf8 "%~dp0todo-run.py" %*
) else (
  python -X utf8 "%~dp0todo-run.py" %*
)
