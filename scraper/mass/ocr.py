#!/usr/bin/env python3
"""미사시간 이미지(주로 base64 임베드) OCR — 선택적 기능.

일부 본당은 미사시간표를 이미지(data:image base64)로만 게시한다. easyocr 로 표를
읽고, 글자 위치(x)로 요일 열에 정렬해 {요일: 'HH:MM ...'} 로 구조화한다.

easyocr 가 설치되지 않았으면 available()==False 이고 모든 함수가 빈 결과를 돌려주므로,
파이프라인은 OCR 없이도 정상 동작한다(해당 본당만 스킵).
"""
from __future__ import annotations

import base64
import re

_DAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri",
        "토": "saturday", "주일": "sunday", "일": "sunday"}
_TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})")
_reader = None
_tried = False


def available() -> bool:
    return _get_reader() is not None


def _get_reader():
    global _reader, _tried
    if not _tried:
        _tried = True
        try:
            import easyocr  # noqa: PLC0415
            _reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        except Exception:  # noqa: BLE001
            _reader = None
    return _reader


def extract_data_images(html: str) -> list[bytes]:
    """페이지 HTML 의 data:image base64 를 디코딩해 바이트로 반환."""
    out = []
    for b64 in re.findall(r"data:image/(?:png|jpe?g|gif);base64,([A-Za-z0-9+/=]+)", html):
        try:
            out.append(base64.b64decode(b64))
        except Exception:  # noqa: BLE001
            pass
    return out


def ocr_mass_image(png: bytes) -> dict:
    """미사시간표 이미지 → {요일: 'HH:MM ...'}. 표가 아니면 빈 dict."""
    reader = _get_reader()
    if reader is None:
        return {}
    try:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
        import io  # noqa: PLC0415
        arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
        res = reader.readtext(arr, detail=1)
    except Exception:  # noqa: BLE001
        return {}

    cols = []          # (x중심, 요일키)  — 헤더
    times = []         # (x중심, y, 'HH:MM')
    notice_y = 10 ** 9  # '예비신자/교리' 등 안내문 y(그 아래 시간은 미사 아님)
    header_y = 0
    for box, txt, _conf in res:
        xc = (box[0][0] + box[1][0]) / 2
        y = box[0][1]
        t = txt.replace(" ", "")
        if t in _DAY:
            cols.append((xc, _DAY[t]))
            header_y = max(header_y, y)
        if re.search(r"예비|교리|판공|성사|첨례", txt):
            notice_y = min(notice_y, y)
        for m in _TIME_RE.finditer(txt):
            times.append((xc, y, f"{int(m.group(1)):02d}:{m.group(2)}"))
    if len(cols) < 4:
        return {}
    cols.sort()
    kmap: dict[str, str] = {}
    used = []
    for xc, y, tm in times:
        if y <= header_y or y >= notice_y:   # 표 본문(헤더~안내문 사이)만
            continue
        day = min(cols, key=lambda c: abs(c[0] - xc))[1]
        kmap[day] = (kmap.get(day, "") + " " + tm).strip()
        used.append(tm)
    # 검증: 미사시간이 아닌 이미지(사진 등) 오검출 방지
    if not used:
        return {}
    if any(len(v.split()) > 6 for v in kmap.values()):   # 요일당 6개 초과 = 비정상
        return {}
    round_frac = sum(1 for t in used if t[-2:] in ("00", "30", "15", "45")) / len(used)
    if round_frac < 0.7:   # 미사시간은 대개 정시/반시
        return {}
    return kmap


def extract_img_urls(html: str, base_url: str):
    """페이지의 <img src>(png/jpg)를 절대 URL 로. (힌트목록, 기타목록) 반환.

    파일명/alt 에 '미사'·'미사시간'·'전례' 있으면 힌트. 힌트 없는 이미지는 사진·배너가
    대부분이라 OCR 대상에서 캡을 둔다(페이지에 이미지가 수십 개인 경우 폭주 방지).
    """
    from urllib.parse import urljoin  # noqa: PLC0415
    hinted, other, seen = [], [], set()
    for tag in re.findall(r"<img\b[^>]*>", html, re.I):
        m = re.search(r'src\s*=\s*["\']?([^"\'>\s]+)', tag, re.I)
        if not m:
            continue
        src = m.group(1)
        if not re.search(r"\.(?:png|jpe?g)(?:\?|$)", src, re.I):
            continue
        url = urljoin(base_url, src)
        if url in seen:
            continue
        seen.add(url)
        alt = re.search(r'alt\s*=\s*["\']([^"\']*)', tag, re.I)
        blob = src + (alt.group(1) if alt else "")
        (hinted if re.search(r"미사|전례|주보", blob) else other).append(url)
    return hinted, other


def ocr_mass_from_html(html: str, base_url: str | None = None, fetch=None,
                       max_unhinted: int = 4) -> dict:
    """페이지에서 미사시간표 이미지를 찾아 OCR. 여러 이미지면 요일 최다 결과.

    base64 임베드 이미지를 먼저 시도하고, base_url·fetch 가 주어지면 링크된 <img>도
    내려받아 OCR 한다. 파일명/alt 에 '미사' 등 힌트가 있는 이미지를 우선하며, 힌트 없는
    이미지는 max_unhinted 개까지만 시도한다(사진 다수 페이지 폭주 방지).
    """
    if _get_reader() is None:
        return {}
    best: dict = {}
    for png in extract_data_images(html):
        if len(png) < 3000:
            continue
        km = ocr_mass_image(png)
        if len(km) > len(best):
            best = km
    if len(best) >= 4 or fetch is None or base_url is None:
        return best
    hinted, other = extract_img_urls(html, base_url)
    for url in hinted + other[:max_unhinted]:
        try:
            png = fetch(url)
        except Exception:  # noqa: BLE001
            continue
        if not png or len(png) < 3000:
            continue
        km = ocr_mass_image(png)
        if len(km) > len(best):
            best = km
        if len(best) >= 6:
            break
    return best
