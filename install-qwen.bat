@echo off
setlocal
cd /d "%~dp0"
echo Installing the optional Qwen quality voice backend...
echo This creates two project-local Python 3.12 environments.
echo.

py -3.12 -c "import sys" >nul 2>&1
if errorlevel 1 goto :python_missing

if not exist "qwen-runtime\Scripts\python.exe" py -3.12 -m venv qwen-runtime
if errorlevel 1 goto :failed
qwen-runtime\Scripts\python.exe -m pip install --upgrade pip
qwen-runtime\Scripts\python.exe -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto :failed
qwen-runtime\Scripts\python.exe -m pip install numpy huggingface_hub soundfile qwen-asr==0.0.6
if errorlevel 1 goto :failed

if not exist "qwen-tts-runtime\Scripts\python.exe" py -3.12 -m venv qwen-tts-runtime
if errorlevel 1 goto :failed
qwen-tts-runtime\Scripts\python.exe -m pip install --upgrade pip
qwen-tts-runtime\Scripts\python.exe -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto :failed
qwen-tts-runtime\Scripts\python.exe -m pip install numpy huggingface_hub soundfile qwen-tts==0.1.1
if errorlevel 1 goto :failed

echo.
echo Qwen quality mode is ready. Run start-qwen.bat to use it.
pause
exit /b 0

:python_missing
echo Python 3.12 is required for the Qwen backend. Install it, then rerun this file.
pause
exit /b 1

:failed
echo.
echo Qwen installation stopped. See the command above for the failing package.
pause
exit /b 1
