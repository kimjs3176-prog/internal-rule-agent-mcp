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


def test_workload_counts():
    """수작업 비교 문서(docs/contest/수작업비교.md)의 작업량 근거가 데이터에서 나온다."""
    import contest_bench as cb
    w = cb.workload(ra.all_regs())
    assert w["여비규정"]["제20조_인용"] == ["24"] and w["여비규정"]["일비_등장"] >= 1
    assert w["일괄정비"]["내규"] >= 1 and w["일괄정비"]["곳"] >= w["일괄정비"]["내규"]
    assert isinstance(w["현행_점검지적"], dict)
