# voice-cloning

한이음 드림업 **기억고팡** 팀의 AI 회상 인형 **모리**가 **보호자의 목소리로 말하도록** 구현한 Voice Cloning TTS 서버입니다.
[CosyVoice2](https://github.com/FunAudioLLM/CosyVoice)의 zero-shot voice cloning을 FastAPI로 감싸, 보호자의 짧은 녹음으로 목소리를 등록하고 대화 답변을 그 목소리로 스트리밍 합성합니다.

> 이 저장소에는 서버 코드(`server_stream.py`)만 있습니다. 모델 가중치와 음성 파일은 포함하지 않습니다.

## 동작 방식

별도 모델 학습 없이, 보호자의 **참조 음성 + 그 음성의 대본**만으로 목소리 특징을 추출하는 zero-shot 방식입니다.

1. **등록**: 참조 음성과 대본에서 목소리 특징을 추출해 `spk_id`로 저장합니다 (몇 초 소요, 서버를 재시작해도 유지).
2. **합성**: 답변 텍스트와 `spk_id`를 보내면 그 목소리로 합성한 음성이 돌아옵니다. 참조 음성은 매번 다시 처리하지 않습니다.

모델은 하나를 공용으로 쓰므로 보호자가 늘어도 모델을 다시 학습할 필요가 없습니다.

## API

모든 요청(`/health` 제외)에 `x-api-key` 헤더가 필요합니다.

| 엔드포인트 | 설명 |
|---|---|
| `GET /health` | 상태 확인 |
| `POST /enroll` | 목소리 등록. `multipart/form-data`로 `spk_id`(문자열)와 `file`(참조 음성) 전송 |
| `POST /tts` | 합성. JSON `{"text": "...", "spk_id": "..."}` → `audio/wav` (`spk_id` 생략 시 기본 화자) |
| `POST /tts_stream` | 스트리밍 합성. 같은 요청 → raw PCM 조각 (`application/octet-stream`) |

`/tts_stream` 응답은 헤더 없는 **16bit signed little-endian, 24kHz, 모노 PCM**입니다. 받는 대로 재생할 수 있습니다.

```bash
aplay -f S16_LE -r 24000 -c 1 -   # 받은 바이트를 stdin으로
```

## 실행

서버는 CosyVoice 저장소 루트에서 실행하도록 작성되어 있습니다 (`third_party/Matcha-TTS` 경로 사용).

1. [CosyVoice](https://github.com/FunAudioLLM/CosyVoice)를 clone하고, 안내에 따라 환경을 만들고 `CosyVoice2-0.5B` 모델을 `pretrained_models/`에 받습니다.
2. 이 저장소의 `server_stream.py`를 CosyVoice 저장소 루트에 복사합니다.
3. 기본 화자로 쓸 **참조 음성**(24kHz 모노 WAV)과 그 **대본**을 준비합니다.
4. 환경변수를 설정하고 실행합니다.

```bash
export TTS_API_KEY="<직접 정한 긴 랜덤 문자열>"
export PROMPT_WAV=my_reference.wav
export PROMPT_TEXT="참조 음성에서 말한 내용 그대로"
python -m uvicorn server_stream:app --host 0.0.0.0 --port 8001
```

| 환경변수 | 설명 |
|---|---|
| `TTS_API_KEY` | **필수.** 없으면 요청이 500으로 거절됩니다 |
| `PROMPT_WAV` | 기본 화자의 참조 음성 경로 (기본값 `caregiver_ref.wav`) |
| `PROMPT_TEXT` | 그 음성의 대본. **음성과 글자까지 같아야** 품질이 나옵니다 |
| `COSYVOICE_MODEL_DIR` | 모델 경로 (기본값 `pretrained_models/CosyVoice2-0.5B`) |

서버를 켤 때 기본 화자를 먼저 등록하므로, `PROMPT_WAV` 파일이 없으면 시작되지 않습니다.

## 사용 예시

```bash
# 목소리 등록 (파일은 고정 대본을 읽은 24kHz 모노 WAV)
curl -X POST http://localhost:8001/enroll \
  -H "x-api-key: $TTS_API_KEY" \
  -F spk_id=spk_1 -F file=@recording.wav

# 스트리밍 합성 후 재생
curl -s -X POST http://localhost:8001/tts_stream \
  -H "x-api-key: $TTS_API_KEY" -H "Content-Type: application/json" \
  -d '{"text":"안녕하세요, 오늘은 어떻게 보내셨어요?","spk_id":"spk_1"}' \
  | aplay -f S16_LE -r 24000 -c 1 -
```

`/enroll`은 서버가 정해둔 고정 대본(`ENROLL_PROMPT_TEXT`)을 사용합니다. 녹음 화면은 그 문장을 그대로 보여주고 처음부터 끝까지 읽게 해야 하며, 서버는 업로드된 음성을 변환하지 않으므로 **업로드 전에 24kHz 모노 WAV로 맞춰야** 합니다.

## 성능 메모

RTX 2080 Ti에서 같은 문장으로 측정한 값입니다. 합성은 확률적이라 오디오 길이는 매번 달라집니다.

| 변경 | 결과 |
|---|---|
| 스트리밍 합성 도입 (인형에서 측정) | 첫 소리까지 5.46초 → 3.58초 |
| 다른 작업과 GPU를 나눠 쓰던 상태 + 18초 참조 → 전용 GPU + 8초 참조 | 서버 첫 청크 약 3.45초 → 약 2.51초 |
| TensorRT (선택) | 서버 첫 청크 약 2.51초 → 약 2.19초, 합성 속도 약 14% 향상 |

- GPU 변경과 참조 음성 단축은 한꺼번에 바꿨기 때문에 각각의 효과는 분리해서 측정하지 못했습니다.
- 참조 음성을 짧게 하면 빨라질 수 있지만 목소리 닮은 정도가 떨어질 수 있으며, 엄밀하게 비교하지는 않았습니다.
- TensorRT를 쓰려면 CosyVoice의 `requirements.txt`에 맞는 `tensorrt-cu12`를 설치하고 서버의 `load_trt=False`를 `True`로 바꿉니다. 첫 실행 때 엔진을 빌드합니다(약 1~2분). 효과가 작아 필수는 아닙니다.

## 주의

- 이 서버는 **실제 사람의 목소리를 복제**합니다. 목소리를 등록하는 보호자 본인의 동의를 받아야 합니다.
- 음성 파일과 화자 정보(`spk2info.pt`)는 저장소에 올리지 마세요. `.gitignore`에 제외되어 있습니다.
- API 키는 코드에 넣지 말고 환경변수로만 주입하세요.
- 서버를 인터넷에 공개할 때는 `TTS_API_KEY`가 유일한 방어선이므로 충분히 긴 값을 쓰세요.

## 라이선스와 출처

음성 합성 모델과 추론 코드는 [FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice)의 것이며, 해당 저장소의 라이선스를 따릅니다.
