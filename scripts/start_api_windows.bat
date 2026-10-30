@echo off
REM ============================================================
REM  WiseQ Hermes -- start the API on the Tailscale address
REM
REM  Run this from Ivan's Windows PC (ivan-desktop).  It starts the
REM  FastAPI surface so it can be demonstrated over Tailscale:
REM
REM      http://100.105.54.119:8000/docs
REM
REM  The API refuses remote reads without a token, so the token is
REM  written to a local file that only Ivan can read.  Rob's demo
REM  (demo_for_rob.py) needs no token at all -- it runs in-process.
REM ============================================================
setlocal

set ROOT=C:\hermes\work\wiseq-hermes
set PY=%ROOT%\.venv\Scripts\python.exe
if "%TS_IP%"=="" set TS_IP=100.105.54.119
if "%PORT%"=="" set PORT=8010

REM Keep PATH clean: an untrusted mount point on PATH breaks pip.
set PATH=C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0

cd /d %ROOT%

REM The client's own master data lives in the sibling clone.
set WISEQ_REPO_DIR=%ROOT%\data\wiseq-repo

REM A local-only token so remote reads work over Tailscale.
if not exist "%ROOT%\.wiseq-token" (
  powershell -NoProfile -Command ^
    "$t=[System.Guid]::NewGuid().ToString('N'); [System.IO.File]::WriteAllText('%ROOT%\.wiseq-token',$t)" >nul
  echo >> created a local API token
)

REM Load the token into the environment for this session.
for /f "usebackq delims=" %%i in ("%ROOT%\.wiseq-token") do set WISEQ_API_TOKEN=%%i

echo.
echo   WiseQ Hermes API
echo   ----------------
echo   Docs      : http://%TS_IP%:%PORT%/docs
echo   Health    : http://%TS_IP%:%PORT%/health
echo   Token     : stored in %ROOT%\.wiseq-token
echo   (a visitor without the token can only see /health and /metrics;
echo    every other read and every write needs it)
echo.
echo   Press Ctrl+C to stop.
echo.

%PY% -m uvicorn wiseq.api:app --host %TS_IP% --port %PORT%
