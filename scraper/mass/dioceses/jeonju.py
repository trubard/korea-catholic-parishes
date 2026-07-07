#!/usr/bin/env python3
"""전주교구 미사시간 어댑터.

목록 church.php 의 churchview.php?intSeq=N 링크(텍스트=본당명) → 상세.
상세: 미사표 [요일 | 시간/시간(구분)]. 전화 있음.
"""
from __future__ import annotations

import re

import requests

from base import MassAdapter, get_soup, normalize_mass

BASE = "http://www.jcatholic.or.kr/theme/main/pages/"
JDAY = {"주일": "sunday", "월요일": "mon", "화요일": "tue", "수요일": "wed",
        "목요일": "thu", "금요일": "fri", "토요일": "saturday"}
_VIEW_RE = re.compile(r"churchview\.php\?intSeq=(\d+)(?:&strCategory=([^\"'&]*))?")
_PHONE_RE = re.compile(r"0\d{1,2}[-)]\s?\d{3,4}-\d{4}")


class JeonjuAdapter(MassAdapter):
    diocese = "전주교구"

    def collect(self, session: requests.Session) -> list[dict]:
        soup = get_soup(session, f"{BASE}church.php")
        # 목록은 <tr onClick="location.href='churchview.php?intSeq=..'"> 방식
        parishes = list(dict.fromkeys(
            _VIEW_RE.findall(str(soup))))  # [(seq, cat), ...]

        records: list[dict] = []
        for seq, cat in parishes:
            url = f"{BASE}churchview.php?intSeq={seq}&strCategory={cat}"
            try:
                s = get_soup(session, url)
            except Exception:  # noqa: BLE001
                continue
            h1 = s.find(["h1", "h2"], string=re.compile("성당"))
            if not h1:
                h1 = next((h for h in s.find_all(["h1", "h2"])
                           if "성당" in h.get_text()), None)
            name = ""
            if h1:
                name = re.sub(r"^\s*\S*지구\s*|\s*성당\s*$", "",
                              h1.get_text(" ", strip=True)).strip()
            if not name:
                continue
            kmap = {}
            for tr in s.find_all("tr"):
                cs = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if len(cs) == 2 and cs[0].strip() in JDAY:
                    kmap[JDAY[cs[0].strip()]] = cs[1]
            if not kmap:
                continue
            ph = _PHONE_RE.search(s.get_text(" ", strip=True))
            mass = normalize_mass(
                weekday_cells={d: kmap.get(d, "") for d in
                               ("mon", "tue", "wed", "thu", "fri")},
                saturday=kmap.get("saturday", ""), sunday=kmap.get("sunday", ""),
                raw="; ".join(f"{k} {v}" for k, v in kmap.items()))
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": ph.group(0) if ph else None, "source_url": url, "mass": mass})
        return records
