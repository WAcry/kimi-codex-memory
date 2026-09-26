@echo off
setlocal
set "KIMI_CODE_NO_AUTO_UPDATE=1"
set "PYTHONUTF8=1"
set "memory_arch=x64"
if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "memory_arch=arm64"
if /I "%PROCESSOR_ARCHITEW6432%"=="ARM64" set "memory_arch=arm64"
set "memory_binary=%~dp0..\runtime\win32-%memory_arch%\kimi-codex-memory\kimi-codex-memory.exe"
if not exist "%memory_binary%" (
  if "%~1"=="hook" exit /b 0
  echo Install the native release plugin, not a source archive. 1>&2
  exit /b 1
)
"%memory_binary%" %*
if "%~1"=="hook" exit /b 0
exit /b %errorlevel%
