#!/usr/bin/env python3
"""
한국 천주교 성당 정보 수집기 (CBCK OnlineAddress).

목록 페이지(paged=2000)에서 전체 본당 링크를 한 번에 수집한 뒤,
각 성당 상세 페이지에 접근하여 지정된 항목을 파싱하고 data/*.json 으로 저장한다.

산출물:
  data/churches.json        전체 성당 배열 + 메타
  data/index.json           교구별 건수 요약 + 마지막 수집 시각
  data/by-diocese/<id>.json 교구(gyogu id)별 분할 파일

사용:
  python scraper/scrape.py                 # 전체 수집
  python scraper/scrape.py --limit 15      # 앞의 15개만 (검증용)
  python scraper/scrape.py --workers 6     # 동시 요청 수
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import normalize as norm

BASE = "https://directory.cbck.or.kr/OnlineAddress/"
LIST_URL = (
    BASE + "SearchList.aspx?cgubn=g&gubn=4&gyogu=all&tbxSearch="
    "&start=1&paged=2000&sort=0&gubn2=all&char=all"
)
USER_AGENT = (
    "catholic-church-directory-collector/1.0 "
    "(+https://github.com/; personal/non-commercial dataset)"
)

# data/ 는 이 파일 기준 상위 폴더의 data/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
CACHE_PATH = os.path.join(DATA_DIR, "_cache", "address_cache.json")
ENV_PATH = os.path.join(ROOT, ".env")

# 정규화로 각 성당에 추가되는 필드
NORM_FIELDS = (
    "road_address", "address_detail", "legal_dong",
    "sido", "sigungu", "admin_dong", "admin_dong_code", "road_name", "building_no",
    "lat", "lng", "geocode_status",
)


def load_env(path: str = ENV_PATH) -> None:
    """의존성 없는 최소 .env 로더. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=32)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    r = session.get(url, timeout=40)
    r.raise_for_status()
    # 사이트는 UTF-8 로 응답한다(헤더 charset=utf-8).
    html = r.content.decode("utf-8", errors="replace")
    return BeautifulSoup(html, "html.parser")


# ---------------------------------------------------------------- 목록 수집


def fetch_church_links(session: requests.Session) -> list[dict]:
    """목록 페이지에서 (name, id, diocese_id, url) 목록을 수집한다."""
    soup = get_soup(session, LIST_URL)
    seen: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "DetailInfo" not in href or "gubn=4" not in href:
            continue  # gubn=4 == 본당(성당)만
        abs_url = urljoin(BASE, href)
        q = parse_qs(urlparse(abs_url).query)
        code = (q.get("code") or [None])[0]
        gyogu = (q.get("gyogu") or [None])[0]
        if not code:
            continue
        seen[code] = {
            "id": code,
            "diocese_id": gyogu,
            "name": a.get_text(strip=True),
            "url": abs_url,
        }
    return list(seen.values())


# ---------------------------------------------------------------- 상세 파싱


def detail_fields(soup: BeautifulSoup) -> dict[str, str]:
    """상세 페이지의 <td>라벨</td><td>값</td> 행을 {라벨: 값} 으로 수집."""
    fields: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 2:
            tds = tr.find_all("td")
            if len(tds) != 2:
                continue
        label = tds[0].get_text(" ", strip=True)
        value = tds[1].get_text(" ", strip=True)
        if label and label not in fields:
            fields[label] = value
    return fields


_POSTAL_RE = re.compile(r"^\s*(\d{5})\s+(.*)$", re.S)


def split_address(raw: str) -> tuple[str | None, str | None]:
    """'28398  충청북도 ...' -> ('28398', '충청북도 ...')."""
    if not raw:
        return None, None
    raw = re.sub(r"\s+", " ", raw).strip()
    m = _POSTAL_RE.match(raw)
    if m:
        return m.group(1), m.group(2).strip()
    return None, raw or None


