@echo off
rem CHUNITHM 자켓 AI 업스케일 (Windows). 더블클릭해서 실행하세요. 처음엔 설치 때문에 오래 걸려요.
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || (echo Python이 필요해요: https://www.python.org/downloads/ & pause & exit /b 1)
    call .venv\Scripts\activate.bat
    where nvidia-smi >nul 2>nul && (
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
    ) || (
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
    )
    pip install spandrel pillow numpy
) else (
    call .venv\Scripts\activate.bat
)
python upscale_jackets.py %*
pause
