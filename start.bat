@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

REM ----------------------------------------------------------------------
REM FHH AI Optimizer — one-click dev startup (Windows)
REM
REM Works from BOTH locations because the script computes BASE from
REM %~dp0 (its own directory):
REM   1. C:\Users\Aldo\Desktop\fhh-maintenance-forecasting\
REM   2. C:\Users\Aldo\Desktop\fhh-maintenance-forecasting\.claude\worktrees\<id>\
REM ----------------------------------------------------------------------

REM ANSI escape character for coloured output (Windows 10+ Terminal).
for /F "delims=#" %%E in ('"prompt #$E# & for %%E in (1) do rem"') do set "ESC=%%E"
set "GREEN=%ESC%[32m"
set "RED=%ESC%[31m"
set "BOLD=%ESC%[1m"
set "DIM=%ESC%[2m"
set "RESET=%ESC%[0m"

REM Repo root = directory of this .bat file. %~dp0 ends with a backslash.
set "BASE=%~dp0"

REM Find the Python venv. The main repo has it at <repo>\venv. Worktrees
REM (under .claude\worktrees\<id>\) share the main repo's venv three
REM directory-levels up.
set "VENV="
if exist "%BASE%venv\Scripts\activate.bat" (
  set "VENV=%BASE%venv"
) else if exist "%BASE%..\..\..\venv\Scripts\activate.bat" (
  for %%I in ("%BASE%..\..\..\venv") do set "VENV=%%~fI"
)
if not defined VENV (
  echo %RED%✗ Could not find Python venv.%RESET% Tried:
  echo     %BASE%venv
  echo     %BASE%..\..\..\venv
  echo.
  echo Create one at the repo root with:
  echo     python -m venv venv
  echo     venv\Scripts\activate
  echo     pip install -r requirements.txt
  exit /b 1
)

echo.
echo %BOLD%FHH AI Optimizer startup%RESET%
echo %DIM%   base = %BASE%%RESET%
echo %DIM%   venv = %VENV%%RESET%

REM ----------------------------------------------------------------------
REM 1. Docker / Postgres
REM ----------------------------------------------------------------------
echo.
echo [1/4] Docker / Postgres
docker ps --format "{{.Names}}" 2>nul | findstr /B /C:"fhh-ts" >nul
if errorlevel 1 (
  echo        fhh-ts not running — starting it...
  docker start fhh-ts >nul 2>nul
  if errorlevel 1 (
    echo %RED%       ✗ Failed to start fhh-ts container.%RESET%
    echo         Is Docker Desktop running? Start it from the Start menu,
    echo         wait for the whale icon to settle, and re-run start.bat.
    exit /b 1
  )
  echo %GREEN%       ✓ fhh-ts started%RESET%
) else (
  echo %GREEN%       ✓ fhh-ts already running%RESET%
)

REM ----------------------------------------------------------------------
REM 2. Backend (FastAPI / uvicorn) — new PowerShell window
REM ----------------------------------------------------------------------
echo.
echo [2/4] Backend (uvicorn :8000)
start "FHH Backend" powershell -NoExit -ExecutionPolicy Bypass -Command ^
  "$Host.UI.RawUI.WindowTitle = 'FHH Backend';" ^
  "Set-Location -LiteralPath '%BASE%';" ^
  "& '%VENV%\Scripts\Activate.ps1';" ^
  "uvicorn backend.api.main:app --reload --port 8000"
echo %GREEN%       ✓ FHH Backend window opened%RESET%

REM ----------------------------------------------------------------------
REM 3. Frontend (Python http.server) — new PowerShell window
REM ----------------------------------------------------------------------
echo.
echo [3/4] Frontend (http.server :8080)
start "FHH Frontend" powershell -NoExit -ExecutionPolicy Bypass -Command ^
  "$Host.UI.RawUI.WindowTitle = 'FHH Frontend';" ^
  "Set-Location -LiteralPath '%BASE%frontend';" ^
  "python -m http.server 8080"
echo %GREEN%       ✓ FHH Frontend window opened%RESET%

REM ----------------------------------------------------------------------
REM 4. Wait for the servers, then open the browser
REM ----------------------------------------------------------------------
echo.
echo [4/4] Waiting 5s for servers to come up...
timeout /t 5 /nobreak >nul

echo.
echo %BOLD%🚀 FHH AI Optimizer is starting...%RESET%
echo    Frontend   http://localhost:8080
echo    Backend    http://localhost:8000/docs
echo.

REM Prefer Chrome; fall back to the user's default browser if Chrome isn't on PATH.
where /q chrome
if errorlevel 1 (
  start "" "http://localhost:8080"
) else (
  start "" chrome "http://localhost:8080"
)

endlocal
