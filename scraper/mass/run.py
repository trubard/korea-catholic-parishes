#!/usr/bin/env python3
"""미사시간 수집 파이프라인.

등록된 교구 어댑터로 미사시간을 수집 → churches.json 의 성당(id)에 조인 →
data/mass/<diocese_id>.json (교구별) + data/mass.json (전체) 저장.

사용:
  python scraper/mass/run.py                 # 등록된 전 교구 수집
  python scraper/mass/run.py --diocese 제주교구
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scraper/mass

from join import Joiner  # noqa: E402
from base import normalize_mass, parse_time_cell  # noqa: E402
from dioceses.jeju import JejuAdapter  # noqa: E402
from dioceses.chuncheon import ChuncheonAdapter  # noqa: E402
from dioceses.busan import BusanAdapter  # noqa: E402
from dioceses.gwangju import GwangjuAdapter  # noqa: E402
from dioceses.suwon import SuwonAdapter  # noqa: E402
from dioceses.cheongju import CheongjuAdapter  # noqa: E402
from dioceses.daejeon import DaejeonAdapter  # noqa: E402
from dioceses.daegu import DaeguAdapter  # noqa: E402
from dioceses.seoul import SeoulAdapter  # noqa: E402
from dioceses.incheon import IncheonAdapter  # noqa: E402
from dioceses.jeonju import JeonjuAdapter  # noqa: E402
from dioceses.wonju import WonjuAdapter  # noqa: E402
from dioceses.gunjong import GunjongAdapter  # noqa: E402
from dioceses.uijeongbu import UijeongbuAdapter  # noqa: E402
from dioceses.masan import MasanAdapter  # noqa: E402
from dioceses.andong import AndongAdapter  # noqa: E402

# 등록된 어댑터 (단계적으로 추가)
ADAPTERS = [
    JejuAdapter(),
    ChuncheonAdapter(),
    BusanAdapter(),
    GwangjuAdapter(),
    SuwonAdapter(),
    CheongjuAdapter(),
    DaejeonAdapter(),
    DaeguAdapter(),
    SeoulAdapter(),
    IncheonAdapter(),
    JeonjuAdapter(),
    WonjuAdapter(),
    GunjongAdapter(),
    UijeongbuAdapter(),
    MasanAdapter(),
    AndongAdapter(),
]

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
CHURCHES = os.path.join(DATA_DIR, "churches.json")
MASS_DIR = os.path.join(DATA_DIR, "mass")


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diocese", help="특정 교구명만 수집")
    args = ap.parse_args()

    churches = json.load(open(CHURCHES, encoding="utf-8"))["churches"]
    joiner = Joiner(churches)
    session = requests.Session()
    session.headers.update({"User-Agent": "catholic-church-mass-collector/1.0"})

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    adapters = [a for a in ADAPTERS
                if not args.diocese or a.diocese == args.diocese]

    # 수동 오버라이드(자동 수집 불가 본당) 교구별 로드
    manual_by_diocese: dict[str, list] = {}
    manual_path = os.path.join(DATA_DIR, "mass_manual.json")
    if os.path.exists(manual_path):
        for e in json.load(open(manual_path, encoding="utf-8")).get("entries", []):
            manual_by_diocese.setdefault(e["diocese"], []).append(e)

    def manual_records(diocese, already_ids):
        out = []
        for e in manual_by_diocese.get(diocese, []):
            cid, method = joiner.match({"parish_name": e["name"],
                                        "diocese": diocese, "phone": None})
            if cid and cid in already_ids:
                continue  # 자동 수집이 있으면 그것을 우선
            wd = e.get("weekday", {})
            mass = normalize_mass(
                weekday_cells={d: wd.get(d, "") for d in
                               ("mon", "tue", "wed", "thu", "fri")},
                saturday=e.get("saturday", ""), sunday=e.get("sunday", ""),
                raw="manual")
            mass["special"] = [x for s in e.get("special", []) for x in parse_time_cell(s)]
            rec = {"parish_name": e["name"], "diocese": diocese, "phone": None,
                   "source_url": e.get("source"), "mass": mass,
                   "church_id": cid, "match_method": method, "manual": True}
            # 공소(station) 미사 — {name, address?, sunday/weekday/... } 목록
            stations = []
            for st in e.get("stations", []):
                swd = st.get("weekday", {})
                smass = normalize_mass(
                    weekday_cells={d: swd.get(d, "") for d in
                                   ("mon", "tue", "wed", "thu", "fri")},
                    saturday=st.get("saturday", ""), sunday=st.get("sunday", ""),
                    raw="manual")
                smass["special"] = [x for s in st.get("special", [])
                                    for x in parse_time_cell(s)]
                stations.append({"name": st["name"],
                                 "address": st.get("address"), "mass": smass})
            if stations:
                rec["stations"] = stations
            out.append(rec)
        return out

    all_records: list[dict] = []
    for adapter in adapters:
        print(f"[수집] {adapter.diocese} ...", flush=True)
        try:
            records = adapter.collect(session)
        except Exception as e:  # noqa: BLE001
            print(f"  [ERR] {adapter.diocese}: {e}", file=sys.stderr)
            continue

        methods = Counter()
        diocese_id = joiner.diocese_id.get(adapter.diocese)
        for rec in records:
            cid, method = joiner.match(rec)
            rec["church_id"] = cid
            rec["match_method"] = method
            methods[method] += 1
        # 수동 오버라이드 병합 (자동 수집 안 된 본당만)
        man = manual_records(adapter.diocese,
                             {r["church_id"] for r in records if r.get("church_id")})
        if man:
            records.extend(man)
            print(f"  + 수동 {len(man)}건", flush=True)

        matched = sum(v for k, v in methods.items() if k != "unmatched") + \
            sum(1 for r in man if r.get("church_id"))
        print(f"  본당 {len(records)}건 | 조인 {matched}/{len(records)} "
              f"| {dict(methods)}", flush=True)

        if diocese_id:
            # 일시적 실패로 이번에 못 얻은 본당은 이전 값 유지(carry-over)
            prev_path = os.path.join(MASS_DIR, f"{diocese_id}.json")
            if os.path.exists(prev_path):
                new_names = {r["parish_name"] for r in records}
                prev = json.load(open(prev_path, encoding="utf-8")).get("masses", [])
                carried = [r for r in prev if r["parish_name"] not in new_names]
                if carried:
                    records.extend(carried)
                    print(f"  + 이전값 유지 {len(carried)}건", flush=True)
            write_json(prev_path, {
                "generated_at": generated_at, "diocese": adapter.diocese,
                "diocese_id": diocese_id, "count": len(records),
                "masses": records,
            })
        all_records.extend(records)

    # 전체 mass.json 은 항상 교구 파일 전량을 합쳐 재생성한다.
    # (--diocese 로 일부만 수집해도 나머지 교구가 지워지지 않도록)
    merged: list[dict] = []
    for fn in sorted(os.listdir(MASS_DIR)):
        if not fn.endswith(".json"):
            continue
        merged.extend(json.load(open(os.path.join(MASS_DIR, fn),
                                    encoding="utf-8")).get("masses", []))
    write_json(os.path.join(DATA_DIR, "mass.json"), {
        "generated_at": generated_at,
        "count": len(merged),
        "matched": sum(1 for r in merged if r.get("church_id")),
        "masses": merged,
    })
    print(f"[저장] 전체 {len(merged)}건 -> data/mass.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
