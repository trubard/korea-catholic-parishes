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

from base import MassAdapter, korean_to_hhmm, normalize_mass
import render

ROOT = "https://sd.uca.or.kr/"
# 교구 호스팅 밖 자체도메인 본당(요일 표) — 헤드리스 렌더링(render.py, 선택적)
OWN_SITES = {
    "고양동": "http://www.goyangdong.or.kr/",
}
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
    text = re.sub(r"주\s*일", "주일", text)          # '주 일' -> '주일'
    text = re.sub(r"\s+", " ", text)
    text = re.split(r"성사\s*시간|성 시 간|예비신자|유아세례|고해성사|판공", text)[0]
    text = korean_to_hhmm(text)                       # '오전 7시' -> '07:00'

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
            def _mass_from(text):
                if "주일미사" not in text:
                    return None
                m = parse_uijeongbu_mass(text)
                return m if (m["sunday"] or any(m["weekday"].values())) else None

            # (1) 메인 페이지에 미사 텍스트가 직접 있으면 사용
            mass = _mass_from(" ".join(home.get_text(" ", strip=True).split()))
            src = f"{ROOT}{code}/"
            # (2) 없으면 미사안내(default.aspx) 링크 페이지
            if not mass:
                best, best_score = None, -1
                for a in home.find_all("a", href=_MISA_RE):
                    t = a.get_text(" ", strip=True)
                    if "미사" not in t or re.search(r"동영상|생중계|영상|갤러리", t):
                        continue
                    score = 2 if re.search(r"안내|시간|전례|성사", t) else 1
                    if score > best_score:
                        best, best_score = _MISA_RE.search(a["href"]).group(0), score
                if not best:
                    continue
                try:
                    page = _get(session, f"{ROOT}{code}/{best}")
                except Exception:  # noqa: BLE001
                    continue
                mass = _mass_from(" ".join(page.get_text(" ", strip=True).split()))
                src = f"{ROOT}{code}/{best}"
            if not mass:
                continue
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": None, "source_url": src, "mass": mass})

        # 자체도메인 본당 — 헤드리스 렌더링 후 요일 표 파싱
        from dioceses.masan import _parse_mass_table  # noqa: PLC0415
        for name, url in OWN_SITES.items():
            html = render.render_html(url)
            if not html:
                continue
            best: dict = {}
            for t in BeautifulSoup(html, "html.parser").find_all("table"):
                km = _parse_mass_table(t) or {}
                if len(km) > len(best):
                    best = km
            if len(best) < 3:
                continue
            records.append({
                "parish_name": name, "diocese": self.diocese, "phone": None,
                "source_url": url,
                "mass": normalize_mass(
                    weekday_cells={d: best.get(d, "") for d in
                                   ("mon", "tue", "wed", "thu", "fri")},
                    saturday=best.get("saturday", ""), sunday=best.get("sunday", ""),
                    raw="; ".join(f"{k} {v}" for k, v in best.items()))})
        return records
