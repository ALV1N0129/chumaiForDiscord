#!/usr/bin/env bash
# Linux용 실행 스크립트 (start.bat과 같은 동작).
# 업데이트를 받고 패키지를 설치한 뒤 봇을 실행합니다. 봇이 업데이트를 받아 종료 코드 3으로 끝나면 다시 시작합니다.
cd "$(dirname "$0")"
[ -d .git ] && git pull --ff-only
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
while true; do
    pip install -q -r requirements.txt
    python -m chumai
    code=$?
    [ "$code" -eq 3 ] || exit "$code"
done