def split_region_district(raw: str) -> tuple[str | None, str | None]:
    """'- / 강서지구' -> (None, '강서지구'). '서울 / 중부' -> ('서울','중부')."""
    if not raw:
        return None, None
    parts = [p.strip() for p in raw.split("/")]
    region = parts[0] if len(parts) >= 1 else None
    district = parts[1] if len(parts) >= 2 else None
    norm = lambda x: None if (x is None or x in ("", "-")) else x
    return norm(region), norm(district)


def split_pastor(raw: str) -> tuple[str | None, str | None]:
    """'홍진 베드로 신부 Rev.Petrus Hong Jin' -> ('홍진 베드로 신부', 'Rev.Petrus Hong Jin')."""
    if not raw:
        return None, None
    raw = raw.strip()
    m = re.search(r"\bRev\.", raw)
    if m:
        ko = raw[: m.start()].strip()
        en = raw[m.start():].strip()
        return (ko or None), (en or None)
    return (raw or None), None


def to_int(raw: str) -> int | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def to_iso_date(raw: str) -> str | None:
    """'2005.1.20.' 또는 '1993.02.18' -> '2005-01-20'. 파싱 실패 시 None."""
    if not raw:
        return None
    m = re.match(r"\s*(\d{4})\D+(\d{1,2})\D+(\d{1,2})", raw)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d).strftime("%Y-%m-%d")
    except ValueError:
        return None


def clean_established(raw: str) -> str | None:
    if not raw:
        return None
    return raw.strip().rstrip(".") or None


def parse_church(session: requests.Session, item: dict) -> dict:
    soup = get_soup(session, item["url"])
    f = detail_fields(soup)

    postal, address = split_address(f.get("대표주소", ""))
    region, district = split_region_district(f.get("지역/지구", ""))
    pastor_ko, pastor_en = split_pastor(f.get("주임신부", ""))
    established_raw = clean_established(f.get("설립일", ""))

    return {
        "id": item["id"],
        "name": f.get("한글명칭") or item["name"],
        "diocese": f.get("소속") or None,
        "diocese_id": item["diocese_id"],
        "region": region,
        "district": district,
        "postal_code": postal,
        "address": address,
        "phone": f.get("대표 전화 번호") or None,
        "fax": f.get("팩스번호") or None,
        "pastor": pastor_ko,
        "pastor_en": pastor_en,
        "established": established_raw,
        "established_date": to_iso_date(established_raw or ""),
        "patron": f.get("주보") or None,
        "believers": to_int(f.get("신자수", "")),
        "mission_stations": to_int(f.get("공소수", "")),
        "source_url": item["url"],
    }


# ---------------------------------------------------------------- 저장


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=2, sort_keys=False)
        fp.write("\n")


def load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as fp:
                return json.load(fp)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(cache: dict) -> None:
    write_json(CACHE_PATH, cache)


def normalize_addresses(session: requests.Session, churches: list[dict]) -> str:
    """각 성당 주소를 정규화(VWorld)한다. 캐시로 신규 주소만 조회.

    반환: 사람이 읽을 요약 문자열.
    """
    key = os.environ.get("VWORLD_KEY")
    client = None
    if key:
        client = norm.VWorldClient(
            key,
            referer=os.environ.get("VWORLD_REFERER") or None,
            session=session,
            delay=0.05,
        )

    cache = load_cache()
    before = len(cache)
    counts = {"matched": 0, "refined_only": 0, "failed": 0, "skipped": 0,
              "no_address": 0}
    for i, c in enumerate(churches, 1):
        result = norm.normalize(c.get("address"), client, cache)
        for f in NORM_FIELDS:
            c[f] = result.get(f)
        counts[result.get("geocode_status", "skipped")] = \
            counts.get(result.get("geocode_status", "skipped"), 0) + 1
        if client and i % 200 == 0:
            print(f"      정규화 {i}/{len(churches)} ...", flush=True)

    if client:
        save_cache(cache)

    new_calls = len(cache) - before
    if not key:
        return ("VWORLD_KEY 없음 → 좌표/공식 표준화 생략(상세 분리만 적용). "
                ".env 에 키를 넣으면 다음 실행부터 지오코딩됩니다.")
    return (f"정규화 완료 (신규 API 조회 {new_calls}건, 캐시 {before}건) | "
            f"matched={counts['matched']} refined_only={counts['refined_only']} "
            f"failed={counts['failed']}")


