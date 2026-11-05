"""출품용 측정 스크립트(scripts/contest_bench.py)가 계속 돌아가는지 — 내규 몇 건으로 오류 주입 적발을 확인한다."""
import os
import sys

import reg_agent as ra

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))


def test_inject_bench_detects_all_on_sample():
    import contest_bench as cb
    regs = [r for r in ra.all_regs() if r["title"] in ("여비규정", "복무규정", "인사규정", "보수규정")]
    assert len(regs) == 4
    res = cb.inject_bench(regs)
    assert len(res) == 10
    for x in res:
        assert x["n"] >= 3, x
        assert x["hit"] == x["n"] and x["exact"] == x["n"], x
