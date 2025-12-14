# Qwen3-VL 서빙 대안 방법

vLLM이 Qwen3-VL의 멀티모달을 완전히 지원하지 않는 경우를 위한 대안입니다.

## 방법 1: Transformers + FastAPI 직접 구현

```python
# services/vlm_server/qwen3_vl_server.py
from fastapi import FastAPI
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
import torch
from PIL import Image
import base64
import io

app = FastAPI()

# 모델 로드
model = Qwen2VLForConditionalGeneration.from_pretrained(
    "Qwen/Qwen3-VL-8B-Instruct",
    torch_dtype=torch.float16,
    device_map="auto"
)
processor = AutoProcessor.from_pretrained("Qwen/Qwen3-VL-8B-Instruct")

@app.post("/v1/chat/completions")
async def chat_completions(request: dict):
    # 이미지와 텍스트 처리
    # ...
    pass
```

## 방법 2: Qwen 공식 서빙 방법 확인

Qwen 공식 GitHub에서 제공하는 서빙 방법을 확인:
- https://github.com/QwenLM/Qwen3-VL

## 방법 3: 다른 멀티모달 서빙 프레임워크

- **TGI (Text Generation Inference)**: Hugging Face의 서빙 프레임워크
- **Ray Serve**: 분산 서빙 프레임워크
- **TensorRT-LLM**: NVIDIA의 최적화 서빙

## 현재 설정 테스트

먼저 현재 vLLM 설정이 작동하는지 테스트:

```bash
cd services/vlm_server
docker-compose up -d
docker-compose logs -f qwen3-vl
```

API 테스트:
```bash
curl http://localhost:8000/v1/models
```

작동하지 않으면 위의 대안 방법을 사용하세요.

