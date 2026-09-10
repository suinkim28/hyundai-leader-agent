@echo off
REM Windows entry point.  Call as:  bin\graph.cmd mail --unread
REM
REM IMPORTANT: keep this file ASCII-only. cmd.exe reads/tokenizes a .bat/.cmd
REM script using the console code page that was active when it started
REM reading the file. On Korean Windows that is cp949 by default, but this
REM repo's files are saved as UTF-8. Re-interpreting UTF-8 bytes as cp949
REM can make cmd.exe misparse the script (it has literally executed
REM fragments of Korean text as bogus commands during testing). Putting
REM `chcp 65001` at the top does NOT reliably fix this, because cmd.exe can
REM buffer-read this same script before the chcp takes effect. Human-facing
REM Korean text belongs in graph.py, which already forces UTF-8 output via
REM PYTHONUTF8 below and is read/executed by Python, not by cmd.exe's batch
REM parser.
setlocal
set "GRAPH_PY=%~dp0graph.py"
set "PYTHONUTF8=1"

where py >nul 2>&1
if not errorlevel 1 goto :usepy
where python >nul 2>&1
if not errorlevel 1 goto :usepython
where python3 >nul 2>&1
if not errorlevel 1 goto :usepython3

echo Python was not found. Install Python 3.11+ from python.org and try again. 1>&2
echo   Be sure to check "Add python.exe to PATH" during setup. 1>&2
exit /b 9009

:usepy
py -3 "%GRAPH_PY%" %*
exit /b %ERRORLEVEL%

:usepython
python "%GRAPH_PY%" %*
exit /b %ERRORLEVEL%

:usepython3
python3 "%GRAPH_PY%" %*
exit /b %ERRORLEVEL%
