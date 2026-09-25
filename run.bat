@echo off
setlocal

set "VENV=%~dp0.venv"
set "REQ=%~dp0requirements.txt"

:: ---- Create requirements.txt if missing ----
if not exist "%REQ%" (
    echo Creating requirements.txt...
    (
        echo PySide6^>=6.6
        echo Pillow^>=10.0
        echo chardet^>=5.0
    ) > "%REQ%"
)

:: ---- Create venv if missing ----
if not exist "%VENV%\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo ERROR: Failed to create venv. Is Python installed and on PATH?
        pause
        exit /b 1
    )
)

:: ---- Install / upgrade packages ----
echo Checking packages...
"%VENV%\Scripts\python.exe" -m pip install -q --no-cache-dir --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -q --no-cache-dir -r "%REQ%"
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

:: ---- Run ----
:: With no args: launch the tour (which offers to open the app alongside).
:: With any args (e.g. --cli, --batch): pass straight through to elitis.
if "%~1"=="" (
    "%VENV%\Scripts\python.exe" tools\tour.py
) else (
    "%VENV%\Scripts\python.exe" -m elitis %*
)
