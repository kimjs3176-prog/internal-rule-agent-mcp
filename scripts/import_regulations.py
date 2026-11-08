"""기관 내규 일괄 등록 — 다른 기관이 자기 내규로 에이전트를 쓰도록 데이터를 만든다.

사용법
    python scripts/import_regulations.py <내규 파일 폴더> [--reset] [--dry-run]

    · 폴더 안의 .hwpx .hwp .docx .html .htm .txt .md .pdf 를 읽어(.hwp 는 본문 글자를 뽑고, .pdf 는 원본을 보여 주며 글자 층이 있으면 검색에 쓴다)
      regulations/<규정명>/index.html·text.txt 와 regulations_manifest.json 을 만든다.
    · 파일명이 규정명이 된다. "인사규정(2025년도 1월 일부개정).hwpx" 처럼 괄호 안은 개정 정보로 쓴다.
    · --reset 을 주면 기존 regulations/ 와 매니페스트를 비우고 새로 만든다(다른 기관 최초 설정).
      지우는 대신 옆에 “.backup-날짜시각” 폴더로 옮겨 둔다. 저장소 기본 데이터(REG_DIR 미지정)를 비우려면 --force 가 더 필요하다
      — Windows에서 export 줄이 실패한 채 붙여 넣어도 기본 내규 126건이 지워지지 않게.
    · 등록 후 의미 검색을 쓰려면 scripts/build_embeddings.py 로 색인을 다시 만든다(선택).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reg_import as ri  # noqa: E402


def split_name(fname: str):
    stem = os.path.splitext(os.path.basename(fname))[0]
    m = re.match(r"^(.*?)\s*[(（]([^)）]*)[)）]\s*$", stem)
    title, rev = (m.group(1), m.group(2)) if m else (stem, "")
    return re.sub(r"[_\s]+", " ", title).strip(), rev.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description="기관 내규 일괄 등록")
    ap.add_argument("folder", help="내규 파일이 있는 폴더")
    ap.add_argument("--reset", action="store_true", help="기존 내규 데이터를 지우고 새로 만든다")
    ap.add_argument("--dry-run", action="store_true", help="변환만 시험하고 저장하지 않는다")
    ap.add_argument("--force", action="store_true", help="REG_DIR 없이(저장소 기본 데이터에) --reset 할 때 필요")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.folder):
        ap.error(f"폴더가 없습니다: {a.folder}")
    files = sorted(f for f in os.listdir(a.folder)
                   if os.path.splitext(f)[1].lower() in ri.ALLOWED_EXT)
    if not files:
        print("등록할 파일이 없습니다(지원 형식: " + ", ".join(sorted(ri.ALLOWED_EXT)) + ")")
        return 1
    if a.reset and not a.dry_run:
        norm = lambda x: os.path.normcase(os.path.realpath(os.path.normpath(os.path.abspath(x))))
        reg_dir = os.path.normpath(os.path.abspath(ri.REG_DIR))      # 끝 “/”(Windows의 대체 구분자 포함)를 없앤다 — 백업 경로가 폴더 안쪽이 되지 않게
        same = norm(reg_dir) == norm(os.path.join(ri.BASE_DIR, "regulations"))
        if same and not a.force:
            n = len(ri.load_manifest())
            print(f"멈춤: 저장소의 기본 내규 데이터({n}건, {ri.REG_DIR})를 비우려 합니다.\n"
                  "  다른 기관 시험이면 REG_DIR·REG_MANIFEST 환경변수로 별도 폴더를 지정하세요(구동안내서 ‘모의데이터 안내’).\n"
                  "  Windows PowerShell: $env:REG_DIR=\"po\\regulations\"; $env:REG_MANIFEST=\"po\\manifest.json\"\n"
                  "  정말 기본 데이터를 바꾸려면 --force 를 함께 주세요(기존 데이터는 백업 폴더로 옮깁니다).")
            return 3
        stamp = time.strftime("%Y%m%d-%H%M%S")
        while os.path.exists(f"{reg_dir}.backup-{stamp}"):
            stamp += "x"
        if os.path.isdir(reg_dir) and os.listdir(reg_dir):
            bak = f"{reg_dir}.backup-{stamp}"
            try:
                shutil.move(reg_dir, bak)
            except OSError as e:
                print(f"멈춤: 기존 내규 폴더를 백업으로 옮기지 못했습니다({e}). 데이터는 그대로입니다.")
                return 3
            print(f"기존 내규 폴더를 옮겨 두었습니다: {bak}")
        if os.path.isfile(ri.REG_MANIFEST_PATH):
            shutil.copy2(ri.REG_MANIFEST_PATH, f"{ri.REG_MANIFEST_PATH}.backup-{stamp}")
        os.makedirs(ri.REG_DIR, exist_ok=True)
        man = []
    else:
        man = ri.load_manifest()
    ok = warn = fail = 0
    for f in files:
        title, rev = split_name(f)
        with open(os.path.join(a.folder, f), "rb") as fh:
            raw = fh.read()
        try:
            res = ri.convert(f, raw, title, {"revision": rev})
        except Exception as e:
            print(f"  ✗ {f}: {e}")
            fail += 1
            continue
        slug = ri.reg_slug(title)
        if not a.dry_run:
            ri.write_reg(slug, res["view_html"], res["text"], f, raw)
            man = ri.upsert(man, {"title": title, "revision": rev,
                                  "category": ri.guess_category(title), "slug": slug,
                                  "src": f, "html": f"/regulations/{slug}/index.html",
                                  "uploaded_at": ri.now_kst()})
        mark = "⚠" if res.get("warning") else "✓"
        warn += bool(res.get("warning"))
        ok += 1
        print(f"  {mark} {title}{(' · ' + rev) if rev else ''}{(' — ' + res['warning']) if res.get('warning') else ''}")
    if not a.dry_run:
        ri.save_manifest(man)
    print(f"\n완료: {ok}건 등록(주의 {warn}건), 실패 {fail}건 → {ri.REG_DIR}"
          + (" (시험 실행 — 저장 안 함)" if a.dry_run else ""))
    return 0 if not fail else 2


if __name__ == "__main__":
    sys.exit(main())
