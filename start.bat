@echo off
rem Update, install packages and start the bot. Restarts automatically when the bot pulls an update.
cd /d "%~dp0"
if exist .git (
    git pull --ff-only
)
if not exist .venv (
    py -m venv .venv
)
call .venv\Scripts\activate.bat
:run
pip install -q -r requirements.txt
python -m chumai
if %errorlevel%==3 goto run
pause
