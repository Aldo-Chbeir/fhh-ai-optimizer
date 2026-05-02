@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ----------------------------------------------------------------------
REM FHH AI Optimizer -- one-click dev startup (Windows)
REM
REM ASCII only. No emoji, no ANSI escape codes. Older cmd/PowerShell
REM hosts mangle non-ASCII bytes in batch files and break parsing
REM ("'OTH' is not recognized as an internal or external command").
REM
REM Works from BOTH locations because the script computes BASE from
REM %~dp0 (its own directory):
REM   1. C:\Users\Aldo\Desktop\fhh-maintenance-forecasting\
REM   2. C:\Users\Aldo\Desktop\fhh-maintenance-forecasting\.claude\worktrees\<id>\
REM ----------------------------------------------------------------------

set "BASE=%~dp0"

REM Find the Python venv. Main repo has it at <repo>\venv. Worktrees
REM (under .claude\worktrees\<id>\) share the main repo's venv three
REM directory-levels up.
set "VENV="
if exist "%BASE%venv\Scripts\activate.bat" (
    set "VENV=%BASE%venv"
) else if exist "%BASE%..\..\..\venv\Scripts\activate.bat" (
    for %%I in ("%BASE%..\..\..\venv") do set "VENV=%%~fI"
)
if not defined VENV (
    echo [ERROR] Could not find Python venv. Tried:
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
echo ===============================================
echo FHH AI Optimizer startup
echo ===============================================
echo   base = %BASE%
echo   venv = %VENV%

REM ----------------------------------------------------------------------
REM 1. Docker / Postgres
REM ----------------------------------------------------------------------
echo.
echo [STEP 1/4] Docker / Postgres
docker ps --format "{{.Names}}" 2>nul | findstr /B /C:"fhh-ts" >nul
if errorlevel 1 (
    echo            fhh-ts not running -- starting it...
    docker start fhh-ts >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Failed to start fhh-ts container.
        echo         Is Docker Desktop running? Start it from the Start menu,
        echo         wait for the whale icon to settle, and re-run start.bat.
        exit /b 1
    )
    echo [OK]       fhh-ts started.
) else (
    echo [OK]       fhh-ts already running.
)

REM ----------------------------------------------------------------------
REM 2. Backend (FastAPI / uvicorn)
REM ----------------------------------------------------------------------
echo.
echo [STEP 2/4] Backend ^(uvicorn :8000^)
echo            Spawning new PowerShell window: "FHH Backend"
start "FHH Backend" powershell -NoExit -ExecutionPolicy Bypass -Command ^
  "$Host.UI.RawUI.WindowTitle = 'FHH Backend';" ^
  "Set-Location -LiteralPath '%BASE%';" ^
  "& '%VENV%\Scripts\Activate.ps1';" ^
  "uvicorn backend.api.main:app --reload --port 8000"
echo [OK]       Backend window opened.

REM ----------------------------------------------------------------------
REM 3. Frontend (Python http.server)
REM ----------------------------------------------------------------------
echo.
echo [STEP 3/4] Frontend ^(http.server :8080^)
echo            Spawning new PowerShell window: "FHH Frontend"
start "FHH Frontend" powershell -NoExit -ExecutionPolicy Bypass -Command ^
  "$Host.UI.RawUI.WindowTitle = 'FHH Frontend';" ^
  "Set-Location -LiteralPath '%BASE%frontend';" ^
  "python -m http.server 8080"
echo [OK]       Frontend window opened.

REM ----------------------------------------------------------------------
REM 4. Wait for the servers, then open the browser
REM ----------------------------------------------------------------------
echo.
echo [STEP 4/4] Waiting 5s for servers to come up...
timeout /t 5 /nobreak >nul

echo.
echo ===============================================
echo FHH AI Optimizer is starting...
echo ===============================================
echo    Frontend   http://localhost:8080
echo    Backend    http://localhost:8000/docs
echo.

REM Prefer Chrome; fall back to the user's default browser if Chrome
REM isn't on PATH.
where /q chrome
if errorlevel 1 (
    echo Opening default browser at http://localhost:8080
    start "" "http://localhost:8080"
) else (
    echo Opening Chrome at http://localhost:8080
    start "" chrome "http://localhost:8080"
)

endlocal
