"""Qwen3-VL API 클라이언트"""
import base64
import requests
from pathlib import Path
from typing import Optional
from PIL import Image
import io
import json


class Qwen3VLClient:
    """Qwen3-VL API 클라이언트"""
    
    def __init__(self, api_base: str = "http://localhost:8888/v1", api_key: Optional[str] = None):
        """
        Qwen3-VL API 클라이언트 초기화
        
        Args:
            api_base: API 베이스 URL (기본값: http://localhost:8000/v1)
            api_key: API 키 (선택사항)
        """
        self.api_base = api_base.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json"
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
    
    def _image_to_base64(self, img: Image.Image) -> str:
        """PIL Image를 base64 문자열로 변환"""
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        return img_str
    
    def _image_path_to_base64(self, image_path: Path) -> str:
        """이미지 파일 경로를 base64 문자열로 변환"""
        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode()
        return img_data
    
    def process_table(self, img: Image.Image, prompt: Optional[str] = None) -> str:
        """
        테이블 이미지를 markdown 형식으로 변환
        
        Args:
            img: PIL Image 객체
            prompt: 사용자 프롬프트 (None이면 기본 프롬프트 사용)
        
        Returns:
            Markdown 형식의 테이블 내용
        """
        if prompt is None:
            prompt = """이 이미지는 문서의 테이블입니다. 
테이블의 모든 내용을 정확하게 markdown 형식의 테이블로 변환해주세요.
헤더와 모든 행, 열의 데이터를 포함해야 합니다.
응답은 markdown 코드 블록(```markdown ... ```)으로 감싸주세요."""
        
        return self._process_image(img, prompt)
    
    def process_chart(self, img: Image.Image, prompt: Optional[str] = None) -> str:
        """
        차트 이미지를 요약
        
        Args:
            img: PIL Image 객체
            prompt: 사용자 프롬프트 (None이면 기본 프롬프트 사용)
        
        Returns:
            차트 요약 텍스트
        """
        if prompt is None:
            prompt = """이 이미지는 문서의 차트입니다.
                    차트의 주요 내용, 데이터 트렌드, 중요한 인사이트를 요약해주세요.
                    한국어로 작성해주세요."""
        
        return self._process_image(img, prompt)
    
    def process_figure(self, img: Image.Image, prompt: Optional[str] = None) -> str:
        """
        그림/도표 이미지를 요약
        
        Args:
            img: PIL Image 객체
            prompt: 사용자 프롬프트 (None이면 기본 프롬프트 사용)
        
        Returns:
            그림 요약 텍스트
        """
        if prompt is None:
            prompt = """이 이미지는 문서의 그림 또는 도표입니다.
                    그림의 주요 내용과 의미를 요약해주세요.
                    한국어로 작성해주세요."""
        
        return self._process_image(img, prompt)
    
    def process_image(self, img: Image.Image, prompt: Optional[str] = None) -> str:
        """
        일반 이미지를 요약
        
        Args:
            img: PIL Image 객체
            prompt: 사용자 프롬프트 (None이면 기본 프롬프트 사용)
        
        Returns:
            이미지 요약 텍스트
        """
        if prompt is None:
            prompt = """이 이미지는 문서에 포함된 이미지입니다.
                    이미지의 주요 내용과 의미를 설명해주세요.
                    한국어로 작성해주세요."""
        
        return self._process_image(img, prompt)
    
    def process_formula(self, img: Image.Image, prompt: Optional[str] = None) -> str:
        """
        수식 이미지를 LaTeX 형식으로 변환
        
        Args:
            img: PIL Image 객체
            prompt: 사용자 프롬프트 (None이면 기본 프롬프트 사용)
        
        Returns:
            LaTeX 형식의 수식 텍스트
        """
        if prompt is None:
            prompt = """이 이미지는 문서의 수식입니다.
                    수식을 정확하게 LaTeX 형식으로만 변환해주세요.
                    LaTeX 코드만 반환하고, 설명이나 다른 텍스트는 포함하지 마세요.
                    예: $E = mc^2$ 또는 \\[\\int_{0}^{\\infty} e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}\\]
                    응답은 LaTeX 수식 코드만 포함해야 합니다."""
        
        return self._process_image(img, prompt)
    
    def _process_image(self, img: Image.Image, prompt: str) -> str:
        """
        이미지를 Qwen3-VL API로 처리
        
        Args:
            img: PIL Image 객체
            prompt: 처리 프롬프트
        
        Returns:
            모델 응답 텍스트
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # 이미지를 base64로 변환
        img_base64 = self._image_to_base64(img)
        logger.debug(f"이미지 base64 변환 완료: {len(img_base64)} chars")
        logger.debug(f"프롬프트: {prompt[:100]}..." if len(prompt) > 100 else f"프롬프트: {prompt}")
        
        # Qwen3-VL API 요청 형식
        # 참고: Qwen3-VL은 멀티모달 모델이므로 messages API를 사용
        url = f"{self.api_base}/chat/completions"
        
        # vLLM OpenAI 호환 API 형식 (공식 문서 참고)
        # https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3-VL.html#consume-the-openai-api-compatible-server
        payload = {
            "model": "Qwen/Qwen3-VL-8B-Instruct",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{img_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.1
        }
        
        try:
            logger.info(f"VLM API 요청 전송: {url}")
            logger.debug(f"요청 payload: {json.dumps(payload, ensure_ascii=False, indent=2)[:1000]}...")
            response = requests.post(url, headers=self.headers, json=payload, timeout=120)
            
            # 에러 응답의 상세 내용 확인
            if not response.ok:
                error_detail = response.text
                logger.error(f"API 요청 실패 ({response.status_code}): {error_detail}")
                logger.error(f"요청 payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
                response.raise_for_status()
            
            result = response.json()
            logger.debug(f"API 응답 수신: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}...")
            
            # 응답에서 텍스트 추출
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                logger.info(f"VLM 응답 수신: {len(content)} chars")
                return content.strip()
            else:
                logger.error(f"예상치 못한 API 응답: {result}")
                raise ValueError(f"Unexpected API response: {result}")
                
        except requests.exceptions.HTTPError as e:
            error_detail = response.text if 'response' in locals() else str(e)
            logger.error(f"API 요청 실패: {e}")
            logger.error(f"에러 상세: {error_detail}")
            raise Exception(f"API 요청 실패: {e} - {error_detail}")
        except requests.exceptions.RequestException as e:
            logger.error(f"API 요청 실패: {e}", exc_info=True)
            raise Exception(f"API 요청 실패: {e}")
        except Exception as e:
            logger.error(f"이미지 처리 실패: {e}", exc_info=True)
            raise Exception(f"이미지 처리 실패: {e}")
    
    def process_image_file(self, image_path: Path, prompt: str) -> str:
        """
        이미지 파일 경로를 받아서 처리
        
        Args:
            image_path: 이미지 파일 경로
            prompt: 처리 프롬프트
        
        Returns:
            모델 응답 텍스트
        """
        img = Image.open(image_path)
        return self._process_image(img, prompt)


def create_qwen3vl_client(api_base: str = "http://localhost:8888/v1", api_key: Optional[str] = None) -> Qwen3VLClient:
    """
    Qwen3-VL 클라이언트 생성 헬퍼 함수
    
    Args:
        api_base: API 베이스 URL
        api_key: API 키 (선택사항)
    
    Returns:
        Qwen3VLClient 인스턴스
    """
    return Qwen3VLClient(api_base=api_base, api_key=api_key)


if __name__ == "__main__":
    # 테스트
    from pathlib import Path
    
    # 클라이언트 생성
    client = create_qwen3vl_client()
    
    # 테스트 이미지 경로
    test_image_path = Path("../../output/test/layout_parsing_output/table/page_0010_0_res_block_0.png")
    
    if test_image_path.exists():
        print(f"[TEST] 이미지 처리 테스트: {test_image_path}")
        
        # 테이블 처리 테스트
        try:
            result = client.process_table(Image.open(test_image_path))
            print(f"\n[결과]")
            print(result)
        except Exception as e:
            print(f"[ERROR] {e}")
    else:
        print(f"[ERROR] 테스트 이미지를 찾을 수 없습니다: {test_image_path}")

