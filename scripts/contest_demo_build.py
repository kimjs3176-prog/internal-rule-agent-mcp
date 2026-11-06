# 시연영상: timing.json의 자막 시각에 맞춰 음성 조각을 한 트랙으로 깔고, 녹화본과 합쳐 mp4(H.264·AAC, 음량 -16 LUFS)를 만든다.
# 실행: python scripts/contest_demo_build.py <녹화 폴더> <출력.mp4> [음성 시각 보정(초), 기본 auto: 녹화 첫머리의 동기 표시로 잰다]
import json, subprocess, sys
import numpy as np, soundfile as sf
vdir = sys.argv[1]; out = sys.argv[2]; arg = sys.argv[3] if len(sys.argv) > 3 else "auto"
d = json.load(open(f"{vdir}/timing.json")); SR = 44100

def sync_offset():
    """녹화 첫머리의 자막·음성 동기 표시(왼쪽 위 자홍색 네모)가 영상에 처음 보이는 시각 − 녹화 시계의 시각"""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-t", "15", "-i", f"{vdir}/raw.webm", "-vf", "crop=24:24:12:12,scale=1:1,fps=100",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    for i in range(0, len(raw) - 2, 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if r > 180 and b > 180 and g < 90: return (i // 3) / 100 - d["syncT"]
    raise SystemExit("동기 표시를 찾지 못했습니다. 보정값(초)을 직접 넣으세요.")

offset = sync_offset() if arg == "auto" else float(arg)
print(f"음성 시각 보정 {offset:+.2f}초")
track = np.zeros(int((d["total"] + 2) * SR), np.float32)
for x in d["subs"]:
    a, sr = sf.read(x["audio"], dtype="float32")
    if a.ndim > 1: a = a.mean(1)
    if sr != SR: a = np.interp(np.arange(0, len(a), sr / SR), np.arange(len(a)), a).astype(np.float32)
    i = int(max(0, x["s"] + offset) * SR); track[i:i + len(a)] += a[:len(track) - i]
peak = np.abs(track).max() or 1; track *= min(1.0, 0.89 / peak)
sf.write(f"{vdir}/narration.wav", track, SR)
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", f"{vdir}/raw.webm", "-i", f"{vdir}/narration.wav",
  "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
  "-c:a", "aac", "-b:a", "160k", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-shortest", "-movflags", "+faststart", out], check=True)
print("ok", out)
