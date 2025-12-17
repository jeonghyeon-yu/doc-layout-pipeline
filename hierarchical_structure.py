"""
하이브리드 법령 계층 구조 파서
================================

핵심 기능:
1. 상태 기반(State-based) 파싱: 현재 조/항/호/목 컨텍스트 추적
2. 컨텍스트 인식(Context-aware): 참조 vs 구조 구분
3. 블록 연속성 처리: 끊어진 문장 자동 병합
4. 암묵적 항 처리: ①없이 시작하는 조문 → 암묵적 1항

계층 구조: 조 > 항 > 호 > 목
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import defaultdict


# ============================================================================
# 1. 타입 정의
# ============================================================================

class PatternType(Enum):
    """패턴 타입"""
    STRUCTURE_편 = auto()
    STRUCTURE_장 = auto()
    STRUCTURE_관 = auto()
    STRUCTURE_약관 = auto()
    STRUCTURE_별표 = auto()
    STRUCTURE_용어정의 = auto()
    STRUCTURE_조 = auto()
    STRUCTURE_항 = auto()
    STRUCTURE_호 = auto()
    STRUCTURE_목 = auto()
    REFERENCE = auto()
    CONTENT = auto()
    CONTINUATION = auto()


@dataclass
class ParserContext:
    """파서 상태 컨텍스트"""
    # 상위 구조
    current_pyeon: Optional[int] = None  # 편
    current_jang: Optional[int] = None   # 장
    current_gwan: Optional[int] = None   # 관
    current_yakgwan: Optional[str] = None  # 약관명
    
    # 기존 구조
    current_jo: Optional[int] = None
    current_hang: Optional[int] = None
    current_ho: Optional[int] = None
    current_mok: Optional[str] = None
    
    # 기대값
    expected_pyeon: int = 1
    expected_jang: int = 1
    expected_gwan: int = 1
    expected_jo: int = 1
    expected_hang: int = 1
    expected_ho: int = 1
    expected_mok_idx: int = 0
    
    # 목 순서 (가나다라...)
    MOK_ORDER: List[str] = field(default_factory=lambda: [
        '가', '나', '다', '라', '마', '바', '사', '아', '자', '차', '카', '타', '파', '하'
    ])
    
    def get_expected_mok(self) -> str:
        if self.expected_mok_idx < len(self.MOK_ORDER):
            return self.MOK_ORDER[self.expected_mok_idx]
        return ''
    
    def reset_for_new_section(self):
        """새 관/장/약관 시작 시 조부터 초기화"""
        self.expected_jo = 1
        self.current_jo = None
        self.reset_hang()
    
    def reset_hang(self):
        """새 조 시작 시 항 초기화"""
        self.expected_hang = 1
        self.current_hang = None
        self.reset_ho()
    
    def reset_ho(self):
        """새 항 시작 시 호 초기화"""
        self.expected_ho = 1
        self.current_ho = None
        self.reset_mok()
    
    def reset_mok(self):
        """새 호 시작 시 목 초기화"""
        self.expected_mok_idx = 0
        self.current_mok = None


@dataclass
class Token:
    """토큰 (분석된 텍스트 단위)"""
    text: str
    pattern_type: PatternType
    structure_number: Optional[Any] = None  # 조/항/호 번호 또는 목 문자
    references: List[Dict] = field(default_factory=list)
    source_block: Optional[Dict] = None
    merged_blocks: List[Dict] = field(default_factory=list)


@dataclass 
class StructureNode:
    """계층 구조 노드"""
    type: str  # "document", "조", "항", "호", "목"
    number: Optional[Any] = None
    title: str = ""
    content: str = ""
    implicit: bool = False  # 암묵적 항 여부
    references: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    children: List['StructureNode'] = field(default_factory=list)
    source_blocks: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """딕셔너리로 변환"""
        result = {
            "type": self.type,
            "number": self.number,
            "title": self.title,
            "content": self.content,
            "children": [child.to_dict() for child in self.children]
        }
        
        if self.implicit:
            result["implicit"] = True
        if self.references:
            result["references"] = self.references
        if self.metadata:
            result["metadata"] = self.metadata
        if self.source_blocks:
            result["source_blocks"] = self.source_blocks
            
        return result


# ============================================================================
# 2. 패턴 인식기
# ============================================================================

class PatternRecognizer:
    """패턴 인식 및 분류"""
    
    # 원문자 매핑
    CIRCLED_NUMBERS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
    
    # 참조 조사 패턴
    REFERENCE_PARTICLES = r'(?:의|에|를|에서|으로|에\s*따[라른]|에\s*의한|에\s*해당|과|와|이|가)'
    
    # 약관명 패턴 (특별약관, 보통약관, 추가약관 등)
    # 약관명 패턴 - 첫 번째로 나오는 약관명만 추출 (non-greedy)
    # 순서 중요: 추가약관이 먼저 (더 짧은 매칭 우선)
    YAKGWAN_PATTERNS = [
        r'^([가-힣a-zA-Z0-9]+(?:\s+[가-힣a-zA-Z0-9]+)*?\s*추가특별약관(?:\([^)]+\))?)',
        r'^([가-힣a-zA-Z0-9]+(?:\s+[가-힣a-zA-Z0-9]+)*?\s*추가약관(?:\([^)]+\))?)',
        r'^([가-힣a-zA-Z0-9]+(?:\s+[가-힣a-zA-Z0-9]+)*?\s*특별약관(?:\([^)]+\))?)',
        r'^([가-힣a-zA-Z0-9]+(?:\s+[가-힣a-zA-Z0-9]+)*?\s*보통약관)',
    ]
    
    # 법규 인용 패턴 (여러 형태 지원)
    LAW_REFERENCE_PATTERNS = [
        r'^\[법규\s*(\d+)\]\s*(.+)$',      # [법규 1] 개인정보 보호법
        r'^【법규\s*(\d+)】\s*(.+)$',       # 【법규 1】 개인정보 보호법
        r'^【법규(\d+)】\s*(.+)$',          # 【법규1】 개인정보 보호법
    ]
    
    # 별표/표 패턴
    BYULPYO_PATTERNS = [
        r'^\[별표\s*(\d+)\]\s*(.*)$',       # [별표 1] 상해구분 및 보험금액
        r'^【별표\s*(\d+)】\s*(.*)$',        # 【별표 1】
        r'^\[별지\s*(\d+)\]\s*(.*)$',       # [별지 1]
        r'^별표\s*(\d+)\s*(.*)$',           # 별표 1
    ]
    
    # 용어 정의 패턴
    TERMINOLOGY_PATTERNS = [
        r'^※\s*용어의\s*정의\s*$',
        r'^용어의\s*정의\s*$',
    ]
    
    @classmethod
    def extract_byulpyo_pattern(cls, text: str) -> Optional[Tuple[int, str, int, int]]:
        """
        별표 패턴 추출: [별표 1] 상해구분 및 보험금액
        Returns: (별표번호, 제목, 시작위치, 끝위치) 또는 None
        """
        text_stripped = text.strip()
        for pattern in cls.BYULPYO_PATTERNS:
            match = re.match(pattern, text_stripped)
            if match:
                return (int(match.group(1)), match.group(2).strip() if match.lastindex >= 2 else '', match.start(), match.end())
        return None
    
    @classmethod
    def is_terminology_section(cls, text: str) -> bool:
        """용어 정의 섹션인지 확인"""
        text_stripped = text.strip()
        for pattern in cls.TERMINOLOGY_PATTERNS:
            if re.match(pattern, text_stripped):
                return True
        return False
    
    @classmethod
    def extract_law_reference_pattern(cls, text: str) -> Optional[Tuple[int, str, int, int]]:
        """
        법규 인용 패턴 추출: [법규 1] 또는 【법규1】 개인정보 보호법
        Returns: (법규번호, 법규명, 시작위치, 끝위치) 또는 None
        """
        text_stripped = text.strip()
        for pattern in cls.LAW_REFERENCE_PATTERNS:
            match = re.match(pattern, text_stripped)
            if match:
                return (int(match.group(1)), match.group(2).strip(), match.start(), match.end())
        return None
    
    @classmethod
    def find_law_reference_in_text(cls, text: str) -> Optional[Tuple[int, str, int, int]]:
        """
        텍스트 중간에서 법규 인용 패턴 찾기
        Returns: (법규번호, 법규명, 시작위치, 끝위치) 또는 None
        """
        patterns = [
            r'\[법규\s*(\d+)\]\s*([^\n\[【]+)',
            r'【법규\s*(\d+)】\s*([^\n\[【]+)',
            r'【법규(\d+)】\s*([^\n\[【]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return (int(match.group(1)), match.group(2).strip(), match.start(), match.end())
        return None
    
    @classmethod
    def extract_pyeon_pattern(cls, text: str) -> Optional[Tuple[int, str, int, int]]:
        """
        편(編) 패턴 추출
        Returns: (편번호, 제목, 시작위치, 끝위치) 또는 None
        """
        match = re.match(r'^제(\d+)편\s*(.*)$', text.strip())
        if match:
            return (int(match.group(1)), match.group(2).strip(), match.start(), match.end())
        return None
    
    @classmethod
    def extract_jang_pattern(cls, text: str) -> Optional[Tuple[int, str, int, int]]:
        """
        장(章) 패턴 추출
        Returns: (장번호, 제목, 시작위치, 끝위치) 또는 None
        """
        match = re.match(r'^제(\d+)장\s*(.*)$', text.strip())
        if match:
            return (int(match.group(1)), match.group(2).strip(), match.start(), match.end())
        return None
    
    @classmethod
    def extract_gwan_pattern(cls, text: str) -> Optional[Tuple[int, str, int, int]]:
        """
        관(款) 패턴 추출
        Returns: (관번호, 제목, 시작위치, 끝위치) 또는 None
        """
        match = re.match(r'^제(\d+)관\s*(.*)$', text.strip())
        if match:
            return (int(match.group(1)), match.group(2).strip(), match.start(), match.end())
        return None
    
    @classmethod
    def extract_yakgwan_pattern(cls, text: str) -> Optional[Tuple[str, int, int]]:
        """
        약관명 패턴 추출
        Returns: (약관명, 시작위치, 끝위치) 또는 None
        """
        text_stripped = text.strip()
        
        # "본 약관", "이 약관" 등으로 시작하면 약관명이 아님
        if text_stripped.startswith('본 ') or text_stripped.startswith('이 '):
            return None
        
        for pattern in cls.YAKGWAN_PATTERNS:
            match = re.match(pattern, text_stripped)
            if match:
                yakgwan_name = match.group(1).strip()
                # 너무 긴 텍스트는 약관명이 아님
                if len(yakgwan_name) <= 50:
                    return (yakgwan_name, 0, len(yakgwan_name))
        return None
    
    @classmethod
    def extract_jo_pattern(cls, text: str) -> Optional[Tuple[int, int, int]]:
        """
        조(條) 패턴 추출
        Returns: (조번호, 시작위치, 끝위치) 또는 None
        """
        match = re.search(r'제(\d+)조', text)
        if match:
            return (int(match.group(1)), match.start(), match.end())
        return None
    
    @classmethod
    def extract_hang_pattern(cls, text: str) -> Optional[Tuple[int, int, int]]:
        """
        항(項) 패턴 추출 (①, ②, ③...)
        Returns: (항번호, 시작위치, 끝위치) 또는 None
        """
        match = re.search(f'([{cls.CIRCLED_NUMBERS}])', text)
        if match:
            circled = match.group(1)
            num = cls.CIRCLED_NUMBERS.index(circled) + 1
            return (num, match.start(), match.end())
        return None
    
    @classmethod
    def extract_ho_pattern(cls, text: str) -> Optional[Tuple[int, int, int]]:
        """
        호(號) 패턴 추출 (1., 2., 3...)
        Returns: (호번호, 시작위치, 끝위치) 또는 None
        """
        # 문장 시작에서 호 패턴 찾기
        match = re.match(r'^(\d+)\.\s*', text.strip())
        if match:
            num = int(match.group(1))
            # 1-50 범위만 유효 (연도 제외)
            if 1 <= num <= 50:
                return (num, match.start(), match.end())
        return None
    
    @classmethod
    def extract_mok_pattern(cls, text: str) -> Optional[Tuple[str, int, int]]:
        """
        목(目) 패턴 추출 (가., 나., 다...)
        Returns: (목문자, 시작위치, 끝위치) 또는 None
        """
        match = re.match(r'^([가나다라마바사아자차카타파하])\.\s*', text.strip())
        if match:
            return (match.group(1), match.start(), match.end())
        return None
    
    @classmethod
    def is_reference_context(cls, text: str, match_end: int) -> bool:
        """
        해당 위치 이후가 참조 컨텍스트인지 판별
        예: "제24조에 따라" → True (참조)
            "제24조(목적)" → False (구조)
        """
        after_text = text[match_end:match_end + 20] if match_end < len(text) else ""
        
        # 참조 조사로 시작하면 참조
        if re.match(cls.REFERENCE_PARTICLES, after_text.strip()):
            return True
        
        # 제X조제Y항, 제X조제Y호 패턴도 참조
        if re.match(r'^제\d+[항호]', after_text.strip()):
            return True
            
        return False
    
    @classmethod
    def is_date_pattern(cls, text: str, match_start: int) -> bool:
        """
        날짜 패턴인지 판별 (예: 2018. 3. 20.)
        """
        # 앞 15자 확인
        before_text = text[max(0, match_start - 15):match_start]
        
        # 연도 패턴이 앞에 있으면 날짜
        if re.search(r'\d{4}\s*\.\s*$', before_text):
            return True
        
        # <개정, [시행 등의 패턴 뒤에 오면 날짜
        if re.search(r'[<\[]\s*(?:개정|시행|신설|삭제)?\s*\d{4}\s*\.\s*$', before_text):
            return True
            
        return False
    
    @classmethod
    def extract_references(cls, text: str) -> List[Dict]:
        """
        텍스트에서 모든 참조 추출
        """
        references = []
        
        # 1. 외부 참조 먼저 추출: 「법률명」 제X조
        # 외부 참조 위치를 기록하여 내부 참조에서 제외
        external_ranges = []
        external_pattern = r'「([^」]+)」\s*제(\d+)조(?:제(\d+)항)?(?:제(\d+)호)?'
        for match in re.finditer(external_pattern, text):
            ref = {
                "type": "external",
                "law": match.group(1),
                "조": int(match.group(2))
            }
            if match.group(3):
                ref["항"] = int(match.group(3))
            if match.group(4):
                ref["호"] = int(match.group(4))
            references.append(ref)
            # 외부 참조 범위 기록 (「 시작부터 끝까지)
            external_ranges.append((match.start(), match.end()))
        
        # 2. 내부 참조: 제X조, 제X조제Y항, 제X조제Y항제Z호
        # 단, 외부 참조 범위 내에 있는 것은 제외
        internal_pattern = r'제(\d+)조(?:제(\d+)항)?(?:제(\d+)호)?'
        for match in re.finditer(internal_pattern, text):
            # 외부 참조 범위 내에 있는지 확인
            is_in_external = False
            for ext_start, ext_end in external_ranges:
                if ext_start <= match.start() < ext_end:
                    is_in_external = True
                    break
            
            if is_in_external:
                continue  # 외부 참조에 포함된 것은 스킵
            
            # 문장 시작에 있고 구조 패턴인 경우는 제외 (조사가 없어야 함)
            # 그 외에는 모두 참조로 처리
            is_structure = False
            if match.start() == 0:
                # 문장 시작에서 조 패턴이고, 바로 뒤에 괄호나 원문자가 오면 구조
                after_text = text[match.end():match.end() + 5]
                if re.match(r'^[\(①]', after_text):
                    is_structure = True
                elif re.match(r'^[,\s]', after_text):
                    # 쉼표나 공백 뒤에 다른 조가 나열되면 참조
                    is_structure = False
                elif not cls.is_reference_context(text, match.end()) and not re.match(r'^[\s,]', after_text):
                    is_structure = True
            
            if not is_structure:
                ref = {"type": "internal", "조": int(match.group(1))}
                if match.group(2):
                    ref["항"] = int(match.group(2))
                if match.group(3):
                    ref["호"] = int(match.group(3))
                references.append(ref)
        
        # 3. 항/호만 참조: 제X항, 제X항제Y호 (조 없이)
        # 예: "제1항제6호에 따라" - 현재 조의 항/호 참조
        hang_only_pattern = r'(?<!조)제(\d+)항(?:제(\d+)호)?'
        for match in re.finditer(hang_only_pattern, text):
            # 외부 참조 범위 내에 있는지 확인
            is_in_external = False
            for ext_start, ext_end in external_ranges:
                if ext_start <= match.start() < ext_end:
                    is_in_external = True
                    break
            
            if is_in_external:
                continue
            
            # 이미 "제X조제Y항" 패턴으로 추출된 것인지 확인
            # 앞에 "제X조"가 바로 붙어있으면 스킵 (이미 위에서 처리됨)
            before_text = text[max(0, match.start()-10):match.start()]
            if re.search(r'제\d+조$', before_text):
                continue
            
            ref = {
                "type": "internal_relative",  # 상대 참조 (현재 조 기준)
                "항": int(match.group(1))
            }
            if match.group(2):
                ref["호"] = int(match.group(2))
            references.append(ref)
        
        return references
    
    @classmethod
    def extract_amendment_info(cls, text: str) -> Optional[Dict]:
        """
        개정 정보 추출
        예: <개정 2018. 3. 20., 2019. 1. 15.>
        """
        match = re.search(r'<\s*개정\s*([\d\s.,]+)>', text)
        if match:
            dates_str = match.group(1)
            dates = re.findall(r'(\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?)', dates_str)
            if dates:
                return {"개정": [d.strip().rstrip('.') for d in dates]}
        return None


# ============================================================================
# 3. 블록 전처리기 (연속성 판별 및 병합)
# ============================================================================

class BlockPreprocessor:
    """블록 전처리: 연속성 판별 및 병합"""
    
    # 불완전 종결 패턴
    INCOMPLETE_ENDINGS = (
        '있는', '하는', '되는', '으로', '에서', '에는', '으로서',
        ',', '및', '또는', '그리고', '다만', '단', '와', '과',
        '를', '을', '이', '가', '의', '에', '한', '된', '할'
    )
    
    # 완전 종결 패턴
    COMPLETE_ENDINGS = ('.', '다.', '음.', '함.', '임.', '것.', '수 있다.', '한다.', '된다.')
    
    @classmethod
    def is_continuation(cls, prev_content: str, curr_content: str) -> bool:
        """
        현재 블록이 이전 블록의 연속인지 판별
        """
        if not prev_content or not curr_content:
            return False
        
        curr_stripped = curr_content.strip()
        prev_stripped = prev_content.strip()
        
        # 1. 현재 블록이 구조 패턴으로 시작하면 연속 아님
        if cls._starts_with_structure_pattern(curr_stripped):
            return False
        
        # 2. 이전 블록이 불완전 종결이면 연속
        if cls._ends_incomplete(prev_stripped):
            return True
        
        # 3. 이전 블록이 완전 종결이고, 현재가 구조 패턴 없으면 → 같은 단위의 추가 문장일 수 있음
        # 하지만 기본적으로는 연속으로 처리
        if not cls._ends_complete(prev_stripped):
            return True
        
        return False
    
    @classmethod
    def _starts_with_structure_pattern(cls, text: str) -> bool:
        """구조 패턴으로 시작하는지"""
        patterns = [
            r'^제\d+편',                          # 편
            r'^제\d+장',                          # 장
            r'^제\d+관',                          # 관
            r'^제\d+조',                          # 조
            r'^\[법규\s*\d+\]',                   # [법규 1]
            r'^【법규\s*\d+】',                   # 【법규 1】
            r'^【법규\d+】',                      # 【법규1】
            r'^\[별표\s*\d+\]',                   # [별표 1]
            r'^【별표\s*\d+】',                   # 【별표 1】
            r'^별표\s*\d+',                       # 별표 1
            r'^※\s*용어의\s*정의',               # ※ 용어의 정의
            f'^[{PatternRecognizer.CIRCLED_NUMBERS}]',  # 항
            r'^\d+\.\s+',                          # 호
            r'^[가나다라마바사아자차카타파하]\.\s*',  # 목
        ]
        
        for pattern in patterns:
            if re.match(pattern, text):
                return True
        
        # 약관 패턴도 확인
        if PatternRecognizer.extract_yakgwan_pattern(text):
            return True
        
        return False
    
    @classmethod
    def _ends_incomplete(cls, text: str) -> bool:
        """불완전 종결인지"""
        for ending in cls.INCOMPLETE_ENDINGS:
            if text.endswith(ending):
                return True
        return False
    
    @classmethod
    def _ends_complete(cls, text: str) -> bool:
        """완전 종결인지"""
        for ending in cls.COMPLETE_ENDINGS:
            if text.endswith(ending):
                return True
        return False
    
    @classmethod
    def merge_blocks(cls, blocks: List[Dict]) -> List[Dict]:
        """
        연속 블록들을 병합
        """
        if not blocks:
            return []
        
        merged = []
        buffer = None
        
        for block in blocks:
            content = block.get('block_content', '').strip()
            
            if not content:
                continue
            
            if buffer is None:
                buffer = {
                    'block_content': content,
                    'block_label': block.get('block_label'),
                    'block_id': block.get('block_id'),
                    'block_order': block.get('block_order'),
                    'merged_from': [block]
                }
            elif cls.is_continuation(buffer['block_content'], content):
                # 병합: 공백 추가하여 연결
                buffer['block_content'] += ' ' + content
                buffer['merged_from'].append(block)
            else:
                # 이전 버퍼 저장, 새 버퍼 시작
                merged.append(buffer)
                buffer = {
                    'block_content': content,
                    'block_label': block.get('block_label'),
                    'block_id': block.get('block_id'),
                    'block_order': block.get('block_order'),
                    'merged_from': [block]
                }
        
        if buffer:
            merged.append(buffer)
        
        return merged


# ============================================================================
# 4. 토크나이저
# ============================================================================

class Tokenizer:
    """블록을 토큰으로 변환"""
    
    @classmethod
    def tokenize(cls, block: Dict, context: ParserContext) -> List[Token]:
        """
        블록을 분석하여 토큰 리스트 생성
        하나의 블록에 여러 구조가 있을 수 있음 (예: "제2조(정의)①이법에서...")
        """
        content = block.get('block_content', '').strip()
        if not content:
            return []
        
        tokens = []
        remaining = content
        current_pos = 0
        
        while remaining:
            token = cls._extract_next_token(remaining, content, current_pos, context, block)
            if token:
                tokens.append(token)
                
                # 토큰이 소비한 텍스트 길이 계산
                if token.pattern_type in (PatternType.STRUCTURE_조, PatternType.STRUCTURE_항):
                    # 조/항은 전체 remaining을 하나의 토큰으로
                    break
                elif token.pattern_type == PatternType.STRUCTURE_호:
                    # 호 패턴 뒤의 내용도 포함
                    break
                elif token.pattern_type == PatternType.STRUCTURE_목:
                    # 목 패턴 뒤의 내용도 포함
                    break
                else:
                    # CONTENT, CONTINUATION
                    break
            else:
                # 토큰 추출 실패 시 전체를 CONTENT로
                tokens.append(Token(
                    text=remaining,
                    pattern_type=PatternType.CONTENT,
                    source_block=block
                ))
                break
        
        return tokens
    
    @classmethod
    def _extract_next_token(cls, text: str, full_text: str, pos: int, 
                           context: ParserContext, block: Dict) -> Optional[Token]:
        """다음 토큰 추출"""
        
        # 0. 상위 구조 패턴 확인 (편 > 장 > 관 > 약관)
        
        # 편(編) 패턴
        pyeon_info = PatternRecognizer.extract_pyeon_pattern(text)
        if pyeon_info:
            pyeon_num, title, start, end = pyeon_info
            return Token(
                text=text,
                pattern_type=PatternType.STRUCTURE_편,
                structure_number=pyeon_num,
                source_block=block
            )
        
        # 장(章) 패턴
        jang_info = PatternRecognizer.extract_jang_pattern(text)
        if jang_info:
            jang_num, title, start, end = jang_info
            return Token(
                text=text,
                pattern_type=PatternType.STRUCTURE_장,
                structure_number=jang_num,
                source_block=block
            )
        
        # 관(款) 패턴
        gwan_info = PatternRecognizer.extract_gwan_pattern(text)
        if gwan_info:
            gwan_num, title, start, end = gwan_info
            return Token(
                text=text,
                pattern_type=PatternType.STRUCTURE_관,
                structure_number=gwan_num,
                source_block=block
            )
        
        # 약관 패턴 (특별약관, 보통약관, 추가약관 등)
        yakgwan_info = PatternRecognizer.extract_yakgwan_pattern(text)
        if yakgwan_info:
            yakgwan_name, start, end = yakgwan_info
            return Token(
                text=text,
                pattern_type=PatternType.STRUCTURE_약관,
                structure_number=yakgwan_name,
                source_block=block
            )
        
        # 법규 인용 패턴 [법규 1] 개인정보 보호법
        law_info = PatternRecognizer.extract_law_reference_pattern(text)
        if law_info:
            law_num, law_name, start, end = law_info
            return Token(
                text=text,
                pattern_type=PatternType.STRUCTURE_약관,  # 약관과 동일하게 처리
                structure_number=text.strip(),
                source_block=block
            )
        
        # 별표 패턴 [별표 1] 상해구분 및 보험금액
        byulpyo_info = PatternRecognizer.extract_byulpyo_pattern(text)
        if byulpyo_info:
            byulpyo_num, title, start, end = byulpyo_info
            return Token(
                text=text,
                pattern_type=PatternType.STRUCTURE_별표,
                structure_number=byulpyo_num,
                source_block=block
            )
        
        # 용어 정의 섹션
        if PatternRecognizer.is_terminology_section(text):
            return Token(
                text=text,
                pattern_type=PatternType.STRUCTURE_용어정의,
                structure_number=None,
                source_block=block
            )
        
        # 1. 조(條) 패턴 확인
        jo_info = PatternRecognizer.extract_jo_pattern(text)
        if jo_info and jo_info[1] == 0:  # 문장 시작에서 조 패턴
            jo_num, start, end = jo_info
            
            # 참조인지 구조인지 판별
            if not PatternRecognizer.is_reference_context(text, end):
                # 인용 법규 모드 (-1)이면 순차성 검증 안함
                if context.expected_jo == -1:
                    return cls._create_jo_token(text, jo_num, block, context)
                
                # 순차성 검증 완화: 새 섹션에서는 1조부터, 아니면 ±3 범위 허용
                is_new_section_start = (jo_num == 1)
                is_sequential = abs(jo_num - context.expected_jo) <= 3
                
                if is_new_section_start or is_sequential or context.expected_jo == 1:
                    return cls._create_jo_token(text, jo_num, block, context)
        
        # 2. 항(項) 패턴 확인
        hang_info = PatternRecognizer.extract_hang_pattern(text)
        if hang_info and hang_info[1] == 0:  # 문장 시작에서 항 패턴
            hang_num, start, end = hang_info
            
            # 순차성 검증
            if hang_num == context.expected_hang:
                return cls._create_hang_token(text, hang_num, block, context)
        
        # 3. 호(號) 패턴 확인
        ho_info = PatternRecognizer.extract_ho_pattern(text)
        if ho_info:
            ho_num, start, end = ho_info
            
            # 날짜 패턴 제외
            if not PatternRecognizer.is_date_pattern(full_text, pos + start):
                # 순차성 검증
                if ho_num == context.expected_ho:
                    return cls._create_ho_token(text, ho_num, block, context)
        
        # 4. 목(目) 패턴 확인
        mok_info = PatternRecognizer.extract_mok_pattern(text)
        if mok_info:
            mok_char, start, end = mok_info
            
            # 순차성 검증
            if mok_char == context.get_expected_mok():
                return cls._create_mok_token(text, mok_char, block, context)
        
        # 5. 일반 내용
        references = PatternRecognizer.extract_references(text)
        return Token(
            text=text,
            pattern_type=PatternType.CONTENT,
            references=references,
            source_block=block
        )
    
    @classmethod
    def _create_jo_token(cls, text: str, jo_num: int, block: Dict, 
                        context: ParserContext) -> Token:
        """조 토큰 생성"""
        references = PatternRecognizer.extract_references(text)
        return Token(
            text=text,
            pattern_type=PatternType.STRUCTURE_조,
            structure_number=jo_num,
            references=references,
            source_block=block
        )
    
    @classmethod
    def _create_hang_token(cls, text: str, hang_num: int, block: Dict,
                          context: ParserContext) -> Token:
        """항 토큰 생성"""
        references = PatternRecognizer.extract_references(text)
        return Token(
            text=text,
            pattern_type=PatternType.STRUCTURE_항,
            structure_number=hang_num,
            references=references,
            source_block=block
        )
    
    @classmethod
    def _create_ho_token(cls, text: str, ho_num: int, block: Dict,
                        context: ParserContext) -> Token:
        """호 토큰 생성"""
        references = PatternRecognizer.extract_references(text)
        return Token(
            text=text,
            pattern_type=PatternType.STRUCTURE_호,
            structure_number=ho_num,
            references=references,
            source_block=block
        )
    
    @classmethod
    def _create_mok_token(cls, text: str, mok_char: str, block: Dict,
                         context: ParserContext) -> Token:
        """목 토큰 생성"""
        references = PatternRecognizer.extract_references(text)
        return Token(
            text=text,
            pattern_type=PatternType.STRUCTURE_목,
            structure_number=mok_char,
            references=references,
            source_block=block
        )


# ============================================================================
# 5. 구조 빌더
# ============================================================================

class StructureBuilder:
    """토큰을 계층 구조로 변환"""
    
    def __init__(self):
        self.root = StructureNode(type="document")
        self.context = ParserContext()
        
        # 현재 활성 노드 스택 - 상위 구조 추가
        self.current_pyeon: Optional[StructureNode] = None
        self.current_jang: Optional[StructureNode] = None
        self.current_gwan: Optional[StructureNode] = None
        self.current_yakgwan: Optional[StructureNode] = None
        self.current_section: Optional[StructureNode] = None  # 현재 섹션 (관/장/약관 중 하나)
        
        self.current_jo: Optional[StructureNode] = None
        self.current_hang: Optional[StructureNode] = None
        self.current_ho: Optional[StructureNode] = None
        self.current_mok: Optional[StructureNode] = None
    
    def _get_current_parent_for_jo(self) -> StructureNode:
        """조의 부모 노드 반환 (관 > 장 > 약관 > 편 > root 순서)"""
        return self.current_section or self.root
    
    def process_token(self, token: Token):
        """토큰 처리"""
        if token.pattern_type == PatternType.STRUCTURE_편:
            self._handle_pyeon(token)
        elif token.pattern_type == PatternType.STRUCTURE_장:
            self._handle_jang(token)
        elif token.pattern_type == PatternType.STRUCTURE_관:
            self._handle_gwan(token)
        elif token.pattern_type == PatternType.STRUCTURE_약관:
            self._handle_yakgwan(token)
        elif token.pattern_type == PatternType.STRUCTURE_별표:
            self._handle_byulpyo(token)
        elif token.pattern_type == PatternType.STRUCTURE_용어정의:
            self._handle_terminology(token)
        elif token.pattern_type == PatternType.STRUCTURE_조:
            self._handle_jo(token)
        elif token.pattern_type == PatternType.STRUCTURE_항:
            self._handle_hang(token)
        elif token.pattern_type == PatternType.STRUCTURE_호:
            self._handle_ho(token)
        elif token.pattern_type == PatternType.STRUCTURE_목:
            self._handle_mok(token)
        elif token.pattern_type == PatternType.CONTENT:
            self._handle_content(token)
    
    def _handle_pyeon(self, token: Token):
        """편(編) 처리"""
        pyeon_num = token.structure_number
        text = token.text
        
        # 제목 추출
        match = re.match(r'^(제\d+편)\s*(.*)$', text.strip())
        title = match.group(1) + (' ' + match.group(2) if match.group(2) else '') if match else text
        
        pyeon_node = StructureNode(
            type="편",
            number=pyeon_num,
            title=title,
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        self.root.children.append(pyeon_node)
        self.current_pyeon = pyeon_node
        self.current_section = pyeon_node
        
        # 하위 구조 초기화
        self.current_jang = None
        self.current_gwan = None
        self.current_yakgwan = None
        self.current_jo = None
        self.context.reset_for_new_section()
    
    def _handle_jang(self, token: Token):
        """장(章) 처리"""
        jang_num = token.structure_number
        text = token.text
        
        match = re.match(r'^(제\d+장)\s*(.*)$', text.strip())
        title = match.group(1) + (' ' + match.group(2) if match.group(2) else '') if match else text
        
        jang_node = StructureNode(
            type="장",
            number=jang_num,
            title=title,
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        # 편이 있으면 편의 자식, 없으면 root의 자식
        parent = self.current_pyeon or self.root
        parent.children.append(jang_node)
        
        self.current_jang = jang_node
        self.current_section = jang_node
        
        # 하위 구조 초기화
        self.current_gwan = None
        self.current_yakgwan = None
        self.current_jo = None
        self.context.reset_for_new_section()
    
    def _handle_gwan(self, token: Token):
        """관(款) 처리"""
        gwan_num = token.structure_number
        text = token.text
        
        match = re.match(r'^(제\d+관)\s*(.*)$', text.strip())
        title = match.group(1) + (' ' + match.group(2) if match.group(2) else '') if match else text
        
        gwan_node = StructureNode(
            type="관",
            number=gwan_num,
            title=title,
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        # 약관 > 장 > 편 > root 순서로 부모 찾기
        parent = self.current_yakgwan or self.current_jang or self.current_pyeon or self.root
        parent.children.append(gwan_node)
        
        self.current_gwan = gwan_node
        self.current_section = gwan_node
        
        # 하위 구조 초기화 (조부터 새로 시작)
        self.current_jo = None
        self.context.reset_for_new_section()
    
    def _handle_yakgwan(self, token: Token):
        """약관 처리 (보통약관, 특별약관, 추가약관, 법규 인용)"""
        full_text = token.text
        yakgwan_name = token.structure_number if isinstance(token.structure_number, str) else token.text
        
        # [법규 X] 패턴 확인
        law_info = PatternRecognizer.extract_law_reference_pattern(yakgwan_name)
        if law_info:
            law_num, law_name, _, _ = law_info
            self._handle_law_reference(law_num, law_name, token)
            return
        
        # 약관명은 이미 structure_number에 정확하게 들어있음
        actual_yakgwan_name = yakgwan_name
        
        # 전체 텍스트에서 약관명 이후 부분 추출
        remaining_content = ''
        if len(full_text) > len(actual_yakgwan_name):
            remaining_content = full_text[len(actual_yakgwan_name):].strip()
        
        # 일반 약관 처리
        yakgwan_node = StructureNode(
            type="약관",
            number=None,
            title=actual_yakgwan_name,
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        # 약관은 항상 root의 자식 (보통약관, 특별약관, 추가약관 동일 레벨)
        parent = self.root
        parent.children.append(yakgwan_node)
        
        self.current_yakgwan = yakgwan_node
        self.current_section = yakgwan_node
        
        # 관, 조 초기화 (새 약관에서는 처음부터 시작)
        self.current_gwan = None
        self.current_jo = None
        self.context.reset_for_new_section()
        
        # 약관명 뒤에 남은 내용이 있으면 암묵적 content로 처리
        if remaining_content:
            # "본 추가약관은..." 같은 설명 문구는 약관의 content로
            yakgwan_node.content = remaining_content
    
    def _handle_byulpyo(self, token: Token):
        """별표 처리"""
        byulpyo_info = PatternRecognizer.extract_byulpyo_pattern(token.text)
        if byulpyo_info:
            byulpyo_num, title, _, _ = byulpyo_info
        else:
            byulpyo_num = token.structure_number
            title = ''
        
        byulpyo_node = StructureNode(
            type="별표",
            number=byulpyo_num,
            title=title if title else '',
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        # 별표는 root의 자식
        self.root.children.append(byulpyo_node)
        
        self.current_yakgwan = byulpyo_node
        self.current_section = byulpyo_node
        self.current_gwan = None
        self.current_jo = None
        # 별표 내에서는 조 순차성 검증 안함
        self.context.reset_for_new_section()
        self.context.expected_jo = -1
    
    def _handle_terminology(self, token: Token):
        """용어 정의 섹션 처리"""
        term_node = StructureNode(
            type="용어정의",
            number=None,
            title="용어의 정의",
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        # 현재 약관의 자식으로 추가
        parent = self.current_yakgwan or self.root
        parent.children.append(term_node)
        
        self.current_section = term_node
        self.current_jo = None
        self.context.reset_for_new_section()
    
    def _handle_yakgwan_or_law(self, token: Token):
        """약관 또는 인용 법규 처리"""
        text = token.structure_number if isinstance(token.structure_number, str) else token.text
        
        # [법규 X] 패턴 확인
        law_info = PatternRecognizer.extract_law_reference_pattern(text)
        if law_info:
            law_num, law_name, _, _ = law_info
            self._handle_law_reference(law_num, law_name, token)
            return
        
        # 일반 약관 처리
        yakgwan_node = StructureNode(
            type="약관",
            number=None,
            title=text,
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        parent = self.root
        parent.children.append(yakgwan_node)
        
        self.current_yakgwan = yakgwan_node
        self.current_section = yakgwan_node
        self.current_gwan = None
        self.current_jo = None
        self.context.reset_for_new_section()
    
    def _handle_law_reference(self, law_num: int, law_name: str, token: Token):
        """인용 법규 처리 - 조 번호가 순차적이지 않을 수 있음"""
        law_node = StructureNode(
            type="인용법규",
            number=law_num,
            title=law_name,  # 법규명만 (번호는 number 필드에)
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        # 인용법규는 root의 자식
        self.root.children.append(law_node)
        
        # 현재 섹션을 인용법규로 설정
        self.current_yakgwan = law_node
        self.current_section = law_node
        self.current_gwan = None
        self.current_jo = None
        
        # 인용 법규는 조 순차성 검증을 하지 않음
        self.context.reset_for_new_section()
        self.context.expected_jo = -1  # -1은 순차성 검증 비활성화 표시
    
    def _handle_jo(self, token: Token):
        """조(條) 처리"""
        jo_num = token.structure_number
        text = token.text
        
        # 조 제목 추출: "제X조(제목)" 또는 "제X조"
        title_match = re.match(r'^(제\d+조(?:\([^)]+\))?)', text)
        title = title_match.group(1) if title_match else f"제{jo_num}조"
        
        # 제목 이후 내용
        content_after_title = text[len(title):].strip() if title_match else text
        
        # 새 조 노드 생성
        jo_node = StructureNode(
            type="조",
            number=jo_num,
            title=title,
            references=token.references,
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        # 개정 정보 추출
        amendment = PatternRecognizer.extract_amendment_info(text)
        if amendment:
            jo_node.metadata = amendment
        
        # 상위 구조의 자식으로 추가 (약관 > 관 > 장 > 편 > root)
        parent = self._get_current_parent_for_jo()
        parent.children.append(jo_node)
        
        self.current_jo = jo_node
        self.current_hang = None
        self.current_ho = None
        self.current_mok = None
        
        # 컨텍스트 업데이트
        self.context.current_jo = jo_num
        self.context.expected_jo = jo_num + 1
        self.context.reset_hang()
        
        # 제목 이후 내용 처리
        if content_after_title:
            self._process_jo_content(content_after_title, token)
    
    def _process_jo_content(self, content: str, original_token: Token):
        """조 제목 이후 내용 처리 - 여러 항이 포함될 수 있음"""
        # 상위 구조 패턴 위치 찾기 (이 위치 이후는 별도 처리)
        upper_patterns = [
            r'(?<!본\s)(?:^|(?<=[\.\s]))([가-힣]{2,15}\s*){1,4}(?:추가|특별)약관(?![은는을를의에도과와이가])',  # XX 추가약관
            r'(?<!본\s)(?:^|(?<=[\.\s]))([가-힣]{2,15}\s*){1,4}보통약관(?![은는을를의에도과와이가])',  # XX 보통약관
            r'\[법규\s*\d+\]',
            r'【법규\s*\d+】',
            r'【법규\d+】',
            r'(?:^|(?<=[\.\s]))제\d+관\s+',
        ]
        
        upper_structure_pos = len(content)
        for pattern in upper_patterns:
            match = re.search(pattern, content)
            if match:
                if match.start() < upper_structure_pos:
                    upper_structure_pos = match.start()
        
        remaining_after_upper = None
        if upper_structure_pos < len(content):
            remaining_after_upper = content[upper_structure_pos:].strip()
            content = content[:upper_structure_pos].strip()
        
        # 모든 항 패턴(①②③...) 찾기
        hang_pattern = f'([{PatternRecognizer.CIRCLED_NUMBERS}])'
        matches = list(re.finditer(hang_pattern, content))
        
        if not matches:
            # ① 없음 → 암묵적 1항
            clean_content = re.sub(r'<\s*개정[^>]*>', '', content).strip()
            clean_content = re.sub(r'<\s*신설[^>]*>', '', clean_content).strip()
            if clean_content:
                self._create_implicit_hang(clean_content, original_token)
        else:
            # 첫 번째 ① 이전 내용이 있으면 처리
            first_match_start = matches[0].start()
            before_first_hang = content[:first_match_start].strip()
            
            # ① 이전에 실질적 내용이 있고, 첫 항이 ①이 아니면 암묵적 1항
            first_hang_num = PatternRecognizer.CIRCLED_NUMBERS.index(matches[0].group(1)) + 1
            if before_first_hang and first_hang_num != 1:
                self._create_implicit_hang(before_first_hang, original_token)
            
            # 각 항별로 분리하여 처리
            for i, match in enumerate(matches):
                hang_num = PatternRecognizer.CIRCLED_NUMBERS.index(match.group(1)) + 1
                start_pos = match.start()
                
                # 다음 항 패턴 전까지 또는 끝까지
                if i + 1 < len(matches):
                    end_pos = matches[i + 1].start()
                else:
                    end_pos = len(content)
                
                hang_content = content[start_pos:end_pos].strip()
                
                # 순차성 검증
                if hang_num == self.context.expected_hang:
                    self._create_explicit_hang(hang_content, hang_num, original_token)
                else:
                    # 순차성 실패 시 현재 항의 content에 추가
                    if self.current_hang:
                        self.current_hang.content += ' ' + hang_content
        
        # 상위 구조 패턴 이후 내용이 있으면 별도 처리
        if remaining_after_upper:
            remaining_token = Token(
                text=remaining_after_upper,
                pattern_type=PatternType.CONTENT,
                source_block=original_token.source_block
            )
            self._handle_content(remaining_token)
    
    def _create_implicit_hang(self, content: str, original_token: Token):
        """암묵적 1항 생성"""
        if not self.current_jo:
            return
        
        # 개정 정보 추출 및 제거
        amendment = PatternRecognizer.extract_amendment_info(content)
        clean_content = re.sub(r'<\s*개정[^>]*>', '', content).strip()
        
        hang_node = StructureNode(
            type="항",
            number=1,
            content=clean_content,
            implicit=True,
            references=PatternRecognizer.extract_references(clean_content),
            source_blocks=[str(original_token.source_block.get('block_id', ''))] if original_token.source_block else []
        )
        
        if amendment:
            hang_node.metadata = amendment
        
        self.current_jo.children.append(hang_node)
        self.current_hang = hang_node
        self.context.current_hang = 1
        self.context.expected_hang = 2
        self.context.reset_ho()
        
        # 호 패턴이 있으면 처리
        self._check_and_process_ho_in_content(clean_content, original_token)
    
    def _create_explicit_hang(self, content: str, hang_num: int, original_token: Token):
        """명시적 항 생성"""
        if not self.current_jo:
            return
        
        # 원문자 제거하고 내용 추출
        clean_content = re.sub(f'^[{PatternRecognizer.CIRCLED_NUMBERS}]\\s*', '', content).strip()
        
        # 개정 정보 추출 및 제거
        amendment = PatternRecognizer.extract_amendment_info(clean_content)
        clean_content = re.sub(r'<\s*개정[^>]*>', '', clean_content).strip()
        clean_content = re.sub(r'<\s*신설[^>]*>', '', clean_content).strip()
        
        # 상위 구조 패턴(약관/법규) 위치 찾기
        remaining_after_hang = None
        upper_patterns = [
            r'[^\s]+(?:추가|특별)약관(?:\([^)]*\))?',
            r'[^\s]+보통약관',
            r'\[법규\s*\d+\]',
            r'【법규\s*\d+】',
            r'【법규\d+】',
            r'제\d+관\s*',
        ]
        
        upper_pos = len(clean_content)
        for pattern in upper_patterns:
            match = re.search(pattern, clean_content)
            if match:
                # 문장 시작 또는 공백/마침표 뒤에 있어야 함
                if match.start() == 0 or clean_content[match.start()-1] in ' \n\t.。':
                    if match.start() < upper_pos:
                        upper_pos = match.start()
                        remaining_after_hang = clean_content[match.start():].strip()
        
        # 상위 구조 패턴 이전까지만 항 content로
        if remaining_after_hang:
            clean_content = clean_content[:upper_pos].strip()
        
        hang_node = StructureNode(
            type="항",
            number=hang_num,
            content=clean_content,
            references=PatternRecognizer.extract_references(clean_content),
            source_blocks=[str(original_token.source_block.get('block_id', ''))] if original_token.source_block else []
        )
        
        if amendment:
            hang_node.metadata = amendment
        
        self.current_jo.children.append(hang_node)
        self.current_hang = hang_node
        self.context.current_hang = hang_num
        self.context.expected_hang = hang_num + 1
        self.context.reset_ho()
        
        # 호 패턴이 있으면 처리
        self._check_and_process_ho_in_content(clean_content, original_token)
        
        # 상위 구조 패턴 이후 내용이 있으면 별도 처리
        if remaining_after_hang:
            remaining_token = Token(
                text=remaining_after_hang,
                pattern_type=PatternType.CONTENT,
                source_block=original_token.source_block
            )
            self._handle_content(remaining_token)
    
    def _handle_hang(self, token: Token):
        """항(項) 처리"""
        if not self.current_jo:
            return
        
        hang_num = token.structure_number
        content = token.text
        
        # 원문자 제거
        clean_content = re.sub(f'^[{PatternRecognizer.CIRCLED_NUMBERS}]\\s*', '', content).strip()
        
        # 개정 정보 추출 및 제거
        amendment = PatternRecognizer.extract_amendment_info(clean_content)
        clean_content = re.sub(r'<\s*개정[^>]*>', '', clean_content).strip()
        
        hang_node = StructureNode(
            type="항",
            number=hang_num,
            content=clean_content,
            references=token.references,
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        if amendment:
            hang_node.metadata = amendment
        
        self.current_jo.children.append(hang_node)
        self.current_hang = hang_node
        self.current_ho = None
        self.current_mok = None
        
        self.context.current_hang = hang_num
        self.context.expected_hang = hang_num + 1
        self.context.reset_ho()
        
        # 호 패턴이 있으면 처리
        self._check_and_process_ho_in_content(clean_content, token)
    
    def _handle_ho(self, token: Token):
        """호(號) 처리 - 내용 안에 항 패턴이 있을 수 있음"""
        if not self.current_hang:
            return
        
        ho_num = token.structure_number
        content = token.text
        
        # 호 패턴 제거
        clean_content = re.sub(r'^\d+\.\s*', '', content).strip()
        
        # 호 content 안에 항 패턴(②③④...)이 있는지 확인
        hang_pattern = f'([{PatternRecognizer.CIRCLED_NUMBERS}])'
        matches = list(re.finditer(hang_pattern, clean_content))
        
        if matches:
            # 첫 번째 항 패턴 이전까지가 호의 실제 content
            first_match_start = matches[0].start()
            ho_actual_content = clean_content[:first_match_start].strip()
            
            # 호 노드 생성
            ho_node = StructureNode(
                type="호",
                number=ho_num,
                content=ho_actual_content,
                references=PatternRecognizer.extract_references(ho_actual_content),
                source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
            )
            
            self.current_hang.children.append(ho_node)
            self.current_ho = ho_node
            self.current_mok = None
            
            self.context.current_ho = ho_num
            self.context.expected_ho = ho_num + 1
            self.context.reset_mok()
            
            # 항 패턴 이후 내용을 별도 처리 (항으로 분리)
            remaining_content = clean_content[first_match_start:].strip()
            if remaining_content:
                self._process_remaining_hangs(remaining_content, token)
        else:
            # 항 패턴 없음 - 기존 로직
            ho_node = StructureNode(
                type="호",
                number=ho_num,
                content=clean_content,
                references=token.references,
                source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
            )
            
            self.current_hang.children.append(ho_node)
            self.current_ho = ho_node
            self.current_mok = None
            
            self.context.current_ho = ho_num
            self.context.expected_ho = ho_num + 1
            self.context.reset_mok()
            
            # 목 패턴이 있으면 처리
            self._check_and_process_mok_in_content(clean_content, token)
    
    def _process_remaining_hangs(self, content: str, original_token: Token):
        """
        남은 content에서 항들을 분리하여 처리
        (호 content 안에 ④⑤⑥⑦ 등이 있는 경우)
        """
        hang_pattern = f'([{PatternRecognizer.CIRCLED_NUMBERS}])'
        matches = list(re.finditer(hang_pattern, content))
        
        for i, match in enumerate(matches):
            hang_num = PatternRecognizer.CIRCLED_NUMBERS.index(match.group(1)) + 1
            start_pos = match.start()
            
            # 다음 항 패턴 전까지 또는 끝까지
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                end_pos = len(content)
            
            hang_content = content[start_pos:end_pos].strip()
            
            # 순차성 검증
            if hang_num == self.context.expected_hang:
                self._create_explicit_hang(hang_content, hang_num, original_token)
            # 순차성 실패 시 현재 노드에 추가하지 않고 무시 (이미 이전 항에 귀속됨)
    
    def _handle_mok(self, token: Token):
        """목(目) 처리"""
        if not self.current_ho:
            return
        
        mok_char = token.structure_number
        content = token.text
        
        # 목 패턴 제거
        clean_content = re.sub(r'^[가나다라마바사아자차카타파하]\.\s*', '', content).strip()
        
        mok_node = StructureNode(
            type="목",
            number=mok_char,
            content=clean_content,
            references=token.references,
            source_blocks=[str(token.source_block.get('block_id', ''))] if token.source_block else []
        )
        
        self.current_ho.children.append(mok_node)
        self.current_mok = mok_node
        
        self.context.current_mok = mok_char
        self.context.expected_mok_idx += 1
    
    def _handle_content(self, token: Token):
        """일반 내용 처리 - 여러 항이 포함될 수 있음, 상위 구조도 체크"""
        content = token.text
        
        # 0. content 안에 상위 구조 패턴(편/장/관/약관/법규)이 있는지 확인
        split_result = self._split_content_by_structure(content, token)
        if split_result:
            return  # 분리 처리됨
        
        # 현재 조가 있고, content 안에 ②③ 등의 항 패턴이 있는지 확인
        if self.current_jo:
            hang_pattern = f'([{PatternRecognizer.CIRCLED_NUMBERS}])'
            matches = list(re.finditer(hang_pattern, content))
            
            if matches:
                # 첫 번째 항 패턴 이전 내용을 현재 노드에 추가
                first_match_start = matches[0].start()
                before_content = content[:first_match_start].strip()
                
                if before_content:
                    self._append_to_current_node(before_content, token)
                
                # 각 항별로 분리하여 처리
                for i, match in enumerate(matches):
                    hang_num = PatternRecognizer.CIRCLED_NUMBERS.index(match.group(1)) + 1
                    start_pos = match.start()
                    
                    # 다음 항 패턴 전까지 또는 끝까지
                    if i + 1 < len(matches):
                        end_pos = matches[i + 1].start()
                    else:
                        end_pos = len(content)
                    
                    hang_content = content[start_pos:end_pos].strip()
                    
                    # 순차성 검증
                    if hang_num == self.context.expected_hang:
                        self._create_explicit_hang(hang_content, hang_num, token)
                    else:
                        # 순차성 실패 시 현재 노드에 추가
                        self._append_to_current_node(hang_content, token)
                
                return
        
        # 항 패턴이 없으면 기존 로직대로 처리
        self._append_to_current_node(content, token)
    
    def _split_content_by_structure(self, content: str, token: Token) -> bool:
        """
        content 안에서 상위 구조 패턴(관/장/편/약관/법규)을 찾아 분리
        Returns: 분리 처리했으면 True
        """
        # 상위 구조 패턴들 (순서 중요: 더 구체적인 것 먼저)
        structure_patterns = [
            (r'(제\d+편\s*[^\n]*)', 'pyeon'),
            (r'(제\d+장\s*[^\n]*)', 'jang'),
            (r'(제\d+관\s*[^\n]*)', 'gwan'),
            # 법규 패턴 (여러 형태) - 법규명만 추출
            (r'(\[법규\s*\d+\]\s*[가-힣\s]+법)', 'law'),
            (r'(【법규\s*\d+】\s*[가-힣\s]+법)', 'law'),
            (r'(【법규\d+】\s*[가-힣\s]+법)', 'law'),
            # 약관 패턴: 한글단어 + 추가/특별약관
            # 뒤에 조사가 오면 제외, 앞에 "본"이 오면 제외
            (r'([가-힣]+(?:\s+[가-힣]+)*\s*(?:추가|특별)약관)(?![은는을를의에도과와이가])', 'yakgwan'),
            (r'([가-힣]+(?:\s+[가-힣]+)*\s*보통약관)(?![은는을를의에도과와이가])', 'yakgwan'),
        ]
        
        # 가장 먼저 나오는 구조 패턴 찾기
        first_match = None
        first_pos = len(content)
        first_kind = None
        
        for pattern, kind in structure_patterns:
            match = re.search(pattern, content)
            if match and match.start() < first_pos:
                # 문장 시작 또는 공백/문장부호 뒤에 있어야 함 (단어 중간 아님)
                if match.start() == 0 or content[match.start()-1] in ' \n\t.。,':
                    # 약관 패턴인 경우, "본 약관" 형태면 제외
                    if kind == 'yakgwan':
                        matched_text = match.group(1) if match.lastindex else match.group(0)
                        # "본 추가약관", "본 특별약관" 형태면 제외
                        if matched_text.startswith('본 ') or matched_text.startswith('본'):
                            continue
                        # 앞에 "본 "이 있는지 확인
                        if match.start() > 0:
                            before_text = content[max(0, match.start()-3):match.start()]
                            if '본 ' in before_text or before_text.strip() == '본':
                                continue
                    first_match = match
                    first_pos = match.start()
                    first_kind = kind
        
        if not first_match:
            return False
        
        # 구조 패턴 이전 내용 처리
        before_content = content[:first_pos].strip()
        if before_content:
            self._append_to_current_node(before_content, token)
        
        # 구조 패턴 처리
        structure_text = first_match.group(1).strip()
        after_content = content[first_match.end():].strip()
        
        # 토큰 생성 및 처리
        if first_kind == 'pyeon':
            pyeon_info = PatternRecognizer.extract_pyeon_pattern(structure_text)
            if pyeon_info:
                new_token = Token(
                    text=structure_text,
                    pattern_type=PatternType.STRUCTURE_편,
                    structure_number=pyeon_info[0],
                    source_block=token.source_block
                )
                self._handle_pyeon(new_token)
        elif first_kind == 'jang':
            jang_info = PatternRecognizer.extract_jang_pattern(structure_text)
            if jang_info:
                new_token = Token(
                    text=structure_text,
                    pattern_type=PatternType.STRUCTURE_장,
                    structure_number=jang_info[0],
                    source_block=token.source_block
                )
                self._handle_jang(new_token)
        elif first_kind == 'gwan':
            gwan_info = PatternRecognizer.extract_gwan_pattern(structure_text)
            if gwan_info:
                new_token = Token(
                    text=structure_text,
                    pattern_type=PatternType.STRUCTURE_관,
                    structure_number=gwan_info[0],
                    source_block=token.source_block
                )
                self._handle_gwan(new_token)
        elif first_kind in ('yakgwan', 'law'):
            new_token = Token(
                text=structure_text,
                pattern_type=PatternType.STRUCTURE_약관,
                structure_number=structure_text,
                source_block=token.source_block
            )
            self._handle_yakgwan(new_token)
        
        # 나머지 내용 재귀 처리
        if after_content:
            remaining_token = Token(
                text=after_content,
                pattern_type=PatternType.CONTENT,
                source_block=token.source_block
            )
            self._handle_content(remaining_token)
        
        return True
    
    def _append_to_current_node(self, content: str, token: Token):
        """현재 활성 노드에 내용 추가"""
        # 가장 하위 활성 노드에 추가
        target_node = (
            self.current_mok or
            self.current_ho or
            self.current_hang or
            self.current_jo or
            self.root
        )
        
        # 기존 content에 추가
        if target_node.content:
            target_node.content += ' ' + content
        else:
            target_node.content = content
        
        # 참조 추가
        refs = PatternRecognizer.extract_references(content)
        if refs:
            target_node.references.extend(refs)
        
        # 소스 블록 추가
        if token.source_block:
            block_id = str(token.source_block.get('block_id', ''))
            if block_id and block_id not in target_node.source_blocks:
                target_node.source_blocks.append(block_id)
    
    def _check_and_process_ho_in_content(self, content: str, original_token: Token):
        """내용에서 호 패턴 확인 및 처리"""
        # 1. 2. 3. 패턴 찾기
        ho_pattern = r'(\d+)\.\s+'
        matches = list(re.finditer(ho_pattern, content))
        
        if not matches:
            return
        
        # 첫 번째 호가 1인지 확인 (순차성)
        first_match = matches[0]
        first_ho_num = int(first_match.group(1))
        
        if first_ho_num != 1:
            return  # 1부터 시작하지 않으면 호 패턴 아님
        
        # 날짜 패턴 필터링
        valid_matches = []
        for match in matches:
            if not PatternRecognizer.is_date_pattern(content, match.start()):
                valid_matches.append(match)
        
        if not valid_matches:
            return
        
        # 순차성 검증
        expected = 1
        sequential_matches = []
        for match in valid_matches:
            ho_num = int(match.group(1))
            if ho_num == expected:
                sequential_matches.append(match)
                expected += 1
            elif ho_num > expected:
                break  # 순차성 깨짐
        
        if len(sequential_matches) < 2:
            # 호가 1개만 있어도 그 안에 목 패턴이 있으면 처리
            if len(sequential_matches) == 1:
                match = sequential_matches[0]
                ho_num = int(match.group(1))
                start_pos = match.start()
                ho_content = content[start_pos:].strip()
                clean_ho_content = re.sub(r'^\d+\.\s*', '', ho_content).strip()
                
                # 목 패턴이 있는지 확인
                mok_pattern = r'(?:^|[\s,])([가나다라마바사아자차카타파하])\.\s*'
                mok_matches = list(re.finditer(mok_pattern, clean_ho_content))
                if mok_matches and len(mok_matches) >= 2:
                    # 목이 2개 이상 있으면 호 생성
                    if self.current_hang:
                        self.current_hang.content = content[:start_pos].strip()
                    
                    ho_node = StructureNode(
                        type="호",
                        number=ho_num,
                        content=clean_ho_content,
                        references=PatternRecognizer.extract_references(clean_ho_content),
                        source_blocks=[str(original_token.source_block.get('block_id', ''))] if original_token.source_block else []
                    )
                    
                    if self.current_hang:
                        self.current_hang.children.append(ho_node)
                    
                    self.current_ho = ho_node
                    self.context.current_ho = ho_num
                    self.context.expected_ho = ho_num + 1
                    
                    # 목 처리
                    self._check_and_process_mok_in_content(clean_ho_content, original_token)
            return  # 호가 1개만 있고 목도 없으면 호 구조 아님
        
        # 호 분리 및 생성
        # 현재 항의 content에서 호 이전 부분만 남기기
        first_ho_start = sequential_matches[0].start()
        if self.current_hang:
            self.current_hang.content = content[:first_ho_start].strip()
        
        # 각 호 노드 생성
        for i, match in enumerate(sequential_matches):
            ho_num = int(match.group(1))
            start_pos = match.start()
            
            # 다음 호 전까지 또는 끝까지
            if i + 1 < len(sequential_matches):
                end_pos = sequential_matches[i + 1].start()
            else:
                end_pos = len(content)
            
            ho_content = content[start_pos:end_pos].strip()
            
            # 호 패턴 제거
            clean_ho_content = re.sub(r'^\d+\.\s*', '', ho_content).strip()
            
            ho_node = StructureNode(
                type="호",
                number=ho_num,
                content=clean_ho_content,
                references=PatternRecognizer.extract_references(clean_ho_content),
                source_blocks=[str(original_token.source_block.get('block_id', ''))] if original_token.source_block else []
            )
            
            if self.current_hang:
                self.current_hang.children.append(ho_node)
            
            self.current_ho = ho_node
            self.context.current_ho = ho_num
            self.context.expected_ho = ho_num + 1
            
            # 호 content 안에 목 패턴이 있으면 처리
            self._check_and_process_mok_in_content(clean_ho_content, original_token)
    
    def _check_and_process_mok_in_content(self, content: str, original_token: Token):
        """내용에서 목 패턴 확인 및 처리"""
        # 목 패턴: 문장 시작 또는 공백 뒤에 "가.", "나." 등이 오는 경우
        # "가격", "나중에" 등 단어 중간의 "가", "나"는 제외
        mok_pattern = r'(?:^|[\s,])([가나다라마바사아자차카타파하])\.\s*'
        matches = list(re.finditer(mok_pattern, content))
        
        if not matches:
            return
        
        # 첫 번째 목이 '가'인지 확인
        first_match = matches[0]
        first_mok = first_match.group(1)
        
        if first_mok != '가':
            return
        
        # 순차성 검증
        mok_order = ['가', '나', '다', '라', '마', '바', '사', '아', '자', '차', '카', '타', '파', '하']
        expected_idx = 0
        sequential_matches = []
        
        for match in matches:
            mok_char = match.group(1)
            if expected_idx < len(mok_order) and mok_char == mok_order[expected_idx]:
                sequential_matches.append(match)
                expected_idx += 1
        
        if len(sequential_matches) < 2:
            return
        
        # 상위 구조 패턴 위치 찾기 (제X관, 제X장 등)
        upper_structure_pattern = r'제\d+(?:편|장|관)'
        upper_match = re.search(upper_structure_pattern, content)
        upper_structure_pos = upper_match.start() if upper_match else len(content)
        
        # 목 분리 및 생성
        first_mok_match = sequential_matches[0]
        first_mok_content_start = first_mok_match.start()
        if content[first_mok_content_start] in ' \t,':
            first_mok_content_start += 1
        
        if self.current_ho:
            self.current_ho.content = content[:first_mok_content_start].strip()
        
        remaining_after_mok = None
        
        for i, match in enumerate(sequential_matches):
            mok_char = match.group(1)
            start_pos = match.start()
            if content[start_pos] in ' \t,':
                start_pos += 1
            
            if i + 1 < len(sequential_matches):
                next_match = sequential_matches[i + 1]
                end_pos = next_match.start()
                if content[end_pos] in ' \t,':
                    end_pos = end_pos
            else:
                # 마지막 목: 상위 구조 패턴이 있으면 그 전까지만
                end_pos = min(upper_structure_pos, len(content))
                if upper_structure_pos < len(content):
                    remaining_after_mok = content[upper_structure_pos:].strip()
            
            mok_content = content[start_pos:end_pos].strip()
            clean_mok_content = re.sub(r'^[가나다라마바사아자차카타파하]\.\s*', '', mok_content).strip()
            
            mok_node = StructureNode(
                type="목",
                number=mok_char,
                content=clean_mok_content,
                references=PatternRecognizer.extract_references(clean_mok_content),
                source_blocks=[str(original_token.source_block.get('block_id', ''))] if original_token.source_block else []
            )
            
            if self.current_ho:
                self.current_ho.children.append(mok_node)
            
            self.current_mok = mok_node
        
        # 상위 구조 패턴 이후 내용이 있으면 별도 처리
        if remaining_after_mok:
            remaining_token = Token(
                text=remaining_after_mok,
                pattern_type=PatternType.CONTENT,
                source_block=original_token.source_block
            )
            self._handle_content(remaining_token)
    
    def build(self) -> Dict:
        """최종 구조 반환"""
        return self.root.to_dict()


# ============================================================================
# 6. 메인 파서
# ============================================================================

class HybridLegalParser:
    """하이브리드 법령 파서"""
    
    def __init__(self):
        self.preprocessor = BlockPreprocessor()
        self.tokenizer = Tokenizer()
    
    def parse(self, blocks: List[Dict]) -> Dict:
        """
        블록 리스트를 계층 구조로 파싱
        
        Args:
            blocks: 블록 리스트 (각 블록은 block_content, block_label 등 포함)
            
        Returns:
            계층 구조 딕셔너리
        """
        # 1. 블록 전처리 (연속 블록 병합)
        merged_blocks = self.preprocessor.merge_blocks(blocks)
        
        # 2. 구조 빌더 초기화
        builder = StructureBuilder()
        
        # 3. 각 블록 처리
        for block in merged_blocks:
            # 토큰화
            tokens = self.tokenizer.tokenize(block, builder.context)
            
            # 각 토큰 처리
            for token in tokens:
                builder.process_token(token)
        
        # 4. 최종 구조 반환
        return builder.build()
    
    def parse_from_json_files(self, parsing_results_dir: Path) -> Dict:
        """
        parsing_results 폴더의 JSON 파일들을 읽어 파싱
        """
        blocks = self._load_blocks_from_dir(parsing_results_dir)
        return self.parse(blocks)
    
    def _load_blocks_from_dir(self, parsing_results_dir: Path) -> List[Dict]:
        """JSON 파일들에서 블록 로드"""
        if not parsing_results_dir.exists():
            raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {parsing_results_dir}")
        
        all_blocks = []
        
        # 페이지 순서대로 정렬
        json_files = sorted(
            parsing_results_dir.glob("page_*.json"),
            key=lambda x: int(re.search(r'page_(\d+)', x.name).group(1)) 
                if re.search(r'page_(\d+)', x.name) else 0
        )
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if 'parsing_res_list' in data:
                    for block in data['parsing_res_list']:
                        # number 블록 제외
                        if block.get('block_label') != 'number':
                            all_blocks.append(block)
            except Exception as e:
                print(f"파일 읽기 오류 ({json_file}): {e}")
        
        return all_blocks


# ============================================================================
# 7. 유틸리티 함수
# ============================================================================

def print_structure(node: Dict, indent: int = 0):
    """구조 출력 (디버깅용)"""
    prefix = "  " * indent
    node_type = node.get('type', 'unknown')
    number = node.get('number', '')
    title = node.get('title', '')
    content = node.get('content', '')[:50] + '...' if len(node.get('content', '')) > 50 else node.get('content', '')
    implicit = ' (암묵적)' if node.get('implicit') else ''
    
    if node_type == 'document':
        print(f"{prefix}[문서]")
    elif node_type == '편':
        print(f"{prefix}[편 {number}] {title}")
    elif node_type == '장':
        print(f"{prefix}[장 {number}] {title}")
    elif node_type == '관':
        print(f"{prefix}[관 {number}] {title}")
    elif node_type == '약관':
        if content:
            print(f"{prefix}[약관] {title} | {content}")
        else:
            print(f"{prefix}[약관] {title}")
    elif node_type == '인용법규':
        print(f"{prefix}[법규 {number}] {title}")
    elif node_type == '별표':
        print(f"{prefix}[별표 {number}] {title}")
    elif node_type == '용어정의':
        print(f"{prefix}[용어정의] {title}")
    elif node_type == '조':
        print(f"{prefix}[조 {number}] {title}")
    elif node_type == '항':
        print(f"{prefix}[항 {number}]{implicit} {content}")
    elif node_type == '호':
        print(f"{prefix}[호 {number}] {content}")
    elif node_type == '목':
        print(f"{prefix}[목 {number}] {content}")
    
    for child in node.get('children', []):
        print_structure(child, indent + 1)


def count_statistics(node: Dict, stats: Dict = None) -> Dict:
    """통계 계산"""
    if stats is None:
        stats = defaultdict(int)
    
    node_type = node.get('type', 'unknown')
    stats[node_type] += 1
    
    if node.get('implicit'):
        stats['암묵적_항'] += 1
    
    if node.get('references'):
        stats['참조_포함_노드'] += 1
        stats['총_참조_수'] += len(node.get('references', []))
    
    for child in node.get('children', []):
        count_statistics(child, stats)
    
    return stats


# ============================================================================
# 8. 메인 함수
# ============================================================================

def main():
    """메인 실행"""
    import sys
    
    # 입력 경로 설정
    if len(sys.argv) > 1:
        input_path = Path(sys.argv[1])
    else:
        input_path = Path("output/work/layout_parsing_output/parsing_results")
    
    # 출력 경로 설정
    if len(sys.argv) > 2:
        output_path = Path(sys.argv[2])
    else:
        output_path = Path("output/hierarchical_structure.json")
    
    print(f"입력 경로: {input_path}")
    print(f"출력 경로: {output_path}")
    
    # 파서 실행
    parser = HybridLegalParser()
    
    try:
        result = parser.parse_from_json_files(input_path)
        
        # 결과 저장
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n완료! 결과 파일: {output_path}")
        
        # 통계 출력
        stats = count_statistics(result)
        print("\n=== 통계 ===")
        for key, value in sorted(stats.items()):
            print(f"  {key}: {value}")
        
        # 구조 미리보기
        print("\n=== 구조 미리보기 ===")
        print_structure(result)
        
    except FileNotFoundError as e:
        print(f"오류: {e}")
        sys.exit(1)


def run_local_test():
    """
    로컬 테스트 실행
    Windows 경로: C:/Users/bigda/Desktop/graph_rag/output/work/layout_parsing_output/parsing_results
    """
    # Windows 경로 설정
    input_path = Path(r"C:\Users\bigda\Desktop\graph_rag\output\work\layout_parsing_output\parsing_results")
    output_path = Path(r"C:\Users\bigda\Desktop\graph_rag\output\hierarchical_structure.json")
    
    print("=" * 60)
    print("하이브리드 법령 파서 - 로컬 테스트")
    print("=" * 60)
    print(f"\n입력 경로: {input_path}")
    print(f"출력 경로: {output_path}")
    
    # 경로 존재 확인
    if not input_path.exists():
        print(f"\n오류: 입력 경로가 존재하지 않습니다: {input_path}")
        return
    
    # JSON 파일 개수 확인
    json_files = list(input_path.glob("page_*.json"))
    print(f"\n발견된 JSON 파일: {len(json_files)}개")
    
    if not json_files:
        print("오류: JSON 파일을 찾을 수 없습니다.")
        return
    
    # 처음 몇 개 파일명 출력
    print("파일 목록 (처음 5개):")
    for f in sorted(json_files)[:5]:
        print(f"  - {f.name}")
    if len(json_files) > 5:
        print(f"  ... 외 {len(json_files) - 5}개")
    
    # 파서 실행
    print("\n파싱 시작...")
    parser = HybridLegalParser()
    
    try:
        result = parser.parse_from_json_files(input_path)
        
        # 결과 저장
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n완료! 결과 파일: {output_path}")
        
        # 통계 출력
        stats = count_statistics(result)
        print("\n" + "=" * 60)
        print("통계")
        print("=" * 60)
        for key, value in sorted(stats.items()):
            print(f"  {key}: {value}")
        
        # 구조 미리보기 (처음 20줄만)
        print("\n" + "=" * 60)
        print("구조 미리보기 (상위 레벨)")
        print("=" * 60)
        
        # 조 레벨만 출력
        for child in result.get('children', [])[:20]:
            if child.get('type') == '조':
                jo_num = child.get('number')
                jo_title = child.get('title', '')
                hang_count = len(child.get('children', []))
                print(f"  [조 {jo_num}] {jo_title} - 항 {hang_count}개")
        
        total_jo = len([c for c in result.get('children', []) if c.get('type') == '조'])
        if total_jo > 20:
            print(f"  ... 외 {total_jo - 20}개 조")
        
        print("\n" + "=" * 60)
        print("테스트 완료")
        print("=" * 60)
        
        return result
        
    except Exception as e:
        print(f"\n오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    import sys
    
    # 인자가 없으면 로컬 테스트 실행
    if len(sys.argv) == 1:
        # 로컬 테스트 모드
        run_local_test()
    else:
        # 명령줄 인자 모드
        main()