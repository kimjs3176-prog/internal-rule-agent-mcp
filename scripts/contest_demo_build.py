# 시연영상: timing.json의 자막 시각에 맞춰 음성 조각을 한 트랙으로 깔고, 녹화본과 합쳐 mp4(H.264·AAC, 음량 -16 LUFS)를 만든다.
# 실행: python scripts/contest_demo_build.py <녹화 폴더> <출력.mp4> [음성 시각 보정(초), 예: -0.35]
import json, subprocess, sys
import numpy as np, soundfile as sf
vdir = sys.argv[1]; out = sys.argv[2]; offset = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
d = json.load(open(f"{vdir}/timing.json")); SR = 44100
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
