#!/usr/bin/env python3
"""수집한 미사 레코드를 기존 churches.json 의 성당(id)에 조인.

전략: 전화번호(숫자만) 1차 → 본당명(교구 스코프) 정확일치 2차 → 부분일치 3차.
"""
from __future__ import annotations

import re

_PAREN_RE = re.compile(r"\([^)]*\)")
# 매칭 방해가 되는 접두/수식어. 정확일치 실패 시 제거하고 재시도.
_NAME_NOISE = ("주교좌", "준본당", "성당", "본당")


def norm_phone(p: str | None) -> str:
    return re.sub(r"\D", "", p or "")


def phone_candidates(s: str | None) -> list[str]:
    """'051-555-2295, 051-556-1531' -> ['0515552295','0515561531']. 9자리 이상만."""
    if not s:
        return []
    out = []
    for part in re.split(r"[,/;]|\s{2,}", s):
        d = re.sub(r"\D", "", part)
        if len(d) >= 9:
            out.append(d)
    if not out:  # 구분자 없이 붙은 경우 전체를 하나로
        d = re.sub(r"\D", "", s)
        if len(d) >= 9:
            out.append(d)
    return out


def norm_name(n: str | None, strip_noise: bool = False) -> str:
    if not n:
        return ""
    n = _PAREN_RE.sub("", n)
    n = re.sub(r"\s+", "", n)
    if strip_noise:
        for w in _NAME_NOISE:
            n = n.replace(w, "")
    return n


class Joiner:
    def __init__(self, churches: list[dict]):
        self.by_phone: dict[str, str] = {}
        self.by_name: dict[tuple, str] = {}
        self.by_diocese: dict[str, list[dict]] = {}
        self.diocese_id: dict[str, str] = {}
        for c in churches:
            # 전화 우선, 팩스도 보조 인덱싱(일부 교구 사이트가 팩스를 전화로 표기)
            ph = norm_phone(c.get("phone"))
            if ph:
                self.by_phone.setdefault(ph, c["id"])
            fx = norm_phone(c.get("fax"))
            if fx:
                self.by_phone.setdefault(fx, c["id"])
            dio = c.get("diocese")
            self.by_name.setdefault((dio, norm_name(c.get("name"))), c["id"])
            self.by_diocese.setdefault(dio, []).append(c)
            if dio and c.get("diocese_id"):
                self.diocese_id.setdefault(dio, c["diocese_id"])

    def match(self, rec: dict) -> tuple[str | None, str]:
        """(church_id, method) 반환. 실패 시 (None, 'unmatched')."""
        for ph in phone_candidates(rec.get("phone")):
            if ph in self.by_phone:
                return self.by_phone[ph], "phone"

        dio = rec.get("diocese")
        target = norm_name(rec.get("parish_name"))
        key = (dio, target)
        if key in self.by_name:
            return self.by_name[key], "name"

        # 접두/수식어 제거 후 부분일치 (교구 내에서만)
        t2 = norm_name(rec.get("parish_name"), strip_noise=True)
        best = None
        for c in self.by_diocese.get(dio, []):
            cn = norm_name(c.get("name"), strip_noise=True)
            if not cn:
                continue
            if cn == t2:
                return c["id"], "name_stripped"
            if cn in t2 or t2 in cn:
                # 가장 긴 공통을 우선(짧은 이름의 과대매칭 방지)
                if best is None or len(cn) > best[1]:
                    best = (c["id"], len(cn))
        if best:
            return best[0], "name_fuzzy"
        return None, "unmatched"
