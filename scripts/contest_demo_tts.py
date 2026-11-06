# 시연영상 녹화 중 자막 한 줄마다 음성을 만들어 주는 로컬 TTS 서버(Supertonic 3, CPU·오프라인). 같은 문장은 캐시에서 돌려준다.
# 시연영상 제작용 도구다(서비스에는 들어가지 않는다). 준비:
#   pip install supertonic soundfile huggingface_hub
#   hf download supertone-oss-archive/supertonic-3 --revision aafc6e32416a594460b32413efc49d7fe4ce6d46 --local-dir tts_assets
#   (코드 MIT, 모델 OpenRAIL-M — docs/contest/시연영상.md)
# 실행: python scripts/contest_demo_tts.py [목소리=F1] [속도=1.2]   (모델 폴더는 DEMO_TTS_MODEL, 기본 ./tts_assets)
# POST /tts {"text": "..."} → {"file": ".../cache/<hash>.wav", "dur": 3.21}
import hashlib, json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import soundfile as sf
from supertonic import TTS

import os
MODEL = Path(os.environ.get("DEMO_TTS_MODEL", "tts_assets")).resolve()
CACHE = MODEL / "cache"; CACHE.mkdir(exist_ok=True)
VOICE = sys.argv[1] if len(sys.argv) > 1 else "F1"
SPEED = float(sys.argv[2]) if len(sys.argv) > 2 else 1.2
tts = TTS(model="supertonic-3", model_dir=MODEL, auto_download=False)
style = tts.get_voice_style(voice_name=VOICE)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        text = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["text"]
        f = CACHE / (hashlib.sha1(f"{VOICE}|{SPEED}|{text}".encode()).hexdigest()[:16] + ".wav")
        if not f.exists():
            wav, _ = tts.synthesize(text, lang="ko", voice_style=style, speed=SPEED)
            tts.save_audio(wav, str(f))
        info = sf.info(str(f))
        body = json.dumps({"file": str(f), "dur": info.frames / info.samplerate}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

HTTPServer(("127.0.0.1", 5200), H).serve_forever()
