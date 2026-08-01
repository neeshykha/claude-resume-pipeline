"""Throwaway: exercise repair_outcomes.classify() on every known row shape."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.repair_outcomes import classify, CANONICAL, LEGACY_V1, CORE

W = len(CANONICAL)
cases = []

# current 13-col row
cases.append(("ok", ["2026-01-01", "Acme", "TAM", "https://x.co/1", "90", "93",
                     "applied", "", "n", "pipeline", "2026-01-01", "2", "Fin"]))
# LEGACY_V1 10-col row -> M
cases.append(("M", ["2026-01-01", "Acme", "TAM", "https://x.co/1", "90", "93",
                    "surfaced", "", "n", "pipeline"]))
# V1 with empty channel (KNOWN_CHANNELS includes "") -> M
cases.append(("M", ["2026-01-01", "Acme", "TAM", "https://x.co/1", "90", "93",
                    "surfaced", "", "n", ""]))
# CORE 9-col -> L
cases.append(("L", ["2026-01-01", "Acme", "TAM", "https://x.co/1", "90", "93",
                    "surfaced", "", "n"]))
# A: 10 cols, trailing PDF path (col 9 is NOT a channel)
cases.append(("A", ["2026-01-01", "Acme", "TAM", "https://x.co/1", "90", "93",
                    "surfaced", "", "n", "tailored/Aneesh_Khan_Acme_TAM.pdf"]))
# B: score/url transposed
cases.append(("B", ["2026-01-01", "Acme", "TAM", "90", "https://x.co/1",
                    "tailored/x.pdf", "", "surfaced", "", "notes"]))
# C: right-shifted by one leading empty
cases.append(("C", ["", "", "Acme", "TAM", "https://x.co/1", "90", "93",
                    "surfaced", "", ""]))
# garbage
cases.append((None, ["just", "three"]))

fails = 0
for want, row in cases:
    got, repaired = classify(list(row))
    ok_shape = got == want
    ok_width = repaired is None or len(repaired) == W
    flag = "PASS" if (ok_shape and ok_width) else "FAIL"
    if flag == "FAIL":
        fails += 1
    print(f"  {flag}  want={str(want):<5} got={str(got):<5} "
          f"width={len(repaired) if repaired else '-'}/{W}")

# idempotency: a repaired row must re-classify as "ok"
print("\n  idempotency (repaired row re-classifies as 'ok'):")
for want, row in cases:
    if want in (None,):
        continue
    _, repaired = classify(list(row))
    again, _ = classify(repaired)
    flag = "PASS" if again == "ok" else "FAIL"
    if flag == "FAIL":
        fails += 1
    print(f"    {flag}  {want} -> {again}")

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILURES'}")
sys.exit(1 if fails else 0)
