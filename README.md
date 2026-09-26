# chumaiForDiscord

maimai DX / CHUNITHM의 **Best 50 레이팅표**를 이미지로 보여주는 디스코드 봇입니다.

- maimai DX: 구곡 Best 35 + 신곡 Best 15
- CHUNITHM (VERSE 이후 방식): 구곡 Best 30 + 신곡 Best 20, 레이팅 = 합계 / 50

## 데이터 출처

두 가지 방법 중 하나로 기록을 가져옵니다. `/b50`은 SEGA ID 로그인이 있으면 그걸 먼저 쓰고, 없으면 Kamaitachi를 씁니다.

### 1. SEGA ID 로그인 (국제판 공식 사이트)

`/login`을 입력하면 뜨는 창에 SEGA ID, 비밀번호, (사용 중이면) 2단계 인증 코드를 넣으면 됩니다.
봇이 [CHUNITHM-NET](https://chunithm-net-eng.com) / [maimai DX NET](https://maimaidx-eng.com)에 직접 접속해 기록을 읽어옵니다.

- **비밀번호는 저장하지 않습니다.** 로그인 직후 SEGA가 발급하는 로그인 유지 토큰(`clal`)만 저장하고,
  이후에는 그 토큰으로 접속합니다. `TOKEN_ENCRYPTION_KEY`를 설정하면 토큰도 암호화해서 저장합니다.
- `/logout`으로 저장된 토큰을 언제든 삭제할 수 있습니다.
- `/privacy public:False`로 다른 사람이 내 B50을 못 보게 할 수 있습니다. (기본값: 공개)
- CHUNITHM은 공식 사이트의 "Music for Rating (Best / New)" 목록을 그대로 사용하고,
  maimai DX는 전체 기록을 읽어서 B50을 직접 고릅니다.
- 공식 사이트는 보면 상수를 보여주지 않으므로, 상수는 Kamaitachi의 공개 곡 데이터
  (GitHub의 Tachi seeds)를 내려받아 사용합니다. 하루에 한 번 갱신되며 `SONGDB_DIR`에 캐시됩니다.
- 국제판(SEGA ID) 전용입니다. 일본판은 로그인 방식이 달라 지원하지 않습니다.

> Discord 입력창(Modal)은 비밀번호 가리기(`***`)를 지원하지 않아서 입력하는 동안 본인 화면에는 비밀번호가 보입니다.
> 다른 사람에게는 보이지 않습니다.

### 2. Kamaitachi

커뮤니티 스코어 트래커 [Kamaitachi](https://kamai.tachi.ac)의 공개 API를 사용합니다. 국제판·일본판 모두 지원합니다.
플레이어가 먼저 Kamaitachi에 가입해 기록을 가져와 두고, `/link`로 아이디를 연결하면 됩니다.

곡별 레이팅은 보면 상수와 점수로 봇이 직접 계산합니다.

## 명령어

| 명령어 | 설명 |
| --- | --- |
| `/login` | SEGA ID로 로그인 (국제판) |
| `/logout` | 저장된 SEGA 로그인 토큰 삭제 |
| `/privacy public:<True\|False>` | 다른 사람이 내 B50(SEGA 로그인)을 볼 수 있는지 설정 |
| `/link username:<Kamaitachi 아이디>` | 내 디스코드 계정에 Kamaitachi 아이디 연결 |
| `/unlink` | Kamaitachi 연결 해제 |
| `/b50 game:<maimai\|chunithm> [member] [username] [source]` | B50 이미지 출력. 인자가 없으면 본인 것, `member`로 다른 사람 것, `username`으로 Kamaitachi 아이디 직접 조회. `source`로 `sega`/`kamaitachi` 강제 선택 |
| `/calc game:<maimai\|chunithm> const:<상수> score:<점수>` | 단일 곡 레이팅 계산 (maimai는 달성률 %, CHUNITHM은 점수) |

## 실행 방법

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 앱을 만들고 Bot 토큰을 발급받습니다.
2. OAuth2 → URL Generator에서 `bot`, `applications.commands` 스코프로 서버에 초대합니다.
   (필요 권한: Send Messages, Attach Files, Embed Links)
3. 설정 파일을 만듭니다.
   ```bash
   cp .env.example .env   # DISCORD_TOKEN, TOKEN_ENCRYPTION_KEY 입력
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
  segaid.py   SEGA ID 로그인 / CHUNITHM-NET·maimai DX NET 세션
  net_parsers.py  공식 사이트 HTML 파서
  songdb.py   보면 상수 DB (Tachi seeds)
  tachi.py    Kamaitachi API 클라이언트
  rating.py   곡별 레이팅 공식 (maimai / CHUNITHM)
  b50.py      구곡/신곡 분리 및 B50 선정
  render.py   B50 이미지 생성 (Pillow)
  storage.py  연동 정보·로그인 토큰 저장 (SQLite)
```

`tests/fixtures/chunithm_net/`의 HTML은 [chuni-penguin](https://github.com/beer-psi/chuni-penguin)의
테스트 자료(0BSD)를 가져온 것입니다. SEGA ID 로그인 흐름은 chuni-penguin을 참고했습니다.
