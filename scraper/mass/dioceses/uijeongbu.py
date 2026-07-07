#!/usr/bin/env python3
"""의정부교구 미사시간 어댑터.

교구 본당 호스팅 sd.uca.or.kr 루트가 본당 디렉토리(코드+이름).
각 본당 /{code}/ 에서 '미사안내' 링크(default.aspx?mnucd=) → 미사 페이지(평문).
형식: '주일미사 06:30 새벽미사 ... 평일미사 월요일 06:00 화요일 ... 토요미사 ... 성사시간 ...'
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from base import MassAdapter, normalize_mass

ROOT = "https://sd.uca.or.kr/"
_CODE_RE = re.compile(r"^/([a-zA-Z0-9_]+)/?$")
_MISA_RE = re.compile(r"default\.aspx\?mnucd=\d+")
_WD = {"월요일": "mon", "화요일": "tue", "수요일": "wed", "목요일": "thu", "금요일": "fri"}


def _get(session, url):
    r = session.get(url, timeout=25, verify=False)
    r.raise_for_status()
    for enc in ("utf-8", "euc-kr"):
        try:
            t = r.content.decode(enc)
            if "미사" in t or "성당" in t:
                return BeautifulSoup(t, "html.parser")
        except UnicodeDecodeError:
            pass
    return BeautifulSoup(r.content.decode("utf-8", "replace"), "html.parser")


def parse_uijeongbu_mass(text: str) -> dict:
    text = re.sub(r"\s+", " ", text)
    text = re.split(r"성사\s*시간|성 시 간|예비신자|유아세례|고해성사", text)[0]

    def between(a, b):
        m = re.search(a, text)
        if not m:
            return ""
        rest = text[m.end():]
        if b:
            e = re.search(b, rest)
            return rest[:e.start()] if e else rest
        return rest

    sun = between(r"주일미사", r"평일미사")
    wk = between(r"평일미사", r"토요미사|토요\s*저녁|특전")
    sat = between(r"토요미사|토요\s*저녁", None)

    weekday = {}
    poss = sorted((m.start(), lb) for lb in _WD for m in re.finditer(lb, wk))
    for i, (pos, lb) in enumerate(poss):
        end = poss[i + 1][0] if i + 1 < len(poss) else len(wk)
        weekday[_WD[lb]] = wk[pos + len(lb):end].strip()

    return normalize_mass(
        weekday_cells={d: weekday.get(d, "") for d in ("mon", "tue", "wed", "thu", "fri")},
        saturday=sat, sunday=sun, raw=text[:400].strip())


class UijeongbuAdapter(MassAdapter):
    diocese = "의정부교구"

    def collect(self, session: requests.Session) -> list[dict]:
        root = _get(session, ROOT)
        parishes = {}
        for a in root.find_all("a", href=True):
            m = _CODE_RE.match(a["href"]) or _CODE_RE.match(
                a["href"].replace("https://sd.uca.or.kr", ""))
            name = a.get_text(" ", strip=True)
            if m and "성당" in name:
                parishes[m.group(1)] = re.sub(r"\s*성당\s*$", "", name).strip()

        records: list[dict] = []
        for code, name in parishes.items():
            try:
                home = _get(session, f"{ROOT}{code}/")
            except Exception:  # noqa: BLE001
                continue
            link = None
            for a in home.find_all("a", href=_MISA_RE):
                if "미사" in a.get_text():
                    link = _MISA_RE.search(a["href"]).group(0)
                    if "안내" in a.get_text() or "성사" in a.get_text():
                        break
            if not link:
                continue
            try:
                page = _get(session, f"{ROOT}{code}/{link}")
            except Exception:  # noqa: BLE001
                continue
            text = " ".join(page.get_text(" ", strip=True).split())
            if "주일미사" not in text:
                continue
            mass = parse_uijeongbu_mass(text)
            if not (mass["sunday"] or any(mass["weekday"].values())):
                continue
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": None, "source_url": f"{ROOT}{code}/{link}", "mass": mass})
        return records
