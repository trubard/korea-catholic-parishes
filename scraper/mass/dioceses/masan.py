#!/usr/bin/env python3
"""마산교구 미사시간 어댑터 (큐레이션 맵 방식).

마산교구는 통합 본당 디렉토리가 없고 본당마다 독립 사이트를 쓴다. 교구 사이트의
본당 목록(cathms.kr/E_2~E_5, ol.bd_lst)에서 75개 본당 상세 페이지를 얻고, 각 상세의
'홈페이지' 필드에서 본당 홈페이지를 수집한 뒤, 홈페이지의 미사 페이지를 찾아 아래 SITES
(본당명 → 미사 페이지 URL)로 등록했다.

각 페이지에서 (1) 요일 표, 없으면 (2) 요일 평문(주일/월요일 …)을 파싱한다. 미사시간을
이미지로만 올린 본당은 표·텍스트가 없어 자동 스킵된다(OCR 미적용). board_*/movie 경로는
게시글 기반이라 재게시 시 바뀔 수 있고, 끊기면 해당 본당만 스킵된다.
"""
from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

from base import MassAdapter, korean_to_hhmm, normalize_mass
import ocr

C = "cathms.kr"
# 본당명: 미사 페이지 URL
SITES = {
    "가좌동": "http://gajwa.cathms.kr/xe/board_oCOh74/13788",
    "거창": "http://geo.cathms.kr/xe/page_foxn59",
    "고현": "http://goh.cathms.kr/xe/page_Awcw22",
    "금산": "http://kum.cathms.kr/xe/board_LuAU21/11773",
    "남성동": "http://namsung.cathms.kr/xe/board_LuAU21/9016",
    "남지": "http://nj.cathms.kr/xe/board_Yuex31/15978",
    "대건": "http://dg.cathms.kr/xe/496366",
    "대산성지": "http://daesan.cathms.kr/notice/1280",
    "망경동": "http://mk.cathms.kr/xe/board_LuAU21/25930",
    "명서동": "http://ms.cathms.kr/xe/churh9",
    "반송": "http://bs.cathms.kr/xe/page_NVdd17",
    "북신동": "http://bsd.cathms.kr/xe/board_Yuex31/8553",
    "산청": "http://sanc.cathms.kr/xe/board_Yuex31/10006",
    "산호동": "http://san.cathms.kr/xe/board_wIoU26/8976",
    "상평동": "http://sp.cathms.kr/xe/board_Yuex31/10769",
    "성가정": "http://skj.cathms.kr/photo/1032",
    "신안동": "http://sin.cathms.kr/B_1/10796",
    "안의선교": "http://an.cathms.kr/page_fJlT21",
    "양곡": "http://yk.cathms.kr/xe/board_Yuex31/2956",
    "양덕동": "http://yangduk.kr/bbs/board.php?bo_table=livesbody&wr_id=10",
    "옥포": "http://okpo.cathms.kr/xe/90479",
    "월영": "http://www.wolyoung.or.kr/bbs/board.php?bo_table=livesbody&wr_id=12",
    "의령": "http://ur.cathms.kr/photo/681",
    "장등": "http://jdsd.cathms.kr/board_ffCj96/7752",
    "장승포": "http://jsp.cathms.kr/xe/prayer01",
    "장평": "http://jp.cathms.kr/xe/movie/39148",
    "중동": "http://jd.cathms.kr/xe/board_LuAU21/8859",
    "지세포": "http://ji.cathms.kr/notice/468",
    "진동": "http://jin.cathms.kr/xe/board_LuAU21/7150",
    "진영": "http://jy.cathms.kr/xe/board_Yuex31/7649",
    "하대동": "http://had.cathms.kr/xe/page_JcrW79",
    "함안": "http://www.hamansd.kr/bbs/board.php?bo_table=livesbody&wr_id=16",
    "함양": "http://ham.cathms.kr/xe/board_Yuex31/5378",
    "합천": "http://hap.cathms.kr/xe/board_mnPW66/15692",
    # 미사시간을 이미지(base64 임베드)로 게시 — 메인 홈페이지에서 OCR (easyocr 필요)
    "가음동": "http://gaeum.cathms.kr/",
    "호계": "http://hg.cathms.kr/",
    "중앙동": "http://jung.cathms.kr/",
    "수산": "http://susan.cathms.kr/",
    "고성": "http://ks.cathms.kr/",
    "대건": "http://dg.cathms.kr/",
    "칠원": "http://cw.cathms.kr/",
}

_DAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri",
        "토": "saturday", "주일": "sunday", "일": "sunday"}
_DAYWORD = [("주일", "sunday"), ("월요일", "mon"), ("화요일", "tue"),
            ("수요일", "wed"), ("목요일", "thu"), ("금요일", "fri"),
            ("토요일", "saturday")]


def _get(session, url):
    time.sleep(0.3)  # 본당 사이트 과부하 방지(동시 요청 시 접속 실패)
    r = session.get(url, timeout=15, verify=False)
    r.raise_for_status()
    html = None
    for enc in ("utf-8", "euc-kr"):
        try:
            t = r.content.decode(enc)
            if "미사" in t or "요일" in t:
                html = t
                break
        except UnicodeDecodeError:
            pass
    if html is None:
        html = r.content.decode("utf-8", "replace")
    return BeautifulSoup(html, "html.parser"), html


