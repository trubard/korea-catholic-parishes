#!/usr/bin/env python3
"""JS 렌더링 페이지 HTML 가져오기 — 선택적 기능(playwright).

일부 본당은 미사시간표를 JS 위젯으로만 그려서 requests 로는 표가 보이지 않는다.
playwright(headless chromium)로 렌더링한 HTML 을 돌려준다.

playwright/chromium 이 없으면 available()==False 이고 render_html()==None 이므로,
파이프라인은 렌더링 없이도 정상 동작한다(해당 본당만 스킵).
"""
from __future__ import annotations

_tried = False
_ok = False


def available() -> bool:
    global _tried, _ok
    if not _tried:
        _tried = True
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                b.close()
            _ok = True
        except Exception:  # noqa: BLE001
            _ok = False
    return _ok


def render_html(url: str, wait_ms: int = 2000) -> str | None:
    """URL 을 headless 브라우저로 렌더링한 최종 HTML. 실패 시 None."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            pg = b.new_page()
            pg.goto(url, timeout=40000, wait_until="networkidle")
            pg.wait_for_timeout(wait_ms)
            html = pg.content()
            b.close()
        return html
    except Exception:  # noqa: BLE001
        return None
