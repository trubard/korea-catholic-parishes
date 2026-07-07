#!/usr/bin/env python3
"""원주교구 미사시간 어댑터 (HTTP 전용).

지구별 미사시간 페이지 parish/time?c={지구}. 한 표: [성당 | 미사평문 | 소재지(전화)].
미사평문: '주일미사 토 19:30 일 08:30 10:30 월 10:00 화 ... 토 -' (일=주일, 토 중복=특전).
"""
from __future__ import annotations

import re

import requests

from base import MassAdapter, get_soup, normalize_mass

BASE = "http://www.wjcatholic.or.kr/"
_DAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri",
        "토": "saturday", "일": "sunday"}
_PHONE_RE = re.compile(r"0\d{1,2}\)\s?\d{3,4}-\d{4}|0\d{1,2}-\d{3,4}-\d{4}")


def _split_wonju(text: str) -> dict:
    text = re.sub(r"주일미사|평일미사", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    poss = [(m.start(), m.group()) for m in re.finditer(r"[월화수목금토일]", text)]
    result: dict = {}
    for i, (pos, lb) in enumerate(poss):
        end = poss[i + 1][0] if i + 1 < len(poss) else len(text)
        val = text[pos + 1:end].strip(" :,-")
        if re.search(r"\d{1,2}:\d{2}", val):
            key = _DAY[lb]
            # 토(특전)·토(평일) 중복 시 시간 병합
            result[key] = (result.get(key, "") + " " + val).strip()
    return result


class WonjuAdapter(MassAdapter):
    diocese = "원주교구"

    def _districts(self, session) -> list[str]:
        try:
            soup = get_soup(session, f"{BASE}parish/time")
            cs = re.findall(r"parish/time\?c=([^\"'&]+지구)", str(soup))
            return list(dict.fromkeys(cs))
        except Exception:  # noqa: BLE001
            return []

    def collect(self, session: requests.Session) -> list[dict]:
        # 영평정지구(영월·평창·정선) 포함 — 지구명 정확히 일치해야 함
        districts = self._districts(session) or [
            "남원주지구", "북원주지구", "서원주지구", "횡성지구",
            "제천지구", "태백지구", "영평정지구", "영동지구"]
        records: list[dict] = []
        seen: set[str] = set()
        for dist in districts:
            try:
                soup = get_soup(session, f"{BASE}parish/time?c={dist}")
            except Exception:  # noqa: BLE001
                continue
            for tr in soup.find_all("tr"):
                cs = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cs) < 2 or "미사" not in cs[1]:
                    continue
                name = re.sub(r"천주교|성당|주교좌", "", cs[0]).strip()
                if not name or name in seen:
                    continue
                days = _split_wonju(cs[1])
                if not days:
                    continue
                seen.add(name)
                loc = cs[2] if len(cs) > 2 else ""
                ph = _PHONE_RE.search(loc)
                mass = normalize_mass(
                    weekday_cells={d: days.get(d, "") for d in
                                   ("mon", "tue", "wed", "thu", "fri")},
                    saturday=days.get("saturday", ""), sunday=days.get("sunday", ""),
                    raw=cs[1].strip())
                records.append({
                    "parish_name": name, "diocese": self.diocese,
                    "phone": ph.group(0) if ph else None,
                    "source_url": f"{BASE}parish/time?c={dist}", "mass": mass})
        return records