def _cells(tr):
    return [re.sub(r"\s+", " ", korean_to_hhmm(c.get_text(" ", strip=True)))
            for c in tr.find_all(["th", "td"])]


def _is_time(c):
    """미사 시간 셀인가(순수 HH:MM). 게시판 날짜('2026-05-29 14:26')는 제외."""
    return (re.search(r"\d{1,2}:\d{2}", c)
            and not re.search(r"\d{4}[-.]\d{1,2}[-.]\d{1,2}|\d{4}년|\d{2}:\d{2}:\d{2}", c))


def _day_keys(text):
    t = text.replace("요일", "")
    keys = ["sunday"] if "주일" in t else []
    keys += [_DAY[ch] for ch in ("월", "화", "수", "목", "금", "토") if ch in t]
    if not keys and "일" in t:
        keys = ["sunday"]
    return keys


def _parse_mass_table(table) -> dict:
    """요일 표 → {mon: 'HH:MM ...'}. 요일이 행(row)·열(column) 어느 방향이든 처리."""
    rows = table.find_all("tr")
    # (1) 요일이 행 머리(첫 셀)에 오는 표
    kmap: dict[str, str] = {}
    for tr in rows:
        cells = _cells(tr)
        if not cells:
            continue
        keys = _day_keys(cells[0])
        if not keys:
            continue
        times = " ".join(c for c in cells[1:] if _is_time(c))
        if times:
            for k in keys:
                kmap[k] = (kmap.get(k, "") + " " + times).strip()
    if len(kmap) >= 3:
        return kmap
    # (2) 요일이 헤더 열(column)에 오는 표: 헤더행에서 열→요일 매핑
    for hi, tr in enumerate(rows):
        cells = _cells(tr)
        col_day = {}
        for i, c in enumerate(cells):
            k = _day_keys(c)
            if len(k) == 1 and not re.search(r"\d", c):
                col_day[i] = k[0]
        if len(col_day) < 4:
            continue
        km2: dict[str, str] = {}
        for tr2 in rows[hi + 1:]:
            cs = _cells(tr2)
            for i, day in col_day.items():
                if i < len(cs) and _is_time(cs[i]):
                    km2[day] = (km2.get(day, "") + " " + cs[i]).strip()
        if len(km2) > len(kmap):
            kmap = km2
        break
    return kmap


def _parse_day_text(text: str) -> dict:
    """'토요일 16:00 (어린이) 주일 10:30 (교중) 월요일 06:00 …' 평문 → {mon: '…'}."""
    text = re.sub(r"주\s*일", "주일", text)
    text = re.sub(r"평일\s*미사|주일\s*미사", " ", text)
    text = re.split(r"고해성사|판공|성사\s*안내", text)[0]
    text = korean_to_hhmm(text)
    poss = sorted((m.start(), len(w), key)
                  for w, key in _DAYWORD for m in re.finditer(w, text))
    kmap: dict[str, str] = {}
    for i, (pos, ln, key) in enumerate(poss):
        end = poss[i + 1][0] if i + 1 < len(poss) else len(text)
        seg = text[pos + ln:end].strip()
        if re.search(r"\d{1,2}:\d{2}", seg):
            kmap[key] = (kmap.get(key, "") + " " + seg).strip()
    return kmap


def _valid_mass(kmap: dict) -> bool:
    """미사시간표가 맞는지 검증(게시판 타임스탬프 등 오검출 방지)."""
    all_t = [t for v in kmap.values() for t in re.findall(r"\d{1,2}:\d{2}", v)]
    if not all_t or any(len(re.findall(r"\d{1,2}:\d{2}", v)) > 6 for v in kmap.values()):
        return False
    round_frac = sum(1 for t in all_t if t[-2:] in ("00", "30", "15", "45")) / len(all_t)
    return round_frac >= 0.7


class MasanAdapter(MassAdapter):
    diocese = "마산교구"

    def collect(self, session: requests.Session) -> list[dict]:
        records: list[dict] = []
        for name, url in SITES.items():
            try:
                soup, html = _get(session, url)
            except Exception:  # noqa: BLE001
                continue
            kmap: dict[str, str] = {}
            for table in soup.find_all("table"):
                km = _parse_mass_table(table)
                if len(km) > len(kmap):
                    kmap = km
            if len(kmap) < 3:  # 표 없으면 요일 평문 시도
                kt = _parse_day_text(soup.get_text(" ", strip=True))
                if len(kt) > len(kmap):
                    kmap = kt
            if len(kmap) < 3:  # 그래도 없으면 base64 이미지 OCR(easyocr 있을 때만)
                ko = ocr.ocr_mass_from_html(html)
                if len(ko) > len(kmap):
                    kmap = ko
            if len(kmap) < 3 or not _valid_mass(kmap):
                continue  # 미사표·텍스트·이미지 없음 또는 오검출 → 스킵
            mass = normalize_mass(
                weekday_cells={d: kmap.get(d, "") for d in
                               ("mon", "tue", "wed", "thu", "fri")},
                saturday=kmap.get("saturday", ""), sunday=kmap.get("sunday", ""),
                raw="; ".join(f"{k} {v}" for k, v in kmap.items()))
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": None, "source_url": url, "mass": mass})
        return records
