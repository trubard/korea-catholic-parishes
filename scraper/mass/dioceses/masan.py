#!/usr/bin/env python3
"""마산교구 미사시간 어댑터 (큐레이션 맵 방식).

마산교구는 통합 본당 디렉토리가 없고 본당마다 독립 서브도메인({약칭}.cathms.kr)을
쓰며 미사 페이지 슬러그도 제각각이다. 따라서 아래 SITES 맵에 본당을 개별 등록해
구조화한다. 표(요일×시간대)가 있는 본당만 파싱하고, 미사시간을 이미지로 올린 본당은
표가 없어 자동 스킵된다. 새 본당은 SITES 에 (본당명: (서브도메인, 미사페이지경로))
한 줄을 추가하면 수집 대상이 된다.
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from base import MassAdapter, korean_to_hhmm, normalize_mass

# 본당명: (서브도메인, 미사페이지 경로).
# CBCK 상세의 홈페이지 필드에서 마산 본당 홈페이지 52개(cathms 서브도메인 36개)를 수집하고,
# 각 사이트의 미사 페이지 중 '요일' 표가 있는 본당을 등록했다. 미사시간을 이미지/게시글로만
# 올린 본당은 표가 없어 자동 스킵된다. (page_* 는 고정 메뉴, board_*/movie 는 게시글 기반이라
# 재게시 시 경로가 바뀔 수 있음 — 끊기면 해당 본당만 스킵된다.)
SITES = {
    "가좌동": ("gajwa", "/xe/board_oCOh74/13788"),
    "거창": ("geo", "/xe/page_foxn59"),
    "고현": ("goh", "/xe/page_Awcw22"),
    "망경동": ("mk", "/xe/board_LuAU21/25930"),
    "명서동": ("ms", "/xe/churh9"),
    "남성동": ("namsung", "/xe/board_LuAU21/8839"),
    "북신동": ("bsd", "/xe/board_Yuex31/8553"),
    "산호동": ("san", "/xe/board_LuAU21/16598"),
    "장평": ("jp", "/xe/movie/39148"),
    "진동": ("jin", "/xe/board_LuAU21/7150"),
    "산청": ("sanc", "/xe/board_Yuex31/10006"),
    "상평동": ("sp", "/xe/board_Yuex31/10769"),
    "장승포": ("jsp", "/xe/board_LuAU21/27254"),
    "중동": ("jd", "/xe/board_LuAU21/8859"),
    "진영": ("jy", "/xe/board_Yuex31/7649"),
    "하대동": ("had", "/xe/page_JcrW79"),
    "함양": ("ham", "/xe/board_Yuex31/5378"),
    "합천": ("hap", "/xe/board_mnPW66/15692"),
    "회원동": ("hw", "/xe/page_MNku90"),
}
_DAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri",
        "토": "saturday", "주일": "sunday", "일": "sunday"}


def _parse_mass_table(table) -> dict:
    """표에서 (요일행+시간) 을 {mon: 'HH:MM ...'} 로. 미사표가 아니면 빈 dict.

    한글시간(오전/오후)·다중요일(예: '수, 목, 금')도 처리.
    """
    kmap: dict[str, str] = {}
    for tr in table.find_all("tr"):
        cells = [re.sub(r"\s+", " ", korean_to_hhmm(c.get_text(" ", strip=True)))
                 for c in tr.find_all(["th", "td"])]
        if not cells:
            continue
        c0 = cells[0].replace("요일", "")
        keys = []
        if "주일" in c0:
            keys.append("sunday")
        for ch in ("월", "화", "수", "목", "금", "토"):
            if ch in c0:
                keys.append(_DAY[ch])
        if not keys and "일" in c0:
            keys.append("sunday")
        if not keys:
            continue
        times = " ".join(c for c in cells[1:] if re.search(r"\d{1,2}:\d{2}", c))
        if times:
            for k in keys:
                kmap[k] = (kmap.get(k, "") + " " + times).strip()
    return kmap


def _get(session, url):
    r = session.get(url, timeout=15, verify=False)
    r.raise_for_status()
    for enc in ("utf-8", "euc-kr"):
        try:
            t = r.content.decode(enc)
            if "미사" in t or "요일" in t:
                return BeautifulSoup(t, "html.parser")
        except UnicodeDecodeError:
            pass
    return BeautifulSoup(r.content.decode("utf-8", "replace"), "html.parser")


class MasanAdapter(MassAdapter):
    diocese = "마산교구"

    def collect(self, session: requests.Session) -> list[dict]:
        records: list[dict] = []
        for name, (sub, path) in SITES.items():
            url = f"http://{sub}.cathms.kr{path}"
            try:
                soup = _get(session, url)
            except Exception:  # noqa: BLE001
                continue
            # 요일 행이 가장 많은 표를 미사표로 선택(교리 일정표 등 오매칭 방지)
            kmap: dict[str, str] = {}
            for table in soup.find_all("table"):
                km = _parse_mass_table(table)
                if len(km) > len(kmap):
                    kmap = km
            if len(kmap) < 3:
                continue  # 미사표 없음(이미지/게시글 등) → 스킵
            mass = normalize_mass(
                weekday_cells={d: kmap.get(d, "") for d in
                               ("mon", "tue", "wed", "thu", "fri")},
                saturday=kmap.get("saturday", ""), sunday=kmap.get("sunday", ""),
                raw="; ".join(f"{k} {v}" for k, v in kmap.items()))
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": None, "source_url": url, "mass": mass})
        return records
