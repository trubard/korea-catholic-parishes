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
| `source_url` | string | 원본 상세 페이지 |

**정규화 주소 필드** (원본 주소를 공식 도로명주소로 정규화)

| 키 | 타입 | 설명 |
|----|------|------|
| `road_address` | string\|null | 정규 도로명주소 |
| `address_detail` | string\|null | 층·호·사서함 등 상세 |
| `lat` / `lng` | float\|null | 위도 / 경도 (WGS84) |
| `geocode_status` | string | `matched`(좌표 확보) / `refined_only` / `failed` / `skipped` |

> 군부대·사서함 등 일부 주소는 좌표를 얻을 수 없어 `geocode_status`가 `failed`이며,
> 이 경우에도 원본 `address`는 그대로 제공됩니다.
> 좌표가 필요한 데이터만 쓰려면 `geocode_status === "matched"` 로 필터링하세요.

## 업데이트

매일 1회 자동으로 최신 정보를 반영합니다.

## 유의사항

공개된 주소록 정보를 개인·비상업 목적으로 수집합니다.
재배포·상업적 이용 시에는 출처([CBCK](https://directory.cbck.or.kr)) 정책을 확인하세요.
