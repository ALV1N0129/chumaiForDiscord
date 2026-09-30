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
- 파일 하나를 실행하는 호스팅(디스호스트 등)에서는 시작 파일을 `app.py`로 두면 됩니다(`python -m chumai`와 같음).
- 메모리가 적은 호스팅(128MB 등)에서는 `.env`에 `LOW_MEMORY=1`을 넣으세요. B50은 60%, 상수표·추천은 70% 크기로 그려서
  메모리를 아낍니다(디자인은 같고 이미지만 작아집니다). B50 크기는 `B50_SCALE=0.7`처럼 직접 정할 수도 있어요.
- 결과 이미지는 기본으로 WebP(PNG의 약 1/3 크기)로 보냅니다. `.env`의 `IMAGE_FORMAT`으로 `jpeg` / `png`를 고를 수 있어요.
- 이미지 스타일은 `.env`의 `B50_STYLE`로 고릅니다: `collage`(기본, 1위 곡 자켓 배경), `glow`, `light`.
- 상단 가운데 로고는 `.env`의 `MAIMAI_LOGO_URL` / `CHUNITHM_LOGO_URL`에 공식 로고 이미지 주소를 넣으면
  처음 실행할 때 받아서 씁니다(`data/logos`에 저장). 비워두면 글자 로고를 그립니다.
  `chumai/assets/logos/maimai.png`처럼 파일을 직접 넣어도 됩니다.
