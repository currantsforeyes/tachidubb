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
%PY% -m pip install setuptools wheel "numpy==1.23.5"
if errorlevel 1 goto :failed
REM chumpy's setup.py does `import pip`, which fails under pip's isolated
REM build environment (no pip in it). Build it without isolation instead.
%PY% -m pip install chumpy --no-build-isolation
if errorlevel 1 goto :failed
REM CUDA 12.8 torch: MuseTalk runs OpenMMLab-free here (the worker patches
REM preprocessing.py to use MuseTalk's vendored face detector), so we can use a
REM modern torch with native kernels for RTX 40/50-series (Blackwell) GPUs.
%PY% -m pip install torch==2.8.0+cu128 torchvision==0.23.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto :failed
%PY% -m pip install -r MuseTalk\requirements.txt
if errorlevel 1 goto :failed
REM OpenMMLab (mmcv/mmdet/mmpose) is intentionally NOT installed — their
REM prebuilt wheels stop at torch 2.1/CUDA 12.1 which has no Blackwell kernels.

echo.
echo Downloading MuseTalk weights (a few GB)...
pushd MuseTalk
call download_weights.bat
popd

echo.
echo Verifying weights (fills in any the downloader skipped)...
%PY% tools\ensure_musetalk_weights.py

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
pause
exit /b 1