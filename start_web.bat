@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PROJECT_ROOT=%~dp0"
if not exist "%PROJECT_ROOT%.local" mkdir "%PROJECT_ROOT%.local"
set "PYTHON_EXE="
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

if defined VIDEOCLAW_PYTHON set "PYTHON_EXE=%VIDEOCLAW_PYTHON:"=%"
if defined PYTHON_EXE goto run_python
if exist "%PROJECT_ROOT%.venv\Scripts\python.exe" set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
if defined PYTHON_EXE goto run_python

where conda >nul 2>&1
if not errorlevel 1 goto run_conda
where python >nul 2>&1
if errorlevel 1 goto no_python
set "PYTHON_EXE=python"
goto run_python

:run_python
"%PYTHON_EXE%" -u "%PROJECT_ROOT%scripts\start_web.py" %* 2>"%PROJECT_ROOT%.local\start_web-bootstrap.log"
set "STARTUP_RESULT=%ERRORLEVEL%"
goto finish

:run_conda
call conda run --no-capture-output -n video-claw python -u "%PROJECT_ROOT%scripts\start_web.py" %* 2>"%PROJECT_ROOT%.local\start_web-bootstrap.log"
set "STARTUP_RESULT=%ERRORLEVEL%"
goto finish

:no_python
echo [FAIL] Python 3.11+ was not found. Run setup_windows.ps1 first.
set "STARTUP_RESULT=1"

:finish
echo.
if "%STARTUP_RESULT%"=="0" goto pause_window
echo Startup failed. Details: "%PROJECT_ROOT%.local\start_web.log"
if exist "%PROJECT_ROOT%.local\start_web-bootstrap.log" type "%PROJECT_ROOT%.local\start_web-bootstrap.log"

:pause_window
if /I "%~1"=="--check" exit /b %STARTUP_RESULT%
echo Press any key to close this launcher.
pause >nul
exit /b %STARTUP_RESULT%
