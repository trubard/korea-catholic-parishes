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
from dioceses.jeju import JejuAdapter  # noqa: E402
from dioceses.chuncheon import ChuncheonAdapter  # noqa: E402
from dioceses.busan import BusanAdapter  # noqa: E402

# 등록된 어댑터 (단계적으로 추가)
ADAPTERS = [
    JejuAdapter(),
    ChuncheonAdapter(),
    BusanAdapter(),
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
        matched = sum(v for k, v in methods.items() if k != "unmatched")
        print(f"  본당 {len(records)}건 | 조인 {matched}/{len(records)} "
              f"| {dict(methods)}", flush=True)

        if diocese_id:
            write_json(os.path.join(MASS_DIR, f"{diocese_id}.json"), {
                "generated_at": generated_at, "diocese": adapter.diocese,
                "diocese_id": diocese_id, "count": len(records),
                "masses": records,
            })
        all_records.extend(records)

    write_json(os.path.join(DATA_DIR, "mass.json"), {
        "generated_at": generated_at,
        "count": len(all_records),
        "matched": sum(1 for r in all_records if r.get("church_id")),
        "masses": all_records,
    })
    print(f"[저장] 전체 {len(all_records)}건 -> data/mass.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
