@echo off
setlocal
cd /d "%~dp0"
echo Installing the optional MuseTalk lip-sync backend...
echo This creates a project-local Python 3.10 environment and clones MuseTalk.
echo.

py -3.10 -c "import sys" >nul 2>&1
if errorlevel 1 goto :python_missing

if not exist "MuseTalk\scripts\inference.py" (
    echo Cloning MuseTalk...
    git clone https://github.com/TMElyralab/MuseTalk.git MuseTalk
    if errorlevel 1 goto :failed
)

if not exist "musetalk-runtime\Scripts\python.exe" py -3.10 -m venv musetalk-runtime
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
echo MuseTalk is ready. Restart TachiDUBB Studio to enable lip-sync.
pause
exit /b 0

:python_missing
echo Python 3.10 is required for MuseTalk. Install it, then rerun this file.
pause
exit /b 1

:failed
echo.
echo MuseTalk installation stopped. See the command above for the failing package.
echo If torch failed on an RTX 40/50-series GPU, install a newer cu12x torch build.
pause
exit /b 1