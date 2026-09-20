@echo off
setlocal
if not exist "%~dp0qwen-runtime\Scripts\python.exe" goto :missing
if not exist "%~dp0qwen-tts-runtime\Scripts\python.exe" goto :missing
set "TACHIDUBB_TTS_ENGINE=qwen"
call "%~dp0start.bat"
exit /b %errorlevel%

:missing
echo.
echo Qwen quality mode is not installed yet.
echo Run install-qwen.bat once, then start-qwen.bat.
pause
exit /b 1
