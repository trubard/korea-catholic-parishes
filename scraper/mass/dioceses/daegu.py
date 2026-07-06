#!/usr/bin/env python3
"""대구대교구 미사시간 어댑터.

목록 area.html?srl=church_search → 상세 ...&menu=c4&number={N}&y_id={ID}.
WAF(WebKnight) 회피: 홈 방문으로 세션 쿠키 확보 + 브라우저 UA/Referer.
미사시간은 자유 텍스트: '[주일미사] 토요일 - 오후 4:00(...) 주일 - 오전 6:30 ...
[평일미사] 오전 월-토 6:30 화-금 11:30'. 오전/오후·요일범위를 해석.
원문은 raw 에 보존.
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from base import MassAdapter, normalize_mass

BASE = "http://www.daegu-archdiocese.or.kr/"
LIST_URL = BASE + "page/area.html?srl=church_search"
DETAIL = BASE + "page/area.html?srl=church_search&menu=c4&number={number}&y_id={y_id}"
DAYS = ["월", "화", "수", "목", "금", "토"]
KDAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri"}
_LINK_RE = re.compile(r"number=(\d+)&y_id=(\d+)")
_PHONE_RE = re.compile(r"0\d{1,2}[-)]\s?\d{3,4}-\d{4}")


def _to24(hh: int, ampm: str) -> int:
    if ampm == "오후" and hh < 12:
        return hh + 12
    if ampm == "오전" and hh == 12:
        return 0
    return hh


def _parse_times(seg: str) -> list[str]:
    """'오전 6:30 8:30 오후 4:00(청년)' -> ['06:30','08:30','16:00 청년'] 형태 텍스트."""
    ampm = "오전"
    out = []
    i = 0
    for m in re.finditer(r"(오전|오후)|(\d{1,2}):(\d{2})(\s*\([^)]*\))?", seg):
        if m.group(1):
            ampm = m.group(1)
            continue
        hh = _to24(int(m.group(2)), ampm)
        note = (m.group(4) or "").strip("() ")
        t = f"{hh:02d}:{m.group(3)}"
        out.append(f"{t} {note}".strip() if note else t)
    return out


def parse_daegu_mass(text: str) -> dict:
    text = " ".join(text.split())
    weekday = {v: [] for v in KDAY.values()}
    sat, sun = [], []

    sun_sec = re.search(r"\[주일미사\](.*?)(?:\[평일미사\]|$)", text)
    if sun_sec:
        s = sun_sec.group(1)
        mt = re.search(r"토요일\s*-?\s*(.*?)(?:주일|$)", s)
        if mt:
            sat = _parse_times(mt.group(1))
        mj = re.search(r"주일\s*-?\s*(.*)$", s)
        if mj:
            sun = _parse_times(mj.group(1))

    wk_sec = re.search(r"\[평일미사\](.*)$", text)
    if wk_sec:
        s = wk_sec.group(1)
        # '오전 월-토 6:30', '월 11:00(...)', '화-금 11:30' 조각을 요일범위+시간으로
        for m in re.finditer(r"(오전|오후)?\s*([월화수목금토])(?:\s*-\s*([월화수목금토]))?\s*"
                             r"((?:\d{1,2}:\d{2}(?:\([^)]*\))?\s*)+)", s):
            ampm = m.group(1) or "오전"
            d1, d2 = m.group(2), m.group(3)
            times = _parse_times(ampm + " " + m.group(4))
            i1 = DAYS.index(d1)
            i2 = DAYS.index(d2) if d2 else i1
            for d in DAYS[i1:i2 + 1]:
                if d == "토":
                    sat = sat or times
                else:
                    weekday[KDAY[d]] = times

    return normalize_mass(
        weekday_cells={k: " ".join(v) for k, v in weekday.items()},
        saturday=" ".join(sat), sunday=" ".join(sun), raw=text)


class DaeguAdapter(MassAdapter):
    diocese = "대구대교구"

    def _session(self, session):
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml", "Accept-Language": "ko-KR,ko;q=0.9",
        })
        try:
            session.get(BASE, timeout=30)  # 쿠키 확보
        except Exception:  # noqa: BLE001
            pass

    def collect(self, session: requests.Session) -> list[dict]:
        self._session(session)
        ref = {"Referer": LIST_URL}
        r = session.get(LIST_URL, headers=ref, timeout=40)
        soup = BeautifulSoup(r.content.decode("utf-8", "replace"), "html.parser")
        pairs = []
        seen = set()
        for a in soup.find_all("a", href=_LINK_RE):
            num, yid = _LINK_RE.search(a["href"]).groups()
            name = " ".join(a.get_text(" ", strip=True).split())
            if (num, yid) not in seen:
                seen.add((num, yid))
                pairs.append((num, yid, name))

        records: list[dict] = []
        for num, yid, name in pairs:
            url = DETAIL.format(number=num, y_id=yid)
            try:
                d = session.get(url, headers=ref, timeout=40)
                body = d.content.decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
            if "WebKnight" in body:
                continue
            s = BeautifulSoup(body, "html.parser")
            txt = " ".join(s.get_text(" ", strip=True).split())
            idx = txt.find("[주일미사]")
            if idx < 0:
                continue
            # 미사 블록: [주일미사] 부터 관할구역/성사/교리 등 다음 섹션 전까지
            tail = txt[idx:]
            end = len(tail)
            for stop in ("관할구역", "관할 구역", "성사", "교리", "본당 연혁", "오시는"):
                p = tail.find(stop, 10)
                if 0 < p < end:
                    end = p
            block = tail[:end]
            ph = _PHONE_RE.search(txt)
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": ph.group(0) if ph else None, "source_url": url,
                "mass": parse_daegu_mass(block),
            })
        return records
