#!/usr/bin/env python3
"""안동교구 미사시간 어댑터.

목록 sub3/sub1.asp(4페이지)의 <li> 에서 본당명·전화·seq 를 얻고,
상세 sub1_view.asp?seq=N 의 자바스크립트 변수(summerSeason/winterSeason)에서
미사시간을 파싱한다. 표는 JS로 채워져 비어 보이므로 원본 JS 변수를 직접 읽는다.
값 형식: '|화|수|목|금|토|일' (앞의 빈칸=월). '동일'=하절기와 동일.
"""
from __future__ import annotations

import re

import requests

BASE = "https://www.acatholic.or.kr/sub3/"
REF = {"Referer": BASE + "sub1.asp"}
DAYS = ("월", "화", "수", "목", "금", "토", "일")
DKEY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri",
        "토": "saturday", "일": "sunday"}
_SEQ_RE = re.compile(r"sub1_view\.asp\?seq=(\d+)")
_NAME_RE = re.compile(r"([가-힣0-9]+)성당")
_PHONE_RE = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")

from base import MassAdapter, normalize_mass  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402


class AndongAdapter(MassAdapter):
    diocese = "안동교구"

    def _html(self, session, url):
        r = session.get(url, headers=REF, timeout=20, verify=False)
        r.raise_for_status()
        return r.content.decode("utf-8", "replace")

    def collect(self, session: requests.Session) -> list[dict]:
        # 목록: (seq, 본당명, 전화)
        parishes = []
        seen = set()
        for pg in range(1, 8):
            try:
                soup = BeautifulSoup(self._html(session, f"{BASE}sub1.asp?page={pg}"),
                                     "html.parser")
            except Exception:  # noqa: BLE001
                break
            found = 0
            for li in soup.find_all("li"):
                a = li.find("a", href=_SEQ_RE)
                if not a:
                    continue
                seq = _SEQ_RE.search(a["href"]).group(1)
                if seq in seen:
                    continue
                txt = " ".join(li.get_text(" ", strip=True).split())
                nm = _NAME_RE.match(txt)
                if not nm:
                    continue
                ph = _PHONE_RE.search(txt)
                seen.add(seq)
                found += 1
                parishes.append((seq, nm.group(1), ph.group(0) if ph else None))
            if found == 0:
                break

        records = []
        for seq, name, phone in parishes:
            try:
                html = self._html(session, f"{BASE}sub1_view.asp?seq={seq}")
            except Exception:  # noqa: BLE001
                continue
            su = re.search(r"summerSeason\s*=\s*'([^']*)'", html)
            if not su:
                continue
            vals = su.group(1).split("|")
            kmap: dict[str, str] = {}
            for day, val in zip(DAYS, vals):
                val = val.strip()
                if val and val not in ("동일", "-") and re.search(r"\d{1,2}:\d{2}", val):
                    kmap[DKEY[day]] = val
            if len(kmap) < 2:
                continue
            mass = normalize_mass(
                weekday_cells={d: kmap.get(d, "") for d in
                               ("mon", "tue", "wed", "thu", "fri")},
                saturday=kmap.get("saturday", ""), sunday=kmap.get("sunday", ""),
                raw="하절기 " + su.group(1))
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": phone, "source_url": f"{BASE}sub1_view.asp?seq={seq}",
                "mass": mass})
        return records
