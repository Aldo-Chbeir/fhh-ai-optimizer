@echo off
setlocal EnableExtensions

REM ----------------------------------------------------------------------
REM FHH AI Optimizer -- graceful shutdown (Windows)
REM
REM ASCII only. Closes the Backend / Frontend PowerShell windows by
REM their titles (set by start.bat) and stops the Postgres docker
REM container.
REM ----------------------------------------------------------------------

echo.
echo ===============================================
echo Stopping FHH AI Optimizer...
echo ===============================================

REM Close backend / frontend PowerShell windows by their titles.
taskkill /FI "WindowTitle eq FHH Backend*" /T /F >nul 2>&1
if errorlevel 1 (
    echo            (FHH Backend window not running)
) else (
    echo [OK]       FHH Backend window closed.
)

taskkill /FI "WindowTitle eq FHH Frontend*" /T /F >nul 2>&1
if errorlevel 1 (
    echo            (FHH Frontend window not running)
) else (
    echo [OK]       FHH Frontend window closed.
)

REM Stop the Postgres container (non-fatal if Docker isn't running).
docker stop fhh-ts >nul 2>&1
if errorlevel 1 (
    echo            (fhh-ts container already stopped, or Docker not running)
) else (
    echo [OK]       Docker container fhh-ts stopped.
)

echo.
echo ===============================================
echo FHH AI Optimizer stopped
echo ===============================================
echo.

endlocal
