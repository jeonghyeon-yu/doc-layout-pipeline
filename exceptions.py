"""커스텀 예외 클래스"""
from typing import Optional


class PipelineError(Exception):
    """파이프라인 기본 예외"""
    def __init__(self, message: str, step: Optional[str] = None):
        self.message = message
        self.step = step
        super().__init__(self.message)
    
    def __str__(self):
        if self.step:
            return f"[{self.step}] {self.message}"
        return self.message


class LayoutParsingError(PipelineError):
    """레이아웃 파싱 에러"""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, step="레이아웃 파싱")
        self.details = details


class TextExtractionError(PipelineError):
    """텍스트 추출 에러"""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, step="텍스트 추출")
        self.details = details


class VLMProcessingError(PipelineError):
    """VLM 처리 에러"""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, step="VLM 처리")
        self.details = details


class HierarchyParsingError(PipelineError):
    """계층 구조 파싱 에러"""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, step="계층 구조 파싱")
        self.details = details


class SectionExportError(PipelineError):
    """섹션 내보내기 에러"""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, step="섹션 내보내기")
        self.details = details


class ConfigError(PipelineError):
    """설정 에러"""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, step="설정")
        self.details = details
