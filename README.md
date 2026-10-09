<div align="center">

# 🎙 ReMory Voice Cloning

**보호자의 목소리로 말하는 인형 모리의 음성 합성 서버**

[CosyVoice2](https://github.com/FunAudioLLM/CosyVoice)의 zero-shot voice cloning을 FastAPI로 감싼 TTS 서버입니다.

![Python](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-2.3.1-EE4C2C?logo=pytorch&logoColor=white)

</div>

---

## 📖 이런 서버입니다

보호자가 앱에서 짧게 녹음하면 그 목소리를 등록하고, 인형 모리가 답변을 **그 목소리로** 말합니다.
모델을 따로 학습하지 않고 **참조 음성 + 대본**만으로 목소리 특징을 추출하는 zero-shot 방식이라, 보호자가 늘어도 모델은 하나입니다.

- 앱 → [리모리 백엔드](https://github.com/Hanium-Remory/Hanium-Remory-BE) → `POST /enroll` : 목소리 등록
- 인형 → `POST /tts_stream` : 답변 합성 (받는 대로 재생)

---

## 🧰 기술 스택

| | |
|---|---|
| 음성 합성 | CosyVoice2-0.5B (fp16) |
| 서버 | FastAPI + Uvicorn |
| 환경 | Python 3.10 · PyTorch 2.3.1 (CUDA 12.1) · RTX 2080 Ti |

---

## ✨ API

`/health`를 제외한 모든 요청에 `x-api-key` 헤더가 필요합니다.

| 엔드포인트 | 설명 |
|---|---|
| `GET /health` | 상태 확인 |
| `POST /enroll` | 목소리 등록. `multipart/form-data`로 `spk_id`, `file`(참조 음성) |
| `POST /tts` | 합성. `{"text", "spk_id"}` → `audio/wav` (`spk_id` 생략 시 기본 화자) |
| `POST /tts_stream` | 스트리밍 합성. 같은 요청 → raw PCM (16bit 모노 24kHz) |

---

## 🚀 빠른 시작

서버는 CosyVoice 저장소 루트에서 실행합니다.

1. [CosyVoice](https://github.com/FunAudioLLM/CosyVoice)를 clone하고 환경과 `CosyVoice2-0.5B` 모델(`pretrained_models/`)을 준비합니다.
2. `server_stream.py`를 CosyVoice 저장소 루트에 복사합니다.
3. 기본 화자의 참조 음성(24kHz 모노 WAV)과 그 음성의 대본을 준비해 실행합니다.

```bash
export TTS_API_KEY="<긴 랜덤 문자열>"
export PROMPT_WAV=my_reference.wav
export PROMPT_TEXT="참조 음성에서 말한 내용 그대로"
python -m uvicorn server_stream:app --host 0.0.0.0 --port 8001
```

| 환경변수 | 설명 |
|---|---|
| `TTS_API_KEY` | 필수. 없으면 요청이 500으로 거절됨 |
| `PROMPT_WAV` / `PROMPT_TEXT` | 기본 화자의 음성과 대본. 시작할 때 등록하므로 없으면 서버가 켜지지 않음. 대본은 음성과 글자까지 같아야 함 |
| `COSYVOICE_MODEL_DIR` | 모델 경로 (기본 `pretrained_models/CosyVoice2-0.5B`) |

**사용 예시**

```bash
# 목소리 등록 (고정 대본 ENROLL_PROMPT_TEXT를 읽은 24kHz 모노 WAV)
curl -X POST http://localhost:8001/enroll \
  -H "x-api-key: $TTS_API_KEY" -F spk_id=spk_1 -F file=@recording.wav

# 스트리밍 합성 후 재생
curl -s -X POST http://localhost:8001/tts_stream \
  -H "x-api-key: $TTS_API_KEY" -H "Content-Type: application/json" \
  -d '{"text":"안녕하세요, 오늘은 어떻게 보내셨어요?","spk_id":"spk_1"}' \
  | aplay -f S16_LE -r 24000 -c 1 -
```

서버는 업로드된 음성을 변환하지 않으므로, 등록 전에 24kHz 모노 WAV로 맞춰야 합니다.

---

## 📊 성능

RTX 2080 Ti에서 같은 문장으로 측정했습니다. 합성은 확률적이라 오디오 길이는 매번 달라집니다.

| 변경 | 결과 |
|---|---|
| 스트리밍 합성 도입 (인형에서 측정) | 첫 소리까지 5.46초 → 3.58초 |
| 전용 GPU + 8초 참조 (이전: 다른 작업과 GPU 공유 + 18초 참조) | 서버 첫 청크 약 3.45초 → 약 2.51초 |
| TensorRT (선택, `load_trt=True`) | 서버 첫 청크 약 2.19초, 합성 속도 약 14% 향상 |

GPU 변경과 참조 음성 단축은 한꺼번에 바꿔서 각각의 효과를 분리하지 못했습니다. TensorRT는 이득이 작아 필수는 아닙니다.

---

> 🔒 **실제 사람의 목소리를 복제합니다.** 목소리를 등록하는 보호자 본인의 동의가 필요합니다. 음성 파일과 화자 정보(`spk2info.pt`)는 저장소에 올리지 않습니다 (`.gitignore`).
>
> 🔑 `TTS_API_KEY`는 코드에 쓰지 말고 환경변수로만 넣으세요. 서버를 외부에 공개한다면 충분히 긴 값을 쓰세요.

모델과 추론 코드는 [FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice)의 라이선스를 따릅니다.
