@echo off
setlocal
if defined ROBOT_RUNNER_PYTHON goto custom
python "%~dp0runner.py" %*
exit /b %errorlevel%
:custom
"%ROBOT_RUNNER_PYTHON%" "%~dp0runner.py" %*
exit /b %errorlevel%