- 곡 자켓은 SEGA 공식 곡 목록(`music.json`, `maimai_songs.json`)에서 찾아 내려받고 `JACKET_DIR`에 캐시합니다.
- `/chart`의 채보 이미지는 팬 사이트 [sdvx.in](https://sdvx.in)에서 필요할 때 받아 `CHART_DIR`에 캐시하고,
  어떤 곡이 sdvx.in의 어느 페이지인지는 [chuni-penguin](https://github.com/beer-psi/chuni-penguin)의 곡 데이터(0BSD)를 씁니다.
  sdvx.in은 이미지 무단 전재를 금지하므로 개인 서버에서만 쓰세요. maimai는 이 데이터가 없어 지원하지 않습니다.
- 국제판(SEGA ID) 전용입니다. 일본판은 로그인 방식이 달라 지원하지 않습니다.

> Discord 입력창(Modal)은 비밀번호 가리기(`***`)를 지원하지 않아서 입력하는 동안 본인 화면에는 비밀번호가 보입니다.
> 다른 사람에게는 보이지 않습니다.

## 명령어

모든 명령어는 슬래시(`/b50`)와 접두어(`!b50 chuni`) 둘 다 쓸 수 있습니다.
접두어는 `.env`의 `PREFIX`로 바꿀 수 있고, 게임은 `m` / `mai` / `c` / `chuni`로 줄여 써도 됩니다.
명령어도 아래 표의 "줄임"처럼 짧게 쓸 수 있어요 (`!b c` = `!b50 chunithm`).
접두어 명령어를 쓰려면 Discord 개발자 포털 → Bot → **Message Content Intent**를 켜야 합니다.

예: `!b c`, `!r m 13+`, `!i c aleph`, `!b50 chuni`, `!b50 mai @친구`, `!info chuni aleph`, `!whatif chuni aleph-0 MAS 1009000`, `!playlog on mai`, `!random chuni 14+ 3`, `!const mai 13.5-13.9`

| 명령어 | 줄임 | 설명 |
| --- | --- | --- |
| `/login` | | SEGA ID로 로그인 (국제판) |
| `/logout` | | 저장된 SEGA 로그인 토큰 삭제 |
| `/privacy public:<True\|False>` | | 다른 사람이 내 B50(SEGA 로그인)을 볼 수 있는지 설정 |
| `/b50 game:<maimai\|chunithm> [member]` | `!b` | B50 이미지. `member`를 지정하면 다른 사람 것 (공개 설정인 경우) |
| `/playlog on\|off\|test game:` | `!pl` | 새로 플레이한 크레딧을 이 채널에 이미지로 자동 업로드 / 끄기 / 최근 크레딧 바로 올려 보기 |
| `/playlog all on\|off` | | 로그인한 사람 모두의 플레이 기록을 이 채널에 자동 업로드 (봇 주인만) |
| `/update` | | GitHub에서 최신 코드를 바로 받아 재시작 (봇 주인만). 자동으로도 1분마다 확인합니다 |
| `/logs status` | | 플레이 로그 자동 업로드 상태(계정별 마지막 확인·실패 이유)와 최근 로그 (봇 주인만) |
| `/logs live on\|off` | | 입력한 채널에 봇 로그를 실시간으로 올리기 / 끄기 (경고·오류, 시작·업데이트, 크레딧 업로드; 봇 주인만) |
| `/profile game:` | `!p` | 프로필 카드 (아이콘, 칭호, 레벨, 네임플레이트, 레이팅) |
| `/recent game:` | `!rc` | 가장 최근 크레딧 |
| `/today game:` | `!td` | 오늘 플레이 정리: 크레딧·곡·신기록·AJ/FC 수, 레이팅 변화, 신기록 곡(많이 오른 순). 새벽 4시까지는 전날로 칩니다 |
| `/info game: song:` | `!i` | 곡 정보 이미지 (자켓, 난이도별 레벨·상수, 아티스트, 장르, 버전) |
| `/jacket game: song:` | `!j` | 자켓 이미지 |
| `/chart song: [difficulty:]` | `!ch` | CHUNITHM 채보 이미지 (sdvx.in, 기본 MASTER) |
| `/const game: level:` | `!c` | 레벨(14+)·상수(14.5)·범위(14.0-14.8)에 해당하는 보면 목록 이미지 (상수별로 묶어서, 최대 90개) |
| `/random game: level: [count:]` | `!r` | 레벨·상수·범위에서 랜덤 선곡 (기본 3곡) |
| `/reach game: const: target:` | `!rh` | 목표 곡 레이팅에 필요한 점수 + 점수별 레이팅 표 |
| `/whatif game: song: difficulty: score:` | `!w` | 그 점수를 받으면 레이팅이 어떻게 바뀌는지 |
| `/recommend game:` | `!rec` | 레이팅을 올릴 수 있는 곡 6개를 쉬운 곡부터 추천 (아래 기준) |
| `/calc game: const: score:` | `!cal` | 단일 곡 레이팅 계산 + 점수별 레이팅 표 (maimai는 달성률 %, CHUNITHM은 점수) |
| `/guess game:` / `/answer title:` | `!g` / `!a` | 자켓 일부를 보고 곡 맞히기 (문제 아래 **정답 입력** 버튼으로도 답할 수 있고, 맞히면 입력한 답도 함께 보여줌) |
| `/giveup` | `!포기` / `!gu` | 맞히기를 포기하고 정답 보기 (문제 아래 버튼으로도 가능) |
| `/alias add\|remove\|list game: song: [name:]` | | 맞히기에서 정답으로 인정할 곡 별명 (서버별, 예: 뇌장작렬걸) |
| `/help` | `!h` | 명령어 목록 |

### 맞히기 정답

제목을 다 쓰지 않아도 됩니다. 띄어쓰기·기호·대소문자·악센트는 무시하고(`aleph0`), 오타 한두 개도 봐줍니다.
제목의 일부만 써도 되고(`endy`, `crossmythos`, `千本` — 영문 4글자·한자/한글 2글자 이상, 제목의 1/4 이상),
공식 곡 목록의 읽는 법으로 가나(`のうしょう`)나 한국어 발음(`노우쇼사쿠레츠가루`, `센본자쿠라`)으로 써도 됩니다.
한자 제목은 한국 한자음으로도 됩니다(`뇌장작렬걸`, `천본앵`, `미쿠의 소실`, 긴 제목은 앞부분만 `혼돈`).
영문·카타카나 제목은 한국어로 부르는 이름, 일본어 제목은 한국어 번역으로도 됩니다(`엔디미온`, `뱀파이어`, `밤을 달리다`, `네가 모르는 이야기`): `chumai/assets/titles_ko.tsv`에
영문 약 1,300곡, 카타카나 약 440곡, 일본어 약 750곡에 적어 두었고, 줄마다 `제목<TAB>발음<TAB>...` 형식이라 직접 추가할 수 있습니다.
한국어 이름의 단어 첫 글자 줄임말(`프다`, `월뱅`)도 됩니다.
커뮤니티 별명은 [GCM-bot](https://github.com/lomotos10/GCM-bot)이 모아 둔 목록(maimai 한국어, 두 게임 영어·로마자)을
봇이 실행될 때 받아서 씁니다(`data/aliases/`에 캐시, 일주일마다 갱신, 이 저장소에는 들어 있지 않음).
CHUNITHM은 [chuni-penguin](https://github.com/beer-psi/chuni-penguin)의 별명(영어·로마자)도 쓰고, 츄니즘 마이너 갤러리 글 제목에서
모은 한국어 별명(`조율주`, `새콤달콤`, `엔탐`, `팬크라` 등)은 `chumai/assets/nicknames_ko.tsv`에 있습니다.
`흑니즘`, `알레프흑`, `멜마`처럼 이름에 난이도(흑·마·울·익)를 붙여 써도 됩니다.
그 밖의 별명은 `/alias add` 로 등록하면 그 서버에서 정답으로 인정됩니다.
한자음은 Unicode의 [Unihan](https://www.unicode.org/charts/unihan.html) 데이터(kHangul, [Unicode License](https://www.unicode.org/license.txt))에서
곡 제목에 나오는 한자만 뽑아 `chumai/assets/hanja_ko.json`에 넣었고, 일본식 약자(脳, 桜 등)는 직접 채웠습니다.

### 추천 기준

두 게임 모두 통계나 추정 없이 **공식 레이팅 산식과 본인 기록만으로** 계산합니다.
곡 레이팅은 랭크 경계(maimai 97.0 / 98.0 / 99.0 / 99.5 / 100.0 / 100.5%, CHUNITHM 975,000 / 990,000 / 1,000,000 /
1,005,000 / 1,007,500 / 1,009,000)에서 크게 달라지므로 목표도 이 경계로 잡습니다.

- **최소**: 그 보면이 B50 최하위(각 칸)를 밀어내는 **정확한 최소 점수** (예: 100.3627%, 1,007,300). 산식으로 계산합니다.
- **목표**: 그 상수 ±0.25 보면들에서 **보통 받는 랭크** (3곡 미만이면 추천 안 함).
  전곡 기록이 있으면 상위 25% 지점(예전에 한 번 치고 만 곡의 낮은 기록이 섞여 있어서),
  B50만 있으면 중앙값(이미 잘 친 곡들이라)이 넘은 랭크 경계입니다. 운 좋은 몇 곡에 끌려가지 않습니다.
  목표가 최소에 못 미치면 추천하지 않습니다. (전곡 기록은 maimai만 B50과 함께 받아 옵니다.)
- **쉬운 곡부터**: 목표 랭크로 B50에 들어가는 보면 중 상수가 낮은 순서로, 상수가 겹치지 않게 고릅니다.
  한 곡은 STD/DX·난이도 중 하나만 나옵니다.
- 이미 친 보면도 현재 기록이 목표보다 낮으면 추천하고 "현재 …"를 보여 줍니다.

### 플레이 기록 자동 업로드

`/playlog on`을 입력한 채널에, 크레딧이 끝난 뒤 그 크레딧의 곡들을 이미지 한 장으로 올립니다.
공식 사이트의 최근 플레이 페이지를 1분마다 한 번씩 확인합니다 (`.env`의 `PLAYLOG_INTERVAL_MINUTES`로 늘릴 수 있음)
(공식 사이트는 크레딧이 끝나야 기록이 반영되므로 실시간은 아닙니다).
확인할 때마다 다시 로그인하지 않고 공식 사이트의 로그인 상태(쿠키, 메모리에만 보관)를 이어 쓰므로
평소에는 한 번에 페이지 하나만 받습니다. 사이트가 로그인을 끊었을 때만 다시 로그인합니다.

곡마다 옆에 표시가 붙습니다: 신기록이면 `NEW +2,150`처럼 오른 만큼, 최고 점수와 같으면 `TIE`,
최고 점수보다 낮으면 `BEST 1,009,450`처럼 내 최고 점수. 오른 폭은 봇이 저장해 둔 최고 점수와 비교하므로
`/playlog on`을 켠 뒤의 플레이부터 나옵니다(그 전에는 `NEW`만). 최고 점수는 `/logout` 하면 함께 지워집니다.

봇 주인이 채널에서 `/playlog all on`을 하면, 각자 켜지 않아도 로그인한 사람 모두의 maimai·CHUNITHM 기록이
그 채널에 올라갑니다(나중에 로그인한 사람도 자동으로 포함). 켠 뒤에 친 것부터 올라가고, 기록을 불러오지 못하는
게임(안 하는 게임)은 몇 번 확인한 뒤 알아서 뺍니다. 각자 `/playlog on`으로 정한 채널이 우선이고,
`/playlog off`로 끈 사람은 계속 꺼진 채로 둡니다.

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

어떤 곡이 "신곡"인지는 버전으로 판정합니다. 기본값은 `maimaiでらっくす CiRCLE`·`maimaiでらっくす CiRCLE PLUS`
(PLUS 버전 기간에는 무印 버전 곡도 신곡), `CHUNITHM X-VERSE-X`이며
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
