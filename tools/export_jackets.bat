@echo off
rem CHUNITHM 게임 폴더의 자켓(300x300)을 봇용 파일로 바꿉니다. 예: export_jackets.bat "D:\chuni\A000" "D:\chuni\option"
chcp 65001 >nul
cd /d "%~dp0"
python -c "import PIL" 2>nul || pip install pillow
python export_jackets.py %*
pause
