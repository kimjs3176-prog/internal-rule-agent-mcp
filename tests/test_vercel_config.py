"""Vercel 배포 설정: 함수 실행 시간 상한이 원격 MCP 응답 제한(엔진 40초·수치 비교 45초)보다 넉넉하고,
함수가 실행 중에 읽는 파일(내규 원문·엔진·인증서 등)이 함수에 함께 실린다."""
import fnmatch
import json
import os
import pathlib

from mcp_server import core, engine

ROOT = pathlib.Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))


def test_function_max_duration_covers_mcp_limits():
    assert "builds" not in CFG                      # 옛 builds 와 functions 는 함께 쓸 수 없다(Vercel)
    fn = CFG["functions"]["api/index.py"]
    assert fn["maxDuration"] >= max(engine.HTTP_TIMEOUT, core.COMPARE_BUDGET) + 10


def test_runtime_files_are_included():
    pats = CFG["functions"]["api/index.py"]["includeFiles"].strip("{}").split(",")
    need = ["assets/reg_agent.js", "certs/law_go_kr_intermediate.pem", "mcp_server/engine_core.js",
            "mcp_server/engine.mjs", "org_config.json", "regulations_manifest.json",
            "regulations_vectors.json", "regulations_vectors.bin"]
    slug = next(p.name for p in (ROOT / "regulations").iterdir() if p.is_dir())
    need.append(f"regulations/{slug}/index.html")
    for f in need:
        assert (ROOT / f).exists(), f
        assert any(fnmatch.fnmatch(f, p.replace("/**", "/*")) or f == p for p in pats), f
