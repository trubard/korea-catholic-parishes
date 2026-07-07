# 한국 천주교 성당 정보 API

한국 천주교 주소록([CBCK](https://directory.cbck.or.kr/OnlineAddress/SearchList.aspx))의
본당(성당) 정보를 **매일 자동으로 수집**하여 JSON으로 제공합니다.
전국 약 1,800개 성당의 기본 정보와 **정규화된 도로명주소·위경도 좌표**를 담고 있습니다.

## API

별도 인증 없이 아래 URL에서 JSON을 바로 내려받을 수 있습니다.

| 엔드포인트 | 내용 |
|-----------|------|
| [`data/churches.json`](https://raw.githubusercontent.com/trubard/korea-catholic-parishes/main/data/churches.json) | 전체 성당 목록 |
| [`data/index.json`](https://raw.githubusercontent.com/trubard/korea-catholic-parishes/main/data/index.json) | 교구별 건수 요약, 마지막 수집 시각 |
| `data/by-diocese/<diocese_id>.json` | 특정 교구 성당만 |

```
https://raw.githubusercontent.com/trubard/korea-catholic-parishes/main/data/churches.json
```

### 사용 예시

```bash
curl https://raw.githubusercontent.com/trubard/korea-catholic-parishes/main/data/churches.json
```

```js
const res = await fetch(
  "https://raw.githubusercontent.com/trubard/korea-catholic-parishes/main/data/churches.json"
);
const { churches } = await res.json();
```

```python
import requests
url = "https://raw.githubusercontent.com/trubard/korea-catholic-parishes/main/data/churches.json"
churches = requests.get(url).json()["churches"]
```

## 응답 형식

```json
{
  "generated_at": "2026-07-07T05:00:00+00:00",
  "source": "https://directory.cbck.or.kr/OnlineAddress/SearchList.aspx",
  "count": 1789,
  "churches": [ { …성당 객체… } ]
}
```

### 성당 객체 필드

| 키 | 타입 | 설명 |
|----|------|------|
| `id` | string | 성당 고유 ID |
| `name` | string | 성당 이름(한글) |
| `diocese` | string | 소속 교구 |
| `diocese_id` | string | 교구 ID |
| `region` | string\|null | 지역 |
| `district` | string\|null | 지구 |
| `postal_code` | string\|null | 우편번호 |
| `address` | string\|null | 표시용 주소 = 정규 도로명주소 + 상세(층·호 등). 지오코딩 미매칭 시 원본 주소 |
| `phone` | string\|null | 대표 전화번호 |
| `fax` | string\|null | 팩스번호 |
| `pastor` | string\|null | 주임신부 |
| `established_date` | string\|null | 설립일(ISO, 예 `2005-01-20`) |
| `patron` | string\|null | 주보 |
| `believers` | int\|null | 신자수 |
| `mission_stations` | int\|null | 공소수 |
| `lat` / `lng` | float\|null | 위도 / 경도 (WGS84) |
| `geocode_status` | string | `matched`(좌표 확보) / `refined_only` / `failed` / `skipped` |
| `source_url` | string | 원본 상세 페이지 |

> 군부대·사서함 등 일부 주소는 좌표를 얻을 수 없어 `geocode_status`가 `failed`이며,
> 이 경우에도 원본 `address`는 그대로 제공됩니다.
> 좌표가 필요한 데이터만 쓰려면 `geocode_status === "matched"` 로 필터링하세요.

## 미사시간 API

각 교구 홈페이지에서 본당 미사시간을 수집하여 별도로 제공합니다. 성당과는 `church_id`
(= 성당의 `id`)로 연결됩니다.

| 엔드포인트 | 내용 |
|-----------|------|
| [`data/mass.json`](https://raw.githubusercontent.com/trubard/korea-catholic-parishes/main/data/mass.json) | 전체 본당 미사시간 |
| `data/mass/<diocese_id>.json` | 교구별 미사시간 |

미사 레코드:

```json
{
  "church_id": "201001479",       // 성당 id (조인 실패 시 null)
  "parish_name": "노형 삼위일체",
  "diocese": "제주교구",
  "source_url": "https://...",
  "mass": {
    "weekday": { "mon": [ {"time": "06:30"} ], "tue": [...], ... },
    "saturday": [ {"time": "19:30", "note": "청소년", "type": ["청소년"]} ],
    "sunday":   [ {"time": "11:00", "note": "교중", "type": ["교중"]} ],
    "special": [],
    "raw": "원문 텍스트"
  },
  "stations": [                    // 공소(선택) — 소스가 공소 미사를 구분 제공할 때만
    { "name": "한림", "address": "경남 김해시 …", "mass": { … } }
  ]
}
```

> **공소(`stations`)**: 성당코드(`church_id`)는 본당에만 부여되고 공소는 별도 id가 없어,
> 본당 레코드 안에 `stations` 배열(이름·주소·미사)로 중첩합니다. 소스가 공소 미사를
> 명시적으로 구분할 때만 존재합니다(대다수 본당은 없음).

각 미사 항목(entry) 필드:

| 키 | 설명 |
|----|------|
| `time` | `HH:MM` (24시간제) |
| `note` | 원문 비고(대상·장소·조건 등 원문 그대로) |
| `type` | 미사 성격 분류: `교중·새벽·어린이·학생·청소년·청년·가족·특전·성시간` 등 (리스트, 감지 시) |
| `recurrence` | 주기 조건(감지 시): `weeks`(해당 주차에만, 1=첫째, -1=마지막) / `weeks_exclude`(제외) / `months`·`months_exclude` / `season`(`summer`·`winter`) |

> `type`·`recurrence`는 감지된 경우에만 존재하며, 없으면 매주 정규 미사로 간주합니다.
> `raw`(원문)는 항상 보존되므로 미분류 정보도 손실되지 않습니다.

**수집 교구 (16개 교구):** 서울대·인천·수원·의정부·춘천·원주·대전·청주·대구대·부산·마산·안동·전주·광주대·군종·제주.
교구마다 홈페이지 구조가 달라 교구별 어댑터(`scraper/mass/dioceses/`)로 수집합니다.
미수집 본당과 사유는 [`data/mass_uncovered.json`](data/mass_uncovered.json) 참고.

> **마산교구**는 통합 본당 목록이 없고 본당별 독립 사이트를 써서, 교구 본당목록에서
> 홈페이지를 수집해 `dioceses/masan.py`의 맵으로 개별 수집합니다. 특수 형식은 선택적
> 의존성(`scraper/requirements-ocr.txt`)으로 처리합니다:
> **이미지(base64) 미사표 → OCR**(easyocr), **JS 위젯 미사표 → 헤드리스 렌더링**(playwright).
> 미설치 시 해당 본당만 스킵되고 나머지 수집은 정상 동작합니다.
> (다음·네이버 카페를 쓰는 본당은 로그인이 필요해 제외.)

## 업데이트

성당 정보는 매일, 미사시간은 매주 자동으로 최신 정보를 반영합니다.

## 유의사항

공개된 주소록 정보를 개인·비상업 목적으로 수집합니다.
재배포·상업적 이용 시에는 출처([CBCK](https://directory.cbck.or.kr)) 정책을 확인하세요.
