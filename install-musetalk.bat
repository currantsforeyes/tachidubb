@echo off
setlocal
cd /d "%~dp0"
echo Installing the optional MuseTalk lip-sync backend...
echo This creates a project-local Python 3.10 environment (via uv if available) and clones MuseTalk.
echo.

REM MuseTalk wants Python 3.10. Prefer `uv`, which downloads a local 3.10 with
REM no system install; otherwise fall back to an installed Python 3.10.
set "MAKE_VENV="
where uv >nul 2>&1
if not errorlevel 1 set "MAKE_VENV=uv venv --seed --python 3.10"
if not defined MAKE_VENV (
    py -3.10 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "MAKE_VENV=py -3.10 -m venv"
)
if not defined MAKE_VENV goto :no_python

if not exist "MuseTalk\scripts\inference.py" (
    echo Cloning MuseTalk...
    git clone https://github.com/TMElyralab/MuseTalk.git MuseTalk
    if errorlevel 1 goto :failed
)

if not exist "musetalk-runtime\Scripts\python.exe" %MAKE_VENV% musetalk-runtime
if errorlevel 1 goto :failed
set PY=musetalk-runtime\Scripts\python.exe
%PY% -m pip install --upgrade pip
REM MuseTalk pins an older CUDA 11.8 torch. On RTX 40/50-series you may need a
REM newer cu12x torch build instead — see the MuseTalk README.
%PY% -m pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118
if errorlevel 1 goto :failed
%PY% -m pip install -r MuseTalk\requirements.txt
if errorlevel 1 goto :failed
%PY% -m pip install -U openmim
if errorlevel 1 goto :failed
musetalk-runtime\Scripts\mim.exe install mmengine
if errorlevel 1 goto :failed
musetalk-runtime\Scripts\mim.exe install "mmcv==2.0.1"
if errorlevel 1 goto :failed
musetalk-runtime\Scripts\mim.exe install "mmdet==3.1.0"
if errorlevel 1 goto :failed
musetalk-runtime\Scripts\mim.exe install "mmpose==1.1.0"
if errorlevel 1 goto :failed

echo.
echo Downloading MuseTalk weights (a few GB)...
pushd MuseTalk
call download_weights.bat
popd

echo.
echo Running MuseTalk diagnostic...
if exist venv\Scripts\python.exe venv\Scripts\python.exe tools\diagnose_musetalk.py

echo.
echo MuseTalk is ready. Restart TachiDUBB Studio to enable lip-sync.
pause
exit /b 0

:no_python
echo MuseTalk needs Python 3.10. Install `uv` (https://docs.astral.sh/uv/) — it
echo fetches a local 3.10 with no system install — or install Python 3.10,
echo then rerun this file.
pause
exit /b 1

:failed
echo.
echo MuseTalk installation stopped. See the command above for the failing package.
echo If torch failed on an RTX 40/50-series GPU, install a newer cu12x torch build.
pause
exit /b 1