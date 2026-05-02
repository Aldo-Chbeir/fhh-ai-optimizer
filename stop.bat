@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM ----------------------------------------------------------------------
REM FHH AI Optimizer — graceful shutdown (Windows)
REM Closes the Backend / Frontend PowerShell windows by their titles
REM (set by start.bat) and stops the Postgres docker container.
REM ----------------------------------------------------------------------

for /F "delims=#" %%E in ('"prompt #$E# & for %%E in (1) do rem"') do set "ESC=%%E"
set "GREEN=%ESC%[32m"
set "DIM=%ESC%[2m"
set "BOLD=%ESC%[1m"
set "RESET=%ESC%[0m"

echo.
echo Stopping FHH AI Optimizer...

REM Close backend / frontend PowerShell windows by their titles.
taskkill /FI "WindowTitle eq FHH Backend*" /T /F >nul 2>&1
if errorlevel 1 (
  echo %DIM%   (FHH Backend window not running)%RESET%
) else (
  echo %GREEN%   ✓ FHH Backend window closed%RESET%
)

taskkill /FI "WindowTitle eq FHH Frontend*" /T /F >nul 2>&1
if errorlevel 1 (
  echo %DIM%   (FHH Frontend window not running)%RESET%
) else (
  echo %GREEN%   ✓ FHH Frontend window closed%RESET%
)

REM Stop the Postgres container (non-fatal if Docker isn't running).
docker stop fhh-ts >nul 2>&1
if errorlevel 1 (
  echo %DIM%   (fhh-ts container already stopped, or Docker not running)%RESET%
) else (
  echo %GREEN%   ✓ Docker container fhh-ts stopped%RESET%
)

echo.
echo %BOLD%🛑 FHH AI Optimizer stopped%RESET%
echo.

endlocal
