"""법제처(law.go.kr) TLS: 검증을 끄지 않고, certifi 묶음 + 빠진 중간 인증서로 검증한다."""
import os
import shutil
import ssl
import subprocess

import certifi
import pytest

import api_server


def test_law_session_verifies_tls():
    v = api_server._LAW_SESSION.verify
    assert v is not False and isinstance(v, str) and os.path.isfile(v)
    text = open(v, encoding="utf-8").read()
    assert open(certifi.where(), encoding="utf-8").read().strip()[:200] in text      # certifi 묶음을 그대로 담고
    inter = open(api_server._LAW_INTERMEDIATE, encoding="utf-8").read()
    assert inter[inter.index("-----BEGIN"):].strip() in text                       # 법제처 중간 인증서를 더한다
    ctx = ssl.create_default_context(cafile=v)                                       # 올바른 인증서 묶음
    assert ctx.cert_store_stats()["x509_ca"] > ssl.create_default_context(cafile=certifi.where()).cert_store_stats()["x509_ca"]


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl 없음")
def test_law_intermediate_chains_to_certifi_root():
    # 더한 중간 인증서가 certifi 의 루트(GlobalSign Root CA - R3)로 이어진다 — 아무 인증서나 믿게 만든 것이 아니다
    r = subprocess.run(["openssl", "verify", "-CAfile", certifi.where(), api_server._LAW_INTERMEDIATE],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip().endswith("OK"), r.stdout + r.stderr


def test_bundle_includes_corporate_ca(monkeypatch, tmp_path):
    corp = tmp_path / "corp.pem"
    corp.write_text(open(api_server._LAW_INTERMEDIATE, encoding="utf-8").read().replace("법제처", "사내"), encoding="utf-8")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(corp))
    assert "사내" in open(api_server._law_ca_bundle(), encoding="utf-8").read()
