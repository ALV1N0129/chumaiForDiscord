@echo off
rem Update (if this folder was cloned with git), install packages, and start the bot.
cd /d "%~dp0"
if exist .git (
    git pull --ff-only
)
if not exist .venv (
    py -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
python -m chumai
pause
