@echo off
setlocal
cd /d "%~dp0"
echo Installing the optional Qwen quality voice backend...
echo This creates two project-local Python 3.12 environments.
echo.

REM The Qwen backend wants Python 3.12. Prefer `uv`, which downloads a local
REM 3.12 with no system install; otherwise fall back to an installed 3.12.
set "MAKE_VENV="
where uv >nul 2>&1
if not errorlevel 1 set "MAKE_VENV=uv venv --seed --python 3.12"
if not defined MAKE_VENV (
    py -3.12 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "MAKE_VENV=py -3.12 -m venv"
)
if not defined MAKE_VENV goto :no_python

if not exist "qwen-runtime\Scripts\python.exe" %MAKE_VENV% qwen-runtime
if errorlevel 1 goto :failed
qwen-runtime\Scripts\python.exe -m pip install --upgrade pip
qwen-runtime\Scripts\python.exe -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto :failed
qwen-runtime\Scripts\python.exe -m pip install numpy huggingface_hub soundfile qwen-asr==0.0.6
if errorlevel 1 goto :failed

if not exist "qwen-tts-runtime\Scripts\python.exe" %MAKE_VENV% qwen-tts-runtime
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

:no_python
echo The Qwen backend needs Python 3.12. Install `uv` (https://docs.astral.sh/uv/)
echo — it fetches a local 3.12 with no system install — or install Python 3.12,
echo then rerun this file.
pause
exit /b 1

:failed
echo.
echo Qwen installation stopped. See the command above for the failing package.
pause
exit /b 1
