# Windows Docker Desktop에서 GPU 사용 설정 가이드

RTX 4090 GPU를 Docker에서 사용하기 위한 설정 방법입니다.

## 방법 1: Docker Desktop 자동 설정 (가장 간단)

최신 Docker Desktop은 WSL2 백엔드를 사용하면 자동으로 GPU를 인식할 수 있습니다.

### 1. Docker Desktop 설정 확인
- Docker Desktop > Settings > General
- "Use the WSL 2 based engine" 체크 확인
- Settings > Resources > WSL Integration
- Ubuntu 배포판이 활성화되어 있는지 확인

### 2. NVIDIA 드라이버 확인
```powershell
nvidia-smi
```
RTX 4090이 인식되는지 확인

### 3. GPU 테스트 (PowerShell에서 직접 실행)
```powershell
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

**이 명령어가 작동하면 추가 설정 없이 바로 사용 가능합니다!**

## 방법 2: WSL2에서 수동 설정 (방법 1이 작동하지 않는 경우)

방법 1에서 GPU가 인식되지 않으면 WSL2에서 수동 설정이 필요합니다.

### 1. WSL2 설치 확인
```powershell
wsl --version
```
WSL2가 설치되어 있지 않으면:
```powershell
wsl --install
```

### 2. WSL2에서 NVIDIA Container Toolkit 설치

**PowerShell에서 한 번에 실행 (Ubuntu 접속 없이):**
```powershell
wsl -d Ubuntu -e bash -c "distribution=\$(. /etc/os-release;echo \$ID\$VERSION_ID) && curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add - && curl -s -L https://nvidia.github.io/nvidia-docker/\$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list && sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit && sudo service docker restart"
```

또는 **간단하게:**
```powershell
wsl -d Ubuntu -e bash -c "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list && sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit"
```

### 3. Docker Desktop 재시작

Windows에서 Docker Desktop을 완전히 종료하고 다시 시작

### 4. GPU 테스트

```powershell
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

## 5. vLLM 서버 실행

```bash
cd services/vlm_server
docker-compose up -d
docker-compose logs -f qwen3-vl
```

## 문제 해결

### GPU가 인식되지 않는 경우

1. **Docker Desktop에서 GPU 지원 확인**
   - Settings > Resources > WSL Integration
   - Ubuntu 배포판이 활성화되어 있는지 확인

2. **WSL2에서 nvidia-smi 확인**
   ```bash
   wsl -d Ubuntu
   nvidia-smi
   ```

3. **Docker Desktop 재시작**
   - 완전히 종료 후 재시작

### CUDA 버전 오류

RTX 4090은 CUDA 12.x를 지원합니다. vLLM 이미지가 CUDA 12.9를 요구하는 경우:
- NVIDIA 드라이버를 최신 버전으로 업데이트
- 또는 더 낮은 CUDA 버전의 vLLM 이미지 사용

## 참고

- RTX 4090: 24GB VRAM (Qwen3-VL-8B 실행 가능)
- CUDA 버전: 12.1 이상 권장
- Docker Desktop: 최신 버전 사용 권장

