import io
import os
import sys
import tempfile

sys.path.append('third_party/Matcha-TTS')

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from cosyvoice.cli.cosyvoice import CosyVoice2

# ---- 설정 (환경변수로 주입, 코드에 비밀 안 박음) ----
API_KEY     = os.environ.get("TTS_API_KEY")   # 필수: 없으면 아무도 못 부름
MODEL_DIR   = os.environ.get("COSYVOICE_MODEL_DIR", "pretrained_models/CosyVoice2-0.5B")
PROMPT_WAV  = os.environ.get("PROMPT_WAV", "caregiver_ref.wav")     # 보호자 참조 음성(24kHz)
PROMPT_TEXT = os.environ.get("PROMPT_TEXT",
    "엄마 저예요, 오늘은 어떻게 보내셨어요? 점심은 뭐 드셨고요? 따뜻하게 드셔야 해요. "
    "어제 보내드린 영양제는 잘 챙겨 드시고 계시죠? 잊지 마시고요. 저는 오늘 회사에서 회의가 많아서 좀 정신이 없었어요.")

# ---- 모델 로드 (서버 켤 때 딱 한 번) ----
print("CosyVoice2 로딩 중...")
cosyvoice = CosyVoice2(MODEL_DIR, load_jit=False, load_trt=False, fp16=True)
print("로딩 완료.")

SPK_ID = "caregiver"
print("참조 음성 특징 캐싱 중...")
cosyvoice.add_zero_shot_spk(PROMPT_TEXT, PROMPT_WAV, SPK_ID)
print("캐싱 완료:", cosyvoice.list_available_spks())

# 목소리 등록 시 사용자가 '순서대로 전부' 읽는 고정 대본(①~④).
# 앱 녹음 화면이 이 순서·문장을 그대로 보여주고, 다 읽어야 완료된다.
# 제로샷은 대본과 실제 녹음이 일치해야 품질이 나오므로,
# 이 텍스트와 앱이 보여주는 텍스트가 '글자까지' 똑같아야 한다.
ENROLL_PROMPT_TEXT = (
    # ① 일상 안부
    "저예요. 그동안 잘 지내셨어요?"
    "여기는 아침저녁으로 좀 쌀쌀해졌어요."
    "낮에는 또 볕이 좋고요."
    "이런 날씨에 감기 걸리기 딱 좋으니까, 얇은 거라도 하나 걸치고 계세요."
    "오늘 점심에 된장찌개를 먹었는데, 예전에 해주시던 그 맛이 자꾸 생각나더라고요."
    "두부를 큼직하게 썰어 넣으셨잖아요."
    "그게 참 맛있었어요."
)

app = FastAPI(title="Morri TTS (CosyVoice2)")


class TTSRequest(BaseModel):
    text: str
    spk_id: str | None = None   # 없으면 기본 caregiver(SPK_ID)


def _check_key(x_api_key: str | None) -> None:
    if not API_KEY:
        raise HTTPException(500, "서버에 TTS_API_KEY 미설정")
    if x_api_key != API_KEY:
        raise HTTPException(401, "잘못된 API 키")


@app.get("/health")
def health():
    return {"status": "ok"}


# ── 목소리 등록(제로샷 화자 추가) ────────────────────────────
# EC2(backend)가 가족 녹음을 이 엔드포인트로 릴레이한다.
# 참조 음성 + 고정 대본(ENROLL_PROMPT_TEXT) → spk_id 로 화자 캐싱(수 초).
@app.post("/enroll")
def enroll(
    spk_id: str = Form(...),          # EC2가 준 화자 식별자 (예: spk_12)
    file: UploadFile = File(...),     # 가족이 녹음한 참조 음성
    x_api_key: str = Header(default=None),
):
    _check_key(x_api_key)

    # 업로드 음성을 임시 파일로 저장. 기존 /tts 가 PROMPT_WAV '경로'를 쓰는 것과 같은 방식.
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(file.file.read())
        wav_path = f.name

    try:
        ok = cosyvoice.add_zero_shot_spk(ENROLL_PROMPT_TEXT, wav_path, spk_id)
        if not ok:
            raise HTTPException(500, "화자 등록 실패(add_zero_shot_spk)")
        cosyvoice.save_spkinfo()   # 디스크에 저장 → 서버 재시작해도 유지
    finally:
        os.remove(wav_path)

    return {"speaker_id": spk_id, "speakers": cosyvoice.list_available_spks()}


# ── 합성(다중 화자) ─────────────────────────────────────────
@app.post("/tts")
def tts(req: TTSRequest, x_api_key: str = Header(default=None)):
    _check_key(x_api_key)
    if not req.text.strip():
        raise HTTPException(400, "text가 비어있음")

    sid = req.spk_id or SPK_ID
    chunks = []
    for out in cosyvoice.inference_zero_shot(req.text, "", "", zero_shot_spk_id=sid, stream=False):
        chunks.append(out["tts_speech"].squeeze(0).cpu().numpy())
    audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]

    buf = io.BytesIO()
    sf.write(buf, audio, cosyvoice.sample_rate, format="WAV")
    return Response(content=buf.getvalue(), media_type="audio/wav")


@app.post("/tts_stream")
def tts_stream(req: TTSRequest, x_api_key: str = Header(default=None)):
    _check_key(x_api_key)
    if not req.text.strip():
        raise HTTPException(400, "text가 비어있음")

    sid = req.spk_id or SPK_ID

    def gen():
        for out in cosyvoice.inference_zero_shot(req.text, "", "", zero_shot_spk_id=sid, stream=True):
            audio = out["tts_speech"].squeeze(0).cpu().numpy()
            pcm16 = (audio * 32767).astype(np.int16)
            yield pcm16.tobytes()

    return StreamingResponse(gen(), media_type="application/octet-stream")