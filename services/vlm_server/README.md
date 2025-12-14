# VLM Server 설정 가이드

이 폴더는 VLM (Vision-Language Model) 서버 관련 설정을 포함합니다.

## 현재 지원 모델

- **Qwen3-VL**: Alibaba의 멀티모달 모델

**vLLM 공식 지원 확인**: [vLLM Qwen3-VL 공식 문서](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3-VL.html)
- vLLM >= 0.11.0에서 Qwen3-VL 멀티모달 지원
- OpenAI 호환 API 제공
- 이미지 및 비디오 처리 지원

## 1. Qwen3-VL Docker 실행

### 사전 준비

1. **GPU 사용 설정 (RTX 4090)**
   - **방법 1 (권장)**: 최신 Docker Desktop (4.19.0+)은 Windows에서 직접 GPU 지원
     - Docker Desktop 업데이트 후 바로 사용 가능
     - `docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi`로 테스트
   - **방법 2**: WSL2 백엔드 사용 (방법 1이 작동하지 않는 경우)
     - 자세한 설정 방법: [GPU_SETUP.md](./GPU_SETUP.md) 참고
   - GPU 설정이 완료되면 `docker-compose.yml`에서 GPU 설정이 활성화되어 있습니다

2. **Docker Desktop 실행 확인**
   - Windows: Docker Desktop이 실행 중인지 확인
   - `docker ps` 명령어로 Docker가 정상 작동하는지 확인

3. **볼륨 경로 설정 (Windows)**
   - Windows에서는 HuggingFace 캐시 경로를 명시적으로 설정해야 할 수 있습니다
   - `docker-compose.yml`의 volumes 섹션을 확인하세요

### Docker Compose로 실행 (권장)

```bash
# VLM 서버 폴더로 이동
cd services/vlm_server

# Docker Compose로 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f qwen3-vl

# 중지
docker-compose down
```

**Windows에서 볼륨 경로 오류가 발생하는 경우:**

`docker-compose.yml`의 volumes 섹션을 다음과 같이 수정:
```yaml
volumes:
  - C:/Users/YourUsername/.cache/huggingface:/root/.cache/huggingface
```

### Docker 명령어로 직접 실행

**GPU 사용 (NVIDIA, CUDA >= 12.9 필요):**
```bash
docker run --gpus all -d \
  --name qwen3-vl-api \
  -p 8000:8000 \
  -v huggingface_cache:/root/.cache/huggingface \
  vllm/vllm-openai:latest \
  --model Qwen/Qwen3-VL-8B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --limit-mm-per-prompt.video 0
```

**CPU만 사용 (느림, 테스트용):**
```bash
docker run -d \
  --name qwen3-vl-api \
  -p 8000:8000 \
  -v huggingface_cache:/root/.cache/huggingface \
  vllm/vllm-openai:latest \
  --model Qwen/Qwen3-VL-8B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --device cpu \
  --limit-mm-per-prompt.video 0
```

**참고**: 
- GPU 사용 시 CUDA >= 12.9 필요 (오류 발생 시 CPU 모드 사용)
- `--limit-mm-per-prompt.video 0`: 이미지만 처리할 경우 비디오 메모리 예약 비활성화
- 공식 문서: https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3-VL.html

## 2. API 확인

```bash
# API 상태 확인
curl http://localhost:8888/health

# 모델 목록 확인
curl http://localhost:8888/v1/models
```

## 3. Python에서 사용

```python
import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.vlm_server.qwen3_vl_client import create_qwen3vl_client
from PIL import Image

# 클라이언트 생성 (기본 포트: 8888)
client = create_qwen3vl_client()

# 다른 포트 사용 시
# client = create_qwen3vl_client(api_base="http://localhost:8888/v1")

# 이미지 처리
img = Image.open("path/to/image.png")

# 테이블 처리
table_markdown = client.process_table(img)

# 차트 처리
chart_summary = client.process_chart(img)

# 그림 처리
figure_summary = client.process_figure(img)
```

## 4. object_parsing과 통합

```python
import sys
from pathlib import Path
from PIL import Image

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.vlm_server.qwen3_vl_client import create_qwen3vl_client
from object_parsing.vlm_processor import process_vlm_blocks_from_images

# Qwen3-VL 클라이언트 생성
client = create_qwen3vl_client()

# VLM 함수 정의
def table_vlm_function(img: Image.Image) -> str:
    return client.process_table(img)

def chart_vlm_function(img: Image.Image) -> str:
    return client.process_chart(img)

def figure_vlm_function(img: Image.Image) -> str:
    return client.process_figure(img)

# VLM 처리
vlm_functions = {
    "table": table_vlm_function,
    "chart": chart_vlm_function,
    "figure": figure_vlm_function
}

process_vlm_blocks_from_images(
    parsing_results_dir=Path("output/test/layout_parsing_output/parsing_results"),
    base_output_dir=Path("output/test/layout_parsing_output"),
    vlm_functions=vlm_functions
)
```

## 5. 다른 모델 추가하기

새로운 VLM 모델을 추가하려면:

1. `services/vlm_server/` 폴더에 새 클라이언트 파일 생성 (예: `claude_client.py`)
2. `docker-compose.yml`에 새 서비스 추가 (필요한 경우)
3. `object_parsing/vlm_processor.py`에서 사용

## 주의사항

1. **GPU 필수**: vLLM은 GPU 전용 프레임워크입니다. CPU 모드는 제한적으로 지원되거나 작동하지 않을 수 있습니다.
2. **CUDA 요구사항**: 
   - CUDA >= 12.9 필요 (최신 vLLM 이미지 기준)
   - NVIDIA 드라이버 업데이트 필요할 수 있음
3. **CPU 모드 문제**: CPU 모드에서 `Failed to infer device type` 오류가 발생하는 경우:
   - GPU가 있는 서버에서 실행하는 것을 권장
   - 또는 다른 서빙 방법 고려 (Transformers + FastAPI 등)
4. **포트**: 기본 포트는 8888입니다. `docker-compose.yml`에서 변경 가능합니다.
5. **API 키**: 보안이 필요한 경우 `docker-compose.yml`에서 API 키를 설정하세요.
6. **첫 실행**: 모델 다운로드로 시간이 걸릴 수 있습니다.

