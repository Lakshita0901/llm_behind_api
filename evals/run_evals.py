#!/usr/bin/env python
"""
evals/run_evals.py
Run all 8 labeled test cases through POST /enrich and report accuracy.

Usage:
  uvicorn main:app --reload &   (or start the server first)
  python evals/run_evals.py

Expected output:
  Category accuracy: X/8 (NN%)
  PASS case-01 ...
  FAIL case-02 expected=fiction got=biography
  ...
"""
import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Install httpx first:  pip install httpx")
    sys.exit(1)

BASE_URL = "http://127.0.0.1:8000/enrich"
CASES_PATH = Path(__file__).parent / "cases.json"


def run():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    passed = 0
    failed = 0
    results = []

    for case in cases:
        cid = case["id"]
        expected_cat = case["expected"]["category"]
        acceptable = case["expected"].get("acceptable_categories", [expected_cat])
        expected_flags = case["expected"].get("quality_flags_contain", [])

        try:
            resp = httpx.post(BASE_URL, json=case["input"], timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                got_cat = data.get("category")
                got_flags = data.get("quality_flags", [])

                cat_ok = got_cat in acceptable
                flags_ok = all(f in got_flags for f in expected_flags)

                if cat_ok and flags_ok:
                    passed += 1
                    status = "PASS"
                else:
                    failed += 1
                    status = "FAIL"

                results.append({
                    "id": cid,
                    "status": status,
                    "note": case.get("note", ""),
                    "expected_category": expected_cat,
                    "got_category": got_cat,
                    "expected_flags_contain": expected_flags,
                    "got_flags": got_flags,
                    "http_status": resp.status_code,
                })
            else:
                failed += 1
                results.append({
                    "id": cid,
                    "status": "ERROR",
                    "http_status": resp.status_code,
                    "body": resp.text[:200],
                })
        except Exception as exc:
            failed += 1
            results.append({"id": cid, "status": "EXCEPTION", "error": str(exc)})

    # ── Print report ──────────────────────────────────────────────────────────
    total = passed + failed
    print("\n" + "=" * 60)
    print(f"  EVAL RESULTS -- {Path(__file__).stem}")
    print(f"  Category accuracy: {passed}/{total} ({100*passed//total}%)")
    print("=" * 60 + "\n")

    for r in results:
        icon = "[PASS]" if r["status"] == "PASS" else "[FAIL]"
        cid = r["id"]
        if r["status"] == "PASS":
            print(f"  {icon} {cid}  category={r['got_category']}  flags={r['got_flags']}")
        elif r["status"] == "FAIL":
            print(
                f"  {icon} {cid}  expected_category={r['expected_category']} "
                f"got={r['got_category']}  "
                f"expected_flags={r['expected_flags_contain']} got_flags={r['got_flags']}"
            )
        else:
            print(f"  {icon} {cid}  {r['status']}  {r.get('error', r.get('body', ''))}")

    print(f"\nTotal: {passed} passed, {failed} failed out of {total}\n")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run()
