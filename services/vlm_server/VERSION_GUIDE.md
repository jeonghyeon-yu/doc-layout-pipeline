# vLLM Docker 이미지 버전 가이드

## 문제 상황

- **Qwen3-VL 지원**: vLLM >= 0.11.0 필요
- **CUDA 호환성**: latest 이미지는 CUDA 12.9 요구 (RTX 4090에서 오류 발생 가능)

## 해결 방법

### 방법 1: CUDA 버전 확인 후 맞는 이미지 사용

```powershell
# CUDA 버전 확인
nvidia-smi
```

**CUDA 버전별 권장 이미지:**
- **CUDA 12.1/12.2**: `vllm/vllm-openai:v0.6.3-post1` 또는 `v0.7.0`
- **CUDA 12.9**: `vllm/vllm-openai:latest` (Qwen3-VL 지원)

### 방법 2: 사용 가능한 태그 확인

Docker Hub에서 사용 가능한 태그 확인:
- https://hub.docker.com/r/vllm/vllm-openai/tags

### 방법 3: Qwen3-VL 대신 Qwen2.5-VL 사용

Qwen3-VL이 작동하지 않는 경우:

```yaml
command: >
  --model Qwen/Qwen2.5-VL-7B-Instruct
  --trust-remote-code
  # ... 나머지 옵션
```

### 방법 4: CUDA 드라이버 업데이트

RTX 4090에서 CUDA 12.9를 지원하려면:
1. NVIDIA 드라이버 최신 버전 설치
2. CUDA Toolkit 12.9 설치 (필요한 경우)

## 현재 설정

`docker-compose.yml`에서 이미지 버전을 변경하여 테스트:

```yaml
image: vllm/vllm-openai:v0.6.3-post1  # CUDA 12.1/12.2 호환
# 또는
image: vllm/vllm-openai:v0.7.0        # 중간 버전 시도
# 또는  
image: vllm/vllm-openai:latest        # CUDA 12.9 필요
```

## 테스트 순서

1. `v0.6.3-post1` 시도 (CUDA 호환성 우선)
2. `v0.7.0` 시도
3. `v0.8.0` 시도
4. `latest` 시도 (CUDA 12.9 업데이트 후)

각 버전에서 `--trust-remote-code` 옵션이 필요합니다.

