@echo off
setlocal
set BASE=%~dp0
set PY=%BASE%venv\Scripts\pythonw.exe
if not exist "%PY%" set PY=pythonw
schtasks /create /tn "AI_CEO_Production" /tr "\"%PY%\" \"%BASE%main.py\"" /sc onlogon /ru %USERNAME% /rl highest /f
echo AI CEO Production will start on Windows logon.
pause
