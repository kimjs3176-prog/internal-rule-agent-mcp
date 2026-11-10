# 시연영상: timing.json의 자막 시각에 맞춰 음성 조각을 한 트랙으로 깔고, 녹화본과 합쳐 mp4(H.264·AAC, 음량 -14 LUFS·최대 -1.5 dBTP)를 만든다.
# 영상은 첫 화면(훅 카드)이 완성된 시각(timing.startT)부터 자르고, 점검용 timeline.json(win4r/video-director 형식, MIT)을 함께 쓴다.
# 실행: python scripts/contest_demo_build.py <녹화 폴더> <출력.mp4> [음성 시각 보정(초), 기본 auto: 녹화 첫머리의 동기 표시로 잰다]
import json, subprocess, sys
import numpy as np, soundfile as sf
vdir = sys.argv[1]; out = sys.argv[2]; arg = sys.argv[3] if len(sys.argv) > 3 else "auto"
d = json.load(open(f"{vdir}/timing.json")); SR = 44100

SYNC_AT = None   # 동기 표시가 영상에 보인 시각(초)

def sync_offset():
    """녹화 첫머리의 자막·음성 동기 표시(왼쪽 위 자홍색 네모)가 영상에 처음 보이는 시각 − 녹화 시계의 시각"""
    global SYNC_AT
    raw = subprocess.run(["ffmpeg", "-v", "error", "-t", "15", "-i", f"{vdir}/raw.webm", "-vf", "crop=24:24:12:12,scale=1:1,fps=100",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    for i in range(0, len(raw) - 2, 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if r > 180 and b > 180 and g < 90:
            SYNC_AT = (i // 3) / 100; return SYNC_AT - d["syncT"]
    raise SystemExit("동기 표시를 찾지 못했습니다. 보정값(초)을 직접 넣으세요.")

offset = sync_offset() if arg == "auto" else float(arg)
start = d.get("timing", {}).get("startT", 0.0)   # 녹화 시계의 영상 시작(첫 화면 완성) 시각
trim = max(0.0, start + offset)                  # 녹화본에서 잘라 낼 앞부분(초)
print(f"음성 시각 보정 {offset:+.2f}초, 앞부분 {trim:.2f}초 자름")
track = np.zeros(int((d["total"] - start + 2) * SR), np.float32)
for x in d["subs"]:
    a, sr = sf.read(x["audio"], dtype="float32")
    if a.ndim > 1: a = a.mean(1)
    if sr != SR: a = np.interp(np.arange(0, len(a), sr / SR), np.arange(len(a)), a).astype(np.float32)
    i = int(max(0, x["s"] + offset - trim) * SR); track[i:i + len(a)] += a[:len(track) - i]
peak = np.abs(track).max() or 1; track *= min(1.0, 0.89 / peak)
sf.write(f"{vdir}/narration.wav", track, SR)
# 동기 표시는 완성본에 보이지 않게, 표시가 뜨기 직전 그 자리 화면을 잘라 표시가 있는 동안 덮어 씌운다
cover = []
if SYNC_AT is not None and trim < SYNC_AT + 0.5:   # 자른 앞부분에 동기 표시가 다 들어가면 덮을 필요가 없다
    still = f"{vdir}/sync_cover.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0, SYNC_AT - 0.15):.2f}", "-i", f"{vdir}/raw.webm", "-frames:v", "1",
                    "-vf", "crop=64:64:0:0", still], check=True)
    cover = ["-loop", "1", "-i", still, "-filter_complex",
             f"[0:v][2:v]overlay=0:0:shortest=1:enable='between(t,{max(0, SYNC_AT - 0.05):.2f},{SYNC_AT + 0.5:.2f})'[v]", "-map", "[v]", "-map", "1:a"]
subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{trim:.3f}", "-i", f"{vdir}/raw.webm", "-i", f"{vdir}/narration.wav", *cover,
  "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
  "-c:a", "aac", "-b:a", "160k", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-shortest", "-movflags", "+faststart", out], check=True)
# 점검용 타임라인: 모든 시각을 완성본 기준(녹화 시계 − startT)으로 옮긴다
f = lambda t: round(t - start, 2)
tm = d.get("timing", {}); end = f(d["total"])
sc = [x for x in d["scenes"] if x["s"] >= start - 0.5]
scenes = [{"id": x["t"], "start": max(0.0, f(x["s"])), "end": (max(0.0, f(sc[i + 1]["s"])) if i + 1 < len(sc) else end), "beats": {"in": max(0.0, f(x["s"]))}} for i, x in enumerate(sc)]
texts = []
if tm.get("hookBox"):
    texts.append({"id": "hook", "text": "한 문장으로 개정안·대비표·검증까지", "from": 0.0, "to": round(scenes[1]["start"] - 0.4, 2) if len(scenes) > 1 else 3.0,
                  "role": "hook", "px": 88, "box": tm["hookBox"]})
tl = {"meta": {"w": 1920, "h": 1080, "fps": 30, "dur": end, "clock": "voice", "register": "editorial", "loop": False,
               "vo": {"status": "RENDERED", "file": "narration.wav"}},
      "scenes": scenes, "cuts": [s["start"] for s in scenes[1:]],
      "hero": {"t": f(tm["hero"]), "what": "실측 숫자 카드(1,243/1,243 · 619/619)"} if tm.get("hero") else None,
      "captions": [{"from": f(x["s"]), "to": f(x["e"]), "text": x["text"], "src": "vo"} for x in d["subs"]],
      "vo": [{"id": f"L{i + 1}", "text": x["text"].replace("\n", " "), "from": f(x["s"]), "to": round(f(x["s"]) + x["dur"], 2)} for i, x in enumerate(d["subs"])],
      "texts": texts, "terms": ["규정 제·개정 에이전트", "신구조문대비표", "개정문 검증"]}
json.dump(tl, open(f"{vdir}/timeline.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok", out)
