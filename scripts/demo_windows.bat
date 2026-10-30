@echo off
REM ============================================================
REM  WiseQ Hermes -- the demo you show Rob
REM
REM  Run this from Ivan's Windows PC (ivan-desktop).  It:
REM    1. installs the package if needed,
REM    2. runs the test suite,
REM    3. runs the end-to-end demo against WiseQ's own master data.
REM
REM  Everything it prints comes from WiseQ's own files.  No credential
REM  is used, no mail leaves the test mailbox, no order is placed.
REM ============================================================
setlocal

set ROOT=C:\hermes\work\wiseq-hermes
set PY=%ROOT%\.venv\Scripts\python.exe

REM Keep PATH clean: an untrusted mount point on PATH breaks pip.
set PATH=C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0

cd /d %ROOT%
set WISEQ_REPO_DIR=%ROOT%\data\wiseq-repo

if not exist "%PY%" (
  echo >> creating the virtual environment
  python -m venv .venv
)

if not exist "%ROOT%\data\wiseq-repo\README.md" (
  echo.
  echo   The client data clone is missing.  Clone it with:
  echo     cd %ROOT%
  echo     git clone --depth 1 https://github.com/Ai-Whisperers/wiseq-ai-onboarding.git data\wiseq-repo
  echo.
  pause
  exit /b 1
)

echo.
echo >> installing
%PY% -m pip install --quiet -e ".[dev]"

echo.
echo >> running the test suite
%PY% -m pytest -q
if errorlevel 1 (
  echo.
  echo   The test suite failed -- fix that before showing the demo.
  pause
  exit /b 1
)

echo.
echo >> running the demo
%PY% scripts\demo_for_rob.py

echo.
echo >> done.  The API can be started separately with:
echo      scripts\start_api_windows.bat
pause
