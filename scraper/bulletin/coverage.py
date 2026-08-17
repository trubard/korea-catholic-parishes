#!/usr/bin/env python3
"""주보 수집 커버리지 리포트 — data/bulletin_coverage.json 생성.

각 본당을 상태별로 분류해 공개한다(투명성 + 신자 제보 웹사이트 데이터):
  collected  : 주보 소스 발견 + 최근 주보 관측(신선)
  stale      : 소스는 있으나 최신 주보가 오래됨(STALE_DAYS 초과)
  source_only: 소스는 발견됐으나 아직 주보 페치/판독 전
  no_source  : 주보 소스 미발견(홈페이지 없음/카페 아님 등) — 제보가 가장 필요
미사시간 수집 여부(mass.json)와 교차해 '미사시간도 없고 주보도 없는' 최우선 대상을 표시.

사용: python scraper/bulletin/coverage.py [--stale-days 35]
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone, date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data")


def _load(name, key=None, default=None):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default if default is not None else {}
    try:
        d = json.load(open(p, encoding="utf-8"))
        return d.get(key, default) if key else d
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def _days_since(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    try:
        y, m, d = (int(x) for x in iso_date[:10].split("-"))
        return (date.today() - date(y, m, d)).days
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-days", type=int, default=35)
    args = ap.parse_args()

    churches = _load("churches.json", "churches", [])
    sources = _load("bulletin_sources.json", "by_church", {})
    state = _load("bulletin_state.json", "by_church", {})   # {cid:{last_post_date,...}}
    masses = _load("mass.json", "masses", [])

    def has_mass(m):
        mm = m.get("mass") or {}
        return any(mm.get(k) for k in ("sunday", "saturday", "weekday", "special"))
    mass_covered = {m["church_id"] for m in masses
                    if m.get("church_id") and has_mass(m)}

    by_status = {"collected": [], "stale": [], "source_only": [], "no_source": []}
    for c in churches:
        if c["diocese"] == "군종교구":
            continue          # 군부대 — 일반 신자 제보 대상 아님
        cid = c["id"]
        src = sources.get(cid)
        st = state.get(cid, {})
        last = st.get("last_post_date")
        rec = {"id": cid, "diocese": c["diocese"], "name": c["name"],
               "homepage": c.get("homepage"),
               "source": (src.get("url") if src else None),
               "last_bulletin": last, "mass_covered": cid in mass_covered}
        if src and last and (_days_since(last) or 999) <= args.stale_days:
            by_status["collected"].append(rec)
        elif src and last:
            rec["stale_days"] = _days_since(last)
            by_status["stale"].append(rec)
        elif src:
            by_status["source_only"].append(rec)
        else:
            by_status["no_source"].append(rec)

    # 최우선 제보 대상: 미사시간도 없고 주보 소스도 없음
    need_help = [r for r in by_status["no_source"] if not r["mass_covered"]]
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stale_days": args.stale_days,
        "note": "주보 수집 커버리지. 신자 제보 웹사이트용. no_source+미사미수집이 최우선.",
        "summary": {k: len(v) for k, v in by_status.items()},
        "need_help_count": len(need_help),
        "by_status": by_status,
    }
    json.dump(out, open(os.path.join(DATA, "bulletin_coverage.json"), "w",
              encoding="utf-8"), ensure_ascii=False, indent=2)
    open(os.path.join(DATA, "bulletin_coverage.json"), "a",
         encoding="utf-8").write("\n")
    print("커버리지:", {k: len(v) for k, v in by_status.items()},
          "| 최우선 제보대상(무미사+무소스):", len(need_help))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
