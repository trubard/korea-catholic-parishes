# 한국 천주교 성당 정보 API

[한국 천주교 주소록(CBCK)](https://directory.cbck.or.kr/OnlineAddress/SearchList.aspx)의
본당(성당) 정보를 **매일 자동으로 수집**하여 JSON으로 제공합니다.

별도의 서버·DB 없이 **GitHub Actions(스케줄러) + Git 저장소(DB) + 정적 JSON(API)** 만으로
동작하므로 유지 비용이 들지 않고 영구적으로 운영됩니다. 매 수집이 커밋으로 남아
성당의 신설·폐지·정보 변경 이력이 Git 히스토리에 자동 기록됩니다.

## API (정적 JSON 다운로드)

`<USER>` / `<REPO>` 를 본인 저장소로 바꿔 사용하세요.

| 엔드포인트 | 내용 |
|-----------|------|
| `.../data/churches.json` | 전체 성당 배열 + 메타 |
| `.../data/index.json` | 교구별 건수 요약, 마지막 수집 시각 |
| `.../data/by-diocese/<diocese_id>.json` | 특정 교구 성당만 |

**두 가지 방식으로 접근할 수 있습니다.**

1. **raw URL** — 저장소를 public 으로 push 하면 즉시 사용 가능(설정 불필요)
   ```
   https://raw.githubusercontent.com/<USER>/<REPO>/main/data/churches.json
   ```
2. **GitHub Pages** — CDN(빠름) + CORS 허용(웹/앱에서 fetch 용이)
   ```
   https://<USER>.github.io/<REPO>/data/churches.json
   ```
   저장소 **Settings → Pages → Source: Deploy from a branch → `main` / `/ (root)`** 로 활성화.

### 사용 예시

```bash
curl https://raw.githubusercontent.com/<USER>/<REPO>/main/data/churches.json
```

```js
const res = await fetch("https://<USER>.github.io/<REPO>/data/churches.json");
const { churches } = await res.json();
```

## 데이터 스키마

`churches.json`:

```json
{
  "generated_at": "2026-07-06T17:29:35+00:00",
  "source": "https://directory.cbck.or.kr/OnlineAddress/SearchList.aspx",
  "count": 1789,
  "churches": [ { …성당 객체… } ]
}
```

성당 객체 필드 (원문 라벨 → JSON 키):

| 원문 라벨 | JSON 키 | 타입 | 설명 |
|-----------|---------|------|------|
| (내부 code) | `id` | string | 성당 고유 ID |
| 한글명칭 | `name` | string | 성당 이름 |
| 소속 | `diocese` | string | 소속 교구 |
| (내부 gyogu) | `diocese_id` | string | 교구 ID |
| 지역/지구 (앞) | `region` | string\|null | 지역 (없으면 null) |
| 지역/지구 (뒤) | `district` | string\|null | 지구 |
| 대표주소 (우편번호) | `postal_code` | string\|null | 5자리 우편번호 |
| 대표주소 (주소) | `address` | string\|null | 우편번호 제외 주소 |
| 대표 전화 번호 | `phone` | string\|null | |
| 팩스번호 | `fax` | string\|null | |
| 주임신부 (한글) | `pastor` | string\|null | |
| 주임신부 (영문) | `pastor_en` | string\|null | |
| 설립일 | `established` | string\|null | 원문 표기(예: `2005.1.20`) |
| 설립일 | `established_date` | string\|null | ISO 8601(예: `2005-01-20`), 파싱 실패 시 null |
| 주보 | `patron` | string\|null | |
| 신자수 | `believers` | int\|null | |
| 공소수 | `mission_stations` | int\|null | |
| (상세 페이지 URL) | `source_url` | string | 원본 링크 |

### 주소 정규화 필드 (VWorld)

원본 `address` 를 [VWorld(브이월드) 지오코더](https://www.vworld.kr)로 정규화하여
아래 필드를 추가로 채웁니다. (키 미설정 시 이 필드들은 `null`, `geocode_status="skipped"`)

| JSON 키 | 타입 | 설명 |
|---------|------|------|
| `road_address` | string\|null | 공식 정규 도로명주소(건물번호까지) |
| `address_detail` | string\|null | 원본에서 분리한 층·호·사서함 등 상세 |
| `sido` / `sigungu` | string\|null | 시도 / 시군구 |
| `legal_dong` | string\|null | 법정동 |
| `admin_dong` / `admin_dong_code` | string\|null | 행정동 / 행정동코드 |
| `road_name` / `building_no` | string\|null | 도로명 / 건물번호 |
| `lat` / `lng` | float\|null | 위도 / 경도 (WGS84, EPSG:4326) |
| `geocode_status` | string | `matched`(좌표 확보) / `refined_only` / `failed` / `skipped` |

> **주소 캐시:** 정규화 결과는 `data/_cache/address_cache.json`(원본 주소 → 정규화)에
> 저장되어 커밋됩니다. 주소는 거의 바뀌지 않으므로 **최초 1회만 전량 조회**하고,
> 이후에는 신규·변경된 주소만 VWorld API 를 호출합니다. (일일 쿼터/부하 최소화)

> **키 이름 관련:** 도구 호환성과 관례를 위해 영문 snake_case 키를 사용했습니다.
> 한글 키를 원하시면 `scraper/scrape.py`의 `parse_church()`에서 바꿀 수 있습니다.

## 수집 주기

`.github/workflows/scrape.yml` 의 cron 으로 **매일 05:00 KST(20:00 UTC)** 실행됩니다.
주기를 바꾸려면 cron 식을 수정하세요. Actions 탭에서 **Run workflow** 로 수동 실행도 가능합니다.

## 주소 정규화 설정 (VWorld 키)

1. [vworld.kr](https://www.vworld.kr) 가입 → **인증키 발급** → 지오코더 API 2.0 선택.
   발급 시 **서비스 URL(도메인)** 을 등록해야 합니다.
   - 로컬만 쓰면 `http://localhost` 등록 후 `.env` 의 `VWORLD_REFERER` 에 동일 값 입력.
2. **로컬:** 저장소 루트의 `.env` 파일에 키를 넣습니다(커밋 안 됨).
   ```
   VWORLD_KEY=발급받은-인증키
   VWORLD_REFERER=            # 등록 도메인 Referer 검사가 있으면 입력
   ```
3. **GitHub Actions:** Settings → Secrets and variables → Actions →
   **New repository secret** 로 `VWORLD_KEY`(필요시 `VWORLD_REFERER`) 등록.
   워크플로우가 자동으로 주입합니다.

> 키가 없어도 스크레이퍼는 정상 동작하며, 좌표/공식 표준화만 생략됩니다(`geocode_status="skipped"`).

## 로컬 실행

```bash
pip install -r scraper/requirements.txt
python scraper/scrape.py            # 전체 수집 + 정규화 -> data/*.json
python scraper/scrape.py --limit 15 # 앞 15개만(검증용)
python scraper/scrape.py --workers 6
```

## 최초 배포 (한 번만)

```bash
cd catholic-church
git init
git add .
git commit -m "init: 성당 정보 수집 API"
git branch -M main
git remote add origin https://github.com/<USER>/<REPO>.git
git push -u origin main
```

이후 GitHub Actions 가 매일 자동으로 데이터를 갱신·커밋합니다.
(Actions 가 push 하려면 Settings → Actions → General → Workflow permissions 를
**Read and write permissions** 로 설정하세요.)

## 참고 / 유의사항

- 본 저장소는 공개된 주소록 정보를 개인·비상업 목적으로 수집합니다.
  재배포·상업적 이용 시에는 출처(CBCK) 정책을 확인하세요.
- 사이트에 부담을 주지 않도록 동시 요청 수를 제한(기본 6)하고 있습니다.
- 원본 사이트의 HTML 구조가 바뀌면 파서 수정이 필요할 수 있습니다.
