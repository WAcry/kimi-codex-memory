@echo off
setlocal
set "KIMI_CODE_NO_AUTO_UPDATE=1"
call kimi __plugin_run_node plugin/launch.mjs %*
exit /b %errorlevel%
