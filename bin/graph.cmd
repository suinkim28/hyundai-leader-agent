@echo off
REM Windows 진입점.  bin\graph mail --unread   처럼 부른다.
REM 문서의 `python3 bin/graph ...` 는 Windows 에서 `bin\graph ...` 로 읽는다.
setlocal
set "GRAPH_PY=%~dp0graph.py"

where py >nul 2>&1
if not errorlevel 1 goto :usepy
where python >nul 2>&1
if not errorlevel 1 goto :usepython
where python3 >nul 2>&1
if not errorlevel 1 goto :usepython3

echo Python 을 찾지 못했습니다. python.org 에서 설치한 뒤 다시 시도하십시오. 1>&2
echo   설치 화면에서 "Add python.exe to PATH" 를 반드시 체크하십시오. 1>&2
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