def save_outputs(churches: list[dict], generated_at: str) -> None:
    # 안정적인 diff 를 위해 id 기준 정렬
    churches.sort(key=lambda c: (c.get("diocese") or "", c.get("name") or "", c["id"]))

    meta = {
        "generated_at": generated_at,
        "source": "https://directory.cbck.or.kr/OnlineAddress/SearchList.aspx",
        "count": len(churches),
    }
    write_json(os.path.join(DATA_DIR, "churches.json"),
               {**meta, "churches": churches})

    # 교구별 분할 (diocese_id 기준)
    by: dict[str, list[dict]] = {}
    for c in churches:
        by.setdefault(c.get("diocese_id") or "unknown", []).append(c)
    for gid, group in by.items():
        write_json(
            os.path.join(DATA_DIR, "by-diocese", f"{gid}.json"),
            {**meta, "diocese_id": gid,
             "diocese": group[0].get("diocese"),
             "count": len(group), "churches": group},
        )

    # 인덱스(교구별 요약)
    diocese_summary: dict[str, dict] = {}
    for c in churches:
        key = c.get("diocese") or "미상"
        s = diocese_summary.setdefault(
            key, {"diocese": key, "diocese_id": c.get("diocese_id"), "count": 0})
        s["count"] += 1
    write_json(
        os.path.join(DATA_DIR, "index.json"),
        {**meta,
         "dioceses": sorted(diocese_summary.values(),
                            key=lambda x: x["count"], reverse=True)},
    )


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="상세 페이지를 앞에서 N개만 수집(검증용). 0=전체")
    ap.add_argument("--workers", type=int, default=6,
                    help="동시 요청 수 (기본 6)")
    args = ap.parse_args()

    load_env()
    session = make_session()
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"[1/4] 목록 수집 중 ... ({LIST_URL})", flush=True)
    links = fetch_church_links(session)
    print(f"      본당 링크 {len(links)}건 확보", flush=True)
    if args.limit:
        links = links[: args.limit]
        print(f"      --limit 적용: {len(links)}건만 수집", flush=True)

    print(f"[2/4] 상세 페이지 수집 중 (workers={args.workers}) ...", flush=True)
    churches: list[dict] = []
    errors = 0
    t0 = time.time()
    with futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        fut_map = {ex.submit(parse_church, session, it): it for it in links}
        for i, fut in enumerate(futures.as_completed(fut_map), 1):
            it = fut_map[fut]
            try:
                churches.append(fut.result())
            except Exception as e:  # noqa: BLE001
                errors += 1
                print(f"      [ERR] {it['name']} ({it['id']}): {e}",
                      file=sys.stderr, flush=True)
            if i % 100 == 0 or i == len(links):
                print(f"      {i}/{len(links)} ...", flush=True)

    dt = time.time() - t0
    print(f"      완료: 성공 {len(churches)}, 실패 {errors}, {dt:.1f}s", flush=True)

    if not churches:
        print("      수집 결과가 비어 있어 저장을 중단합니다.", file=sys.stderr)
        return 1

    print("[3/4] 주소 정규화(VWorld) 중 ...", flush=True)
    summary = normalize_addresses(session, churches)
    print(f"      {summary}", flush=True)

    print("[4/4] JSON 저장 중 ...", flush=True)
    save_outputs(churches, generated_at)
    print(f"      저장 완료 -> {DATA_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
