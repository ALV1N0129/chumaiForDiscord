# chumaiForDiscord

maimai DX / CHUNITHM의 **Best 50 레이팅표**를 이미지로 보여주는 디스코드 봇입니다.

- maimai DX: 구곡 Best 35 + 신곡 Best 15
- CHUNITHM (VERSE 이후 방식): 구곡 Best 30 + 신곡 Best 20, 레이팅 = 합계 / 50

## 동작 방식

SEGA ID로 로그인하면 봇이 국제판 공식 사이트([CHUNITHM-NET](https://chunithm-net-eng.com),
[maimai DX NET](https://maimaidx-eng.com))에서 직접 기록을 읽어옵니다.

- `/login`을 입력하면 뜨는 창에 SEGA ID, 비밀번호, (사용 중이면) 2단계 인증 코드를 넣습니다.
- **비밀번호는 저장하지 않습니다.** 로그인 직후 SEGA가 발급하는 로그인 유지 토큰(`clal`)만 저장하고,
  이후에는 그 토큰으로 접속합니다. `TOKEN_ENCRYPTION_KEY`를 설정하면 토큰도 암호화해서 저장합니다.
- `/logout`으로 저장된 토큰을 언제든 삭제할 수 있습니다.
- `/privacy public:False`로 다른 사람이 내 B50을 못 보게 할 수 있습니다. (기본값: 공개)
- CHUNITHM은 공식 사이트의 "Music for Rating (Best / New)" 목록을 그대로 사용하고,
  maimai DX는 전체 기록을 읽어서 B50을 직접 고릅니다.
- 공식 사이트는 보면 상수를 보여주지 않으므로, 상수는 공개된 곡 데이터 파일
  ([Tachi](https://github.com/TNG-dev/Tachi)의 seeds)을 GitHub에서 내려받아 사용합니다.
  계정이나 로그인은 필요 없고, 하루에 한 번 갱신되며 `SONGDB_DIR`에 캐시됩니다.
- 이미지 스타일은 `.env`의 `B50_STYLE`로 고릅니다: `collage`(기본, 1위 곡 자켓 배경), `glow`, `light`.
- 상단 가운데 로고는 `.env`의 `MAIMAI_LOGO_URL` / `CHUNITHM_LOGO_URL`에 공식 로고 이미지 주소를 넣으면
  처음 실행할 때 받아서 씁니다(`data/logos`에 저장). 비워두면 글자 로고를 그립니다.
  `chumai/assets/logos/maimai.png`처럼 파일을 직접 넣어도 됩니다.
- 곡 자켓은 SEGA 공식 곡 목록(`music.json`, `maimai_songs.json`)에서 찾아 내려받고 `JACKET_DIR`에 캐시합니다.
- 국제판(SEGA ID) 전용입니다. 일본판은 로그인 방식이 달라 지원하지 않습니다.

> Discord 입력창(Modal)은 비밀번호 가리기(`***`)를 지원하지 않아서 입력하는 동안 본인 화면에는 비밀번호가 보입니다.
> 다른 사람에게는 보이지 않습니다.

## 명령어

모든 명령어는 슬래시(`/b50`)와 접두어(`!b50 chuni`) 둘 다 쓸 수 있습니다.
접두어는 `.env`의 `PREFIX`로 바꿀 수 있고, 게임은 `mai` / `chuni`로 줄여 써도 됩니다.
접두어 명령어를 쓰려면 Discord 개발자 포털 → Bot → **Message Content Intent**를 켜야 합니다.

예: `!b50 chuni`, `!b50 mai @친구`, `!info chuni aleph`, `!whatif chuni aleph-0 MAS 1009000`, `!playlog on mai`, `!random chuni 14+ 3`, `!const mai 13.5-13.9`

| 명령어 | 설명 |
| --- | --- |
| `/login` | SEGA ID로 로그인 (국제판) |
| `/logout` | 저장된 SEGA 로그인 토큰 삭제 |
| `/privacy public:<True\|False>` | 다른 사람이 내 B50(SEGA 로그인)을 볼 수 있는지 설정 |
| `/b50 game:<maimai\|chunithm> [member]` | B50 이미지 출력. `member`를 지정하면 다른 사람 것 (공개 설정인 경우) |
| `/playlog on game:<maimai\|chunithm>` | 새로 플레이한 크레딧을 이 채널에 이미지로 자동 업로드 |
| `/playlog off game:<maimai\|chunithm>` | 자동 업로드 끄기 |
| `/playlog test game:<maimai\|chunithm>` | 최근 크레딧 하나를 바로 올려 보기 (확인용) |
| `/update` | GitHub에서 최신 코드를 바로 받아 재시작 (봇 주인만). 자동으로도 1분마다 확인합니다 |
| `/profile game:` | 프로필 카드 (아이콘, 칭호, 레벨, 네임플레이트, 레이팅) |
| `/recent game:` | 가장 최근 크레딧 |
| `/info game: song:` | 곡 정보 (난이도별 레벨·상수, 아티스트, 장르, 버전, 자켓) |
| `/jacket game: song:` | 자켓 이미지 |
| `/const game: level:` | 레벨(14+)·상수(14.5)·범위(14.0-14.8)에 해당하는 보면 목록 |
| `/random game: level: [count:]` (`!r`) | 레벨·상수·범위에서 랜덤 선곡 (곡마다 카드로 표시, 기본 3곡) |
| `/reach game: const: target:` | 목표 곡 레이팅에 필요한 점수 |
| `/whatif game: song: difficulty: score:` | 그 점수를 받으면 레이팅이 어떻게 바뀌는지 |
| `/recommend game:` | 레이팅 올리기 좋은 곡 추천 |
| `/guess game:` / `/answer title:` | 자켓 일부를 보고 곡 맞히기 |
| `/help` | 명령어 목록 |
| `/calc game:<maimai\|chunithm> const:<상수> score:<점수>` | 단일 곡 레이팅 계산 (maimai는 달성률 %, CHUNITHM은 점수) |

### 플레이 기록 자동 업로드

`/playlog on`을 입력한 채널에, 크레딧이 끝난 뒤 그 크레딧의 곡들을 이미지 한 장으로 올립니다.
공식 사이트의 최근 플레이 페이지를 평소엔 15분, 새 플레이가 있었던 뒤 1시간 동안은 5분마다 한 번씩 확인합니다
(공식 사이트는 크레딧이 끝나야 기록이 반영되므로 실시간은 아닙니다).

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

숫자와 영문 라벨은 함께 들어 있는 Barlow Condensed(SIL OFL, `chumai/assets/display/`)를 씁니다.
곡 제목은 일본어 폰트가 필요하며 다음 순서로 찾습니다.

1. `FONT_PATH` 환경변수
2. `chumai/assets/fonts/` 폴더 안의 `.ttf/.otf/.ttc` 파일
3. 시스템 폰트 (Noto Sans CJK, 히라기노, Windows의 Yu Gothic/메이리오)

Windows와 Mac은 따로 설치할 필요가 없고, Linux는 `sudo apt install fonts-noto-cjk`로 설치하면 됩니다.

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
  rating.py   곡별 레이팅 공식 (maimai / CHUNITHM)
  b50.py      구곡/신곡 분리 및 B50 선정
  render.py   B50 이미지 생성 (Pillow)
  jackets.py  곡 자켓 찾기·캐시
  tls.py      인증서 체인이 불완전한 사이트 대응
  storage.py  로그인 토큰 저장 (SQLite)
```

`tests/fixtures/chunithm_net/`의 HTML은 [chuni-penguin](https://github.com/beer-psi/chuni-penguin)의
테스트 자료(0BSD)를 가져온 것입니다. SEGA ID 로그인 흐름은 chuni-penguin을 참고했습니다.
