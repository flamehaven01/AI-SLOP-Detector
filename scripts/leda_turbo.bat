@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: ============================================================
::  LEDA TURBO PROTOCOL v3.5  (BAT = thin wrapper, Python = logic)
::  Usage: leda_turbo.bat "TARGET_DIR" [N_FILES]
::  Location: ai-slop-detector\scripts\leda_turbo.bat
::  Requires: scripts\leda_helper.py  (co-located)
:: ============================================================

set VENV=%~dp0..\.venv\Scripts
set PYTHON=%VENV%\python.exe
set HELPER=%~dp0leda_helper.py
set INJECTOR=%~dp0global_injector.py

set TARGET=%~1
set N=%~2
if "%TARGET%"=="" (
    echo [!] ERROR: No target specified.
    echo [>] Usage: leda_turbo.bat "TARGET_DIR" [N_FILES]
    echo [>] Example: leda_turbo.bat "D:\Sanctum\Extra Repo\minGPT" 3
    pause ^& exit /b 1
)
if "%N%"=="" set N=3

echo.
echo [*] LEDA TURBO PROTOCOL v3.5
echo [>] Target   : %TARGET%
echo [>] TopFiles : %N%
echo ============================================================
echo.

if not exist "%TARGET%\*" (
    echo [!] ERROR: Directory not found: %TARGET%
    echo [>] Check path spelling and quotes.
    pause ^& exit /b 1
)
if not exist "%PYTHON%" (
    echo [!] ERROR: Python not found: %PYTHON%
    pause ^& exit /b 1
)
if not exist "%HELPER%" (
    echo [!] ERROR: leda_helper.py not found: %HELPER%
    echo [>] Ensure scripts\leda_helper.py exists.
    pause ^& exit /b 1
)

set REPORT=%TARGET%\slop_reports
if not exist "%REPORT%\" mkdir "%REPORT%"
set CFG=%TARGET%\.slopconfig.yaml

"%PYTHON%" -c "import yaml" 2>nul
if errorlevel 1 "%VENV%\pip.exe" install pyyaml -q

echo.
:: ------------------------------------------------------------
echo [STEP 0] Config check...
if exist "%CFG%" (
    echo [o] .slopconfig.yaml found
) else (
    echo [!] Not found -- using defaults
    set CFG=
)
echo.

:: ------------------------------------------------------------
echo [STEP 1] Baseline scan...
if defined CFG (
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --json --config "%CFG%" > "%REPORT%\scan_1.json" 2>&1
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --emit-leda-yaml --leda-output "%REPORT%\leda_1.yaml" --config "%CFG%" > nul 2>&1
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --self-calibrate --config "%CFG%" > "%REPORT%\calibration_1.txt" 2>&1
) else (
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --json > "%REPORT%\scan_1.json" 2>&1
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --emit-leda-yaml --leda-output "%REPORT%\leda_1.yaml" > nul 2>&1
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --self-calibrate > "%REPORT%\calibration_1.txt" 2>&1
)
echo [+] scan_1.json  leda_1.yaml  calibration_1.txt
echo.

:: ------------------------------------------------------------
echo [STEP 2] Selecting top %N% fixable files...
echo.
"%PYTHON%" "%HELPER%" select "%REPORT%\scan_1.json" %N%
echo.

:: ------------------------------------------------------------
echo [STEP 3] Fix cycles (automated via --auto)...
echo.
if defined CFG (
    "%PYTHON%" "%HELPER%" fixloop "%REPORT%\selected_files.txt" "%PYTHON%" "%CFG%" --auto
) else (
    "%PYTHON%" "%HELPER%" fixloop "%REPORT%\selected_files.txt" "%PYTHON%" --auto
)
echo.

:: ------------------------------------------------------------
echo [STEP 4] Final project scan...
if defined CFG (
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --json --config "%CFG%" > "%REPORT%\scan_final.json" 2>&1
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --emit-leda-yaml --leda-output "%REPORT%\leda_final.yaml" --config "%CFG%" > nul 2>&1
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --self-calibrate --config "%CFG%" > "%REPORT%\calibration_final.txt" 2>&1
) else (
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --json > "%REPORT%\scan_final.json" 2>&1
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --emit-leda-yaml --leda-output "%REPORT%\leda_final.yaml" > nul 2>&1
    "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --self-calibrate > "%REPORT%\calibration_final.txt" 2>&1
)
echo [+] Final scans saved.
echo.

:: ------------------------------------------------------------
echo [STEP 5] LEDA comparison...
echo.
"%PYTHON%" "%HELPER%" compare "%REPORT%\leda_1.yaml" "%REPORT%\leda_final.yaml"
echo.
echo [PROJECT DELTA]:
"%PYTHON%" "%HELPER%" delta "%REPORT%\scan_1.json" "%REPORT%\scan_final.json"
echo.

:: ------------------------------------------------------------
echo [STEP 6] Calibration gate...
"%PYTHON%" "%HELPER%" gapcheck "%REPORT%\leda_final.yaml" > "%REPORT%\gap_check.txt" 2>&1
set /p GAP=<"%REPORT%\gap_check.txt"
echo [>] Gap status: %GAP%

if "%GAP%"=="OK" (
    echo [*] Gap >= 0.10 -- Applying calibration weights...
    if defined CFG (
        "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --self-calibrate --apply-calibration --config "%CFG%"
    ) else (
        "%PYTHON%" -m slop_detector.cli --project "%TARGET%" --self-calibrate --apply-calibration
    )
    echo [+] Weights updated.
) else (
    echo [>] Signal accumulating. Continue with more repos.
    echo [>] After 3+ new repos, re-run: python scripts\global_injector.py
)

echo.
echo ============================================================
echo  [*] COMPLETE -- %REPORT%
echo  [>] To inject global weights: python "%INJECTOR%"
echo ============================================================
pause
