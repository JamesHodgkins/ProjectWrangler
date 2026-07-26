@echo off
setlocal
set "PROJECT_DIR=%~dp0"
set "VENV_PYTHON=%PROJECT_DIR%venv\Scripts\python.exe"
cd /d "%PROJECT_DIR%"
"%VENV_PYTHON%" "%PROJECT_DIR%main.py" %*
if errorlevel 1 (
    echo.
    echo Failed to start Coconut.
    pause
)