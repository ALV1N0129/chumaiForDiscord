# chumaiForDiscord

maimai DX / CHUNITHM의 **Best 50 레이팅표**를 이미지로 보여주는 디스코드 봇입니다.

- maimai DX: 구곡 Best 35 + 신곡 Best 15
- CHUNITHM (VERSE 이후 방식): 구곡 Best 30 + 신곡 Best 20, 레이팅 = 합계 / 50

## 데이터 출처: Kamaitachi

SEGA 공식 API가 없기 때문에, 커뮤니티 스코어 트래커인 [Kamaitachi](https://kamai.tachi.ac)의 공개 API를 사용합니다.
국제판·일본판 모두 지원하며, API 키 없이 공개 프로필을 조회할 수 있습니다.

플레이어는 먼저 Kamaitachi에 가입하고 기록을 가져와야 합니다.
(maimai DX NET / CHUNITHM-NET에서 Kamaitachi가 안내하는 북마클릿·임포트 방식을 사용)

곡별 레이팅은 Kamaitachi가 주는 보면 상수(`levelNum`)와 점수로 봇이 직접 계산합니다.

## 명령어

| 명령어 | 설명 |
| --- | --- |
| `/link username:<Kamaitachi 아이디>` | 내 디스코드 계정에 Kamaitachi 아이디 연동 |
| `/unlink` | 연동 해제 |
| `/b50 game:<maimai\|chunithm> [member] [username]` | B50 이미지 출력. 인자가 없으면 본인 것, `member`로 다른 사람 것, `username`으로 Kamaitachi 아이디 직접 조회 |
| `/calc game:<maimai\|chunithm> const:<상수> score:<점수>` | 단일 곡 레이팅 계산 (maimai는 달성률 %, CHUNITHM은 점수) |

## 실행 방법

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 앱을 만들고 Bot 토큰을 발급받습니다.
2. OAuth2 → URL Generator에서 `bot`, `applications.commands` 스코프로 서버에 초대합니다.
   (필요 권한: Send Messages, Attach Files, Embed Links)
3. 설정 파일을 만듭니다.
   ```bash
   cp .env.example .env   # DISCORD_TOKEN 입력
   ```
4. 실행합니다.
   ```bash
   pip install -r requirements.txt
   python -m chumai
   ```
   또는 Docker:
   ```bash
   docker build -t chumai .
   docker run -d --env-file .env -v $(pwd)/data:/app/data chumai
   ```

### 폰트

곡 제목에 일본어/한국어가 많아서 CJK 폰트가 필요합니다. 다음 순서로 자동 탐색합니다.

1. `FONT_PATH` 환경변수
2. `chumai/assets/fonts/` 폴더 안의 `.ttf/.otf/.ttc` 파일
3. 시스템 폰트 (Noto Sans CJK, 나눔고딕, 맑은 고딕 등)

Linux라면 `sudo apt install fonts-noto-cjk` 한 줄이면 됩니다. Docker 이미지에는 이미 포함되어 있습니다.

### 신곡 기준 버전

어떤 곡이 "신곡"인지는 버전으로 판정합니다. 기본값은 `maimaiでらっくす CiRCLE`, `CHUNITHM X-VERSE-X`이며
새 버전이 나오거나 국제판 버전이 다르면 `.env`의 `MAIMAI_NEW_VERSIONS` / `CHUNITHM_NEW_VERSIONS`를 바꾸면 됩니다.

## 개발

```bash
pip install -r requirements-dev.txt
python -m pytest
```

```
chumai/
  bot.py      디스코드 슬래시 명령어
  tachi.py    Kamaitachi API 클라이언트
  rating.py   곡별 레이팅 공식 (maimai / CHUNITHM)
  b50.py      구곡/신곡 분리 및 B50 선정
  render.py   B50 이미지 생성 (Pillow)
  storage.py  디스코드 ↔ Kamaitachi 연동 정보 (SQLite)
```
