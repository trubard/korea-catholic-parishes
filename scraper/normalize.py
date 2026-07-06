#!/usr/bin/env python3
"""
주소 정규화 모듈 (VWorld 지오코더 기반).

- split_detail(): 원본 주소에서 '정규 도로명주소(건물번호까지)'와
  '상세(층·호 등)', '법정동(괄호)' 을 분리한다.
- VWorldClient.getcoord(): 브이월드 지오코더로 정규 도로명주소 + 위경도 획득.
- normalize(): 캐시를 이용해 신규/변경 주소만 API 로 조회.

VWORLD_KEY 환경변수가 없으면 API 호출 없이 split_detail 결과만 채운다
(좌표/공식 표준화는 생략, 파이프라인은 정상 동작).
"""
from __future__ import annotations

import os
import re
import time

import requests

VWORLD_URL = "https://api.vworld.kr/req/address"

# ---------------------------------------------------------------- 상세 분리

# 도로명(로/길로 끝남) + 그 뒤의 건물본번(-부번). 도로명 자체에 숫자가 들어가는
# 'X로NN번길' 형태를 위해, '로/길' 뒤에 '숫자'가 바로 오는 마지막 위치를 건물번호로 본다.
# 예: '금화로73번길 33' -> 도로명='금화로73번길', 건물번호='33'
#     '태평4길 11 - 6'   -> 도로명='태평4길',     건물번호='11-6'
_ROAD_RE = re.compile(r"^(.*(?:로|길))\s*(\d+(?:\s*[-–]\s*\d+)?)(.*)$")
# 괄호 안이 법정동/리/가 로 끝나면 법정동으로 간주. 예: '(가음동)', '(남가좌동)'
_DONG_PAREN_RE = re.compile(r"\(([가-힣0-9·]+(?:동|리|가))\)")


def split_detail(raw: str) -> dict:
    """원본 주소 -> {base, detail, legal_dong}.

    base       : VWorld 에 보낼 정규 도로명주소(건물번호까지)
    detail     : 층/호 등 상세 (없으면 None)
    legal_dong : 괄호 법정동 (없으면 None)
    """
    if not raw:
        return {"base": None, "detail": None, "legal_dong": None}

    text = re.sub(r"\s+", " ", raw).strip()

    legal_dong = None
    m = _DONG_PAREN_RE.search(text)
    if m:
        legal_dong = m.group(1)
        text = (text[: m.start()] + " " + text[m.end():]).strip()

    m = _ROAD_RE.match(text)
    if m:
        road = m.group(1).strip()
        # 건물번호 부번 표기 정리: '11 - 6' -> '11-6'
        building = re.sub(r"\s*[-–]\s*", "-", m.group(2).strip())
        detail = m.group(3).strip(" ,")
        base = f"{road} {building}"
        return {"base": base, "detail": detail or None, "legal_dong": legal_dong}

    # 도로명 패턴이 없으면(지번 등) 통째로 base 로 두고 API 의 정제에 맡긴다.
    return {"base": text or None, "detail": None, "legal_dong": legal_dong}


# ---------------------------------------------------------------- VWorld


class VWorldClient:
    def __init__(self, key: str, referer: str | None = None,
                 session: requests.Session | None = None, delay: float = 0.0):
        self.key = key
        self.session = session or requests.Session()
        self.delay = delay
        self.headers = {"Referer": referer} if referer else {}

    def getcoord(self, address: str, addr_type: str = "road") -> dict | None:
        """정규 도로명주소 + 위경도 조회. 실패 시 None.

        addr_type: 'road'(도로명) 또는 'parcel'(지번).
        """
        params = {
            "service": "address",
            "request": "getcoord",
            "version": "2.0",
            "crs": "epsg:4326",
            "type": addr_type,
            "refine": "true",
            "simple": "false",
            "format": "json",
            "address": address,
            "key": self.key,
        }
        if self.delay:
            time.sleep(self.delay)
        r = self.session.get(VWORLD_URL, params=params,
                             headers=self.headers, timeout=30)
        r.raise_for_status()
        data = r.json().get("response", {})
        if data.get("status") != "OK":
            return None

        refined = data.get("refined", {}) or {}
        struct = refined.get("structure", {}) or {}
        point = (data.get("result", {}) or {}).get("point", {}) or {}
        try:
            lat = float(point["y"])
            lng = float(point["x"])
        except (KeyError, TypeError, ValueError):
            lat = lng = None

        # VWorld getcoord(road) structure:
        #   level1=시도, level2=시군구, level3=법정동,
        #   level4A=행정동, level4AC=행정동코드, level4L=도로명, level5=건물번호
        return {
            "road_address": refined.get("text") or None,
            "sido": struct.get("level1") or None,
            "sigungu": struct.get("level2") or None,
            "legal_dong": struct.get("level3") or None,
            "admin_dong": struct.get("level4A") or None,
            "admin_dong_code": struct.get("level4AC") or None,
            "road_name": struct.get("level4L") or None,
            "building_no": struct.get("level5") or None,
            "lat": lat,
            "lng": lng,
        }


# ---------------------------------------------------------------- 정규화


EMPTY = {
    "road_address": None, "address_detail": None, "legal_dong": None,
    "sido": None, "sigungu": None, "road_name": None, "building_no": None,
    "admin_dong": None, "admin_dong_code": None,
    "lat": None, "lng": None, "geocode_status": "skipped",
}


def normalize(raw: str, client: VWorldClient | None, cache: dict) -> dict:
    """원본 주소를 정규화한다. client 가 None 이면 split 결과만 채운다.

    cache: {raw_address: normalized_dict} — 신규 주소만 API 조회.
    """
    if not raw:
        return dict(EMPTY, geocode_status="no_address")
    if raw in cache:
        return cache[raw]

    parts = split_detail(raw)
    out = dict(EMPTY)
    out["address_detail"] = parts["detail"]
    out["legal_dong"] = parts["legal_dong"]

    # 키가 없으면 캐시에 남기지 않는다(나중에 키가 생기면 지오코딩되도록).
    if client is None or not parts["base"]:
        out["geocode_status"] = "skipped"
        return out

    geo = None
    try:
        geo = client.getcoord(parts["base"], "road")
        if geo is None:  # 도로명 실패 시 지번으로 재시도
            geo = client.getcoord(parts["base"], "parcel")
    except Exception:  # noqa: BLE001 - 개별 실패는 파이프라인을 막지 않음
        geo = None

    if geo is None:
        out["geocode_status"] = "failed"
    else:
        out.update({k: v for k, v in geo.items() if v is not None or k in ("lat", "lng")})
        # split 으로 얻은 법정동/상세는 API 값이 없을 때만 보존
        if not geo.get("legal_dong"):
            out["legal_dong"] = parts["legal_dong"]
        out["address_detail"] = parts["detail"]
        out["geocode_status"] = "matched" if out.get("lat") else "refined_only"

    cache[raw] = out
    return out
