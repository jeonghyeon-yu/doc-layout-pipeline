"""설정 로더"""
import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Config:
    """설정 데이터 클래스"""
    # 경로 설정
    input_path: str = "work.pdf"
    output_dir: str = "output"
    
    # 워커 설정
    max_workers: int = 5
    
    # VLM 설정
    vlm_enabled: bool = True
    vlm_api_base: str = "http://localhost:8888/v1"
    vlm_api_key: str = "optional-api-key-here"
    vlm_batch_size: int = 10
    vlm_prompts: Dict[str, str] = field(default_factory=dict)
    
    # 로깅 설정
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # 문서 설정
    doc_type: str = "insurance"
    
    # 출력 파일명
    output_hierarchy_file: str = "document_hierarchy.json"
    output_references_file: str = "document_hierarchy_references.json"
    output_neo4j_export_dir: str = "neo4j_export"
    
    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> 'Config':
        """환경 변수 또는 .env 파일에서 설정 로드"""
        if env_file:
            _load_env_file(env_file)
        
        return cls(
            input_path=os.getenv("INPUT_PATH", "work.pdf"),
            output_dir=os.getenv("OUT_DIR", "output"),
            max_workers=int(os.getenv("MAX_WORKERS", "5")),
            vlm_enabled=os.getenv("ENABLE_VLM_PROCESSING", "true").lower() == "true",
            vlm_api_base=os.getenv("VLM_API_BASE", "http://localhost:8888/v1"),
            vlm_api_key=os.getenv("VLM_API_KEY", "optional-api-key-here"),
            vlm_batch_size=int(os.getenv("VLM_BATCH_SIZE", "10")),
            vlm_prompts={},  # TODO: JSON 파싱 지원
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
            doc_type=os.getenv("DOC_TYPE", "insurance"),
            output_hierarchy_file=os.getenv("OUTPUT_HIERARCHY_FILE", "document_hierarchy.json"),
            output_references_file=os.getenv("OUTPUT_REFERENCES_FILE", "document_hierarchy_references.json"),
            output_neo4j_export_dir=os.getenv("OUTPUT_NEO4J_EXPORT_DIR", "neo4j_export"),
        )


def _load_env_file(env_file: str) -> None:
    """.env 파일 로드"""
    env_path = Path(env_file)
    if not env_path.exists():
        logger.warning(f".env 파일을 찾을 수 없습니다: {env_file}")
        return
    
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # 주석 및 빈 줄 무시
            if not line or line.startswith('#'):
                continue
            
            # KEY=VALUE 파싱
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value


def load_config(env_file: Optional[str] = ".env") -> Config:
    """
    설정 로드
    
    Args:
        env_file: .env 파일 경로 (None이면 환경 변수만 사용)
    
    Returns:
        Config 객체
    """
    if env_file and Path(env_file).exists():
        logger.info(f"설정 파일 로드: {env_file}")
        return Config.from_env(env_file)
    else:
        logger.info("환경 변수에서 설정 로드")
        return Config.from_env(None)
