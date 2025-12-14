FROM vllm/vllm-openai:v0.11.0

# Qwen3-VL recipe에서 권장
RUN pip install --no-cache-dir qwen-vl-utils==0.0.14

# (권장) Qwen3-VL은 transformers 버전 요구가 빡센 편이라 안전하게 올려두기
RUN pip install --no-cache-dir "transformers>=4.57.0"