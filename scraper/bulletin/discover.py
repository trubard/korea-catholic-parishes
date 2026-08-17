#!/usr/bin/env python3
"""주보 소스 발견 — 각 본당 홈페이지(카페/블로그/자체홈)에서 주보 게시판을 찾아
data/bulletin_sources.json 에 기록한다(church_id -> {platform, cafe/blog, board/menu}).

주보는 신빙성 최상위 소스라 이후 '최신 주보 페치 → (반자동)판독 → 병합' 의 토대다.
1단계(발견)는 OCR 불필요. 다음카페(최다)부터 지원, 이후 네이버·자체홈 확장.

사용: python scraper/bulletin/discover.py [--platform daum|naver|all] [--limit N]
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

requests.packages.urllib3.disable_warnings()
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "bulletin_sources.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      "Referer": "https://m.cafe.daum.net/"}
# 주보 게시판명 후보(넓게)
_JUBO = re.compile(r"주보")


def _daum_cafe_id(homepage: str) -> str | None:
    m = re.search(r"cafe\.daum\.net/([A-Za-z0-9_.-]+)", homepage)
    return m.group(1) if m else None


def discover_daum(church, homepage):
    """다음카페 홈페이지 -> 주보 게시판 코드.

    m.cafe.daum.net 의 `articles.push({fldid, fldName, ...})` 에서 이름에 '주보'가
    든 게시판을 고른다. '교구 주보'(교구 전체)보다 본당 주보를 우선한다.
    """
    cid = _daum_cafe_id(homepage)
    if not cid:
        return None
    try:
        r = requests.get(f"https://m.cafe.daum.net/{cid}", headers=UA, timeout=15)
        t = r.text
    except Exception:
        return None
    pairs = re.findall(r'fldid:\s*"([^"]+)",\s*fldName:\s*"([^"]+)"', t)
    seen, jubo = set(), []
    for fid, nm in pairs:
        if fid in seen:
            continue
        seen.add(fid)
        if "주보" in nm:
            jubo.append((fid, nm))
    if not jubo:
        return None
    # 본당 주보(교구/타본당 아님) 우선
    parish = [x for x in jubo if "교구" not in x[1] and "타본당" not in x[1]]
    fid, nm = (parish or jubo)[0]
    return {"platform": "daum_cafe", "cafe": cid, "board": fid, "board_name": nm,
            "url": f"https://m.cafe.daum.net/{cid}/{fid}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="daum")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    churches = json.load(open(os.path.join(DATA, "churches.json"),
                              encoding="utf-8"))["churches"]
    prev = {}
    if os.path.exists(OUT):
        prev = json.load(open(OUT, encoding="utf-8")).get("by_church", {})

    targets = [c for c in churches if c.get("homepage") and
               "cafe.daum.net" in c["homepage"]]
    if args.limit:
        targets = targets[: args.limit]
    print(f"다음카페 대상 {len(targets)}곳 발견 시도 ...")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    found = dict(prev)
    ok = 0
    changes = []   # 변경 이력(감사)
    with futures.ThreadPoolExecutor(max_workers=12) as ex:
        fut = {ex.submit(discover_daum, c, c["homepage"]): c for c in targets}
        for i, f in enumerate(futures.as_completed(fut), 1):
            c = fut[f]
            try:
                res = f.result()
            except Exception:
                res = None
            old = prev.get(c["id"])
            if res:
                res["church"] = c["name"]
                res["diocese"] = c["diocese"]
                res["homepage"] = c["homepage"]
                res["last_checked"] = today
                if old:
                    res["first_found"] = old.get("first_found", today)
                    # 홈페이지·게시판·카페 변경 감지 → 이력 기록
                    for k in ("homepage", "cafe", "board"):
                        if old.get(k) and old.get(k) != res.get(k):
                            changes.append({"date": today, "church": c["name"],
                                            "id": c["id"], "field": k,
                                            "from": old.get(k), "to": res.get(k)})
                else:
                    res["first_found"] = today
                found[c["id"]] = res
                ok += 1
            elif old:
                # 이전엔 있었는데 지금 못 찾음 → 소스 유실 가능(경로 변경)
                old["last_checked"] = today
                old["lost"] = True
                changes.append({"date": today, "church": c["name"], "id": c["id"],
                                "field": "source", "from": old.get("board"), "to": None})
            if i % 50 == 0:
                print(f"  {i}/{len(targets)} (발견 {ok})", flush=True)

    # 변경 이력 누적
    log_path = os.path.join(DATA, "bulletin_changes.json")
    hist = []
    if os.path.exists(log_path):
        try:
            hist = json.load(open(log_path, encoding="utf-8")).get("changes", [])
        except (json.JSONDecodeError, OSError):
            hist = []
    hist.extend(changes)
    json.dump({"generated_at": today, "note": "주보 소스 변경 이력(홈페이지·게시판·카페 "
               "변경, 소스 유실). 수집경로 변경 감사용.", "changes": hist},
              open(log_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(log_path, "a", encoding="utf-8").write("\n")

    json.dump({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "note": "본당 주보 게시판 소스. platform=daum_cafe|naver_cafe|blog|homepage. "
                       "first_found/last_checked 로 이력, lost=true 는 소스 유실 의심. "
                       "최신 주보 페치→판독→병합의 토대(1단계 발견).",
               "count": len(found), "by_church": found},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(OUT, "a", encoding="utf-8").write("\n")
    print(f"발견 {ok}/{len(targets)} (누적 {len(found)}) | 변경 {len(changes)}건 "
          f"-> data/bulletin_sources.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
