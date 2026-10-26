"""İki ölçüm turunu görev görev karşılaştırır (A/B).

Döküm dosyalarını (data/trajectories/*.jsonl) okur; bir tur birkaç parçaya bölündüyse (durdurulup --only ile
devam edildiyse) glob ile hepsini verin, aynı görevin son kaydı geçerlidir.

    uv run python evals/compare_runs.py "A_glob" "B_glob"
"""
from __future__ import annotations

import collections
import glob
import json
import sys


def load(pattern: str) -> dict[str, dict]:
    runs = {}
    for f in sorted(glob.glob(pattern)):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            runs[r["task_id"]] = r
    return runs


def tool_calls(r: dict) -> collections.Counter:
    c = collections.Counter()
    for s in r.get("sessions") or []:
        for m in s.get("messages") or []:
            c.update(tc["function"]["name"] for tc in m.get("tool_calls") or [])
    return c


def main(a_glob: str, b_glob: str) -> None:
    A, B = load(a_glob), load(b_glob)
    ids = [i for i in B if i in A]
    print(f"ortak görev: {len(ids)} (A {len(A)}, B {len(B)})\n")
    tools = {}
    for name, R in (("A", A), ("B", B)):
        tools[name] = sum((tool_calls(R[i]) for i in ids), collections.Counter())
        print(f"{name}: {sum(R[i]['ok'] for i in ids)}/{len(ids)} başarılı, "
              f"{sum(R[i]['seconds'] for i in ids):.0f} sn, {sum(tools[name].values())} araç çağrısı")

    print("\nkategori     görev   A   B")
    cats = collections.defaultdict(lambda: [0, 0, 0])
    for i in ids:
        c = cats[B[i]["category"]]
        c[0] += 1
        c[1] += A[i]["ok"]
        c[2] += B[i]["ok"]
    for k, (n, a, b) in sorted(cats.items()):
        print(f"  {k:10s} {n:5d} {a:3d} {b:3d}" + ("  <--" if a != b else ""))

    print("\naraç          A    B")
    for t in sorted(set(tools["A"]) | set(tools["B"]), key=lambda t: -tools["A"][t] - tools["B"][t]):
        print(f"  {t:16s} {tools['A'][t]:4d} {tools['B'][t]:4d}")

    flips = [i for i in ids if A[i]["ok"] != B[i]["ok"]]
    better = sum(B[i]["ok"] for i in flips)
    print(f"\nfarklı sonuç: {len(flips)} görev ({better} B lehine, {len(flips) - better} A lehine)")
    for i in flips:
        print(f"  {i:24s} A={'OK' if A[i]['ok'] else 'X '} B={'OK' if B[i]['ok'] else 'X '}  "
              f"A: {(A[i].get('note') or A[i].get('error') or '')[:60]} | B: {(B[i].get('note') or '')[:60]}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
