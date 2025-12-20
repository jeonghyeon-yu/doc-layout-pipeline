"""
보험약관/법률 계층 구조 파싱 시스템 v4

주요 기능:
1. 보험약관 및 법률 문서 계층 파싱
2. 참조(reference) 자동 추출 및 연결
3. 장의2, 조의2 등 가지 조항 지원
4. 트리 구조 저장 및 탐색

계층 구조:
- 보험약관: 약관 → 관 → 조 → 항 → 호 → 목 → 세목 → 대시
- 법률: 법률 → 편 → 장 → 절 → 관 → 조 → 항 → 호 → 목 → 세목
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Any
from collections import defaultdict
from dataclasses import dataclass, field


# =============================================================================
# 상수 정의
# =============================================================================

# 원문자 (항)
CIRCLED_NUMBERS = {
    '①':1, '②':2, '③':3, '④':4, '⑤':5,
    '⑥':6, '⑦':7, '⑧':8, '⑨':9, '⑩':10,
    '⑪':11, '⑫':12, '⑬':13, '⑭':14, '⑮':15,
    '⑯':16, '⑰':17, '⑱':18, '⑲':19, '⑳':20
}

# 로마숫자 (세목)
ROMAN_NUMERALS = {
    'ⅰ':1, 'ⅱ':2, 'ⅲ':3, 'ⅳ':4, 'ⅴ':5,
    'ⅵ':6, 'ⅶ':7, 'ⅷ':8, 'ⅸ':9, 'ⅹ':10,
    'i':1, 'ii':2, 'iii':3, 'iv':4, 'v':5,
    'vi':6, 'vii':7, 'viii':8, 'ix':9, 'x':10
}

# 한글 (목)
MOK_CHARS = "가나다라마바사아자차카타파하"

# 계층 레벨 정의
LEVEL_SECTION = 0   # 약관 / 법률
LEVEL_PYEON = 1     # 편 (법률)
LEVEL_JANG = 2      # 장 (법률)
LEVEL_JEOL = 3      # 절 (법률)
LEVEL_GWAN = 4      # 관
LEVEL_JO = 5        # 조
LEVEL_HANG = 6      # 항
LEVEL_HO = 7        # 호
LEVEL_MOK = 8       # 목
LEVEL_SEMOK = 9     # 세목
LEVEL_DASH = 10     # 대시

# 문서 타입
DOC_TYPE_INSURANCE = 'insurance'
DOC_TYPE_LAW = 'law'


# =============================================================================
# 참조(Reference) 데이터 클래스
# =============================================================================

@dataclass
class Reference:
    """참조 정보"""
    ref_type: str           # 'internal' (동일 문서) / 'external' (외부 법률)
    source_id: str          # 참조하는 노드 ID
    target_law: Optional[str] = None   # 외부 법률명 (예: "민법", "상법")
    target_jo: Optional[int] = None    # 참조 조 번호
    target_jo_branch: Optional[int] = None  # 조의N (가지 조항)
    target_hang: Optional[int] = None  # 참조 항 번호
    target_ho: Optional[int] = None    # 참조 호 번호
    target_mok: Optional[str] = None   # 참조 목 (가, 나, 다)
    raw_text: str = ""      # 원본 참조 텍스트
    resolved_id: Optional[str] = None  # 해석된 대상 ID
    
    def to_dict(self) -> Dict:
        return {
            'ref_type': self.ref_type,
            'source_id': self.source_id,
            'target_law': self.target_law,
            'target_jo': self.target_jo,
            'target_jo_branch': self.target_jo_branch,
            'target_hang': self.target_hang,
            'target_ho': self.target_ho,
            'target_mok': self.target_mok,
            'raw_text': self.raw_text,
            'resolved_id': self.resolved_id
        }


# =============================================================================
# 계층 노드 데이터 클래스
# =============================================================================

@dataclass
class HierarchyNode:
    """계층 구조 노드"""
    id: str
    type: str
    level: int
    number: Optional[int] = None
    branch: Optional[int] = None       # 가지 번호 (제N조의2 → branch=2)
    marker: str = ""
    title: str = ""
    content: str = ""
    page: int = 0
    children: List['HierarchyNode'] = field(default_factory=list)
    references: List[Reference] = field(default_factory=list)  # 참조 목록
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'type': self.type,
            'level': self.level,
            'number': self.number,
            'branch': self.branch,
            'marker': self.marker,
            'title': self.title,
            'content': self.content,
            'page': self.page,
            'children': [c.to_dict() for c in self.children],
            'references': [r.to_dict() for r in self.references],
            'metadata': self.metadata
        }
    
    def find(self, path: str) -> Optional['HierarchyNode']:
        """경로로 노드 찾기"""
        parts = path.split(".")
        current = self
        
        for part in parts:
            found = None
            for child in current.children:
                if self._match_node(child, part):
                    found = child
                    break
            if found:
                current = found
            else:
                return None
        return current
    
    def _match_node(self, node: 'HierarchyNode', query: str) -> bool:
        # 제N편
        m = re.match(r'제(\d+)편', query)
        if m:
            return node.type == '편' and node.number == int(m.group(1))
        
        # 제N장 또는 제N장의M
        m = re.match(r'제(\d+)장(?:의(\d+))?', query)
        if m:
            if node.type == '장' and node.number == int(m.group(1)):
                if m.group(2):
                    return node.branch == int(m.group(2))
                return node.branch is None
            return False
        
        # 제N절
        m = re.match(r'제(\d+)절', query)
        if m:
            return node.type == '절' and node.number == int(m.group(1))
        
        # 제N조 또는 제N조의M
        m = re.match(r'제(\d+)조(?:의(\d+))?', query)
        if m:
            if node.type == '조' and node.number == int(m.group(1)):
                if m.group(2):
                    return node.branch == int(m.group(2))
                return node.branch is None
            return False
        
        # 제N관
        m = re.match(r'제(\d+)관', query)
        if m:
            return node.type == '관' and node.number == int(m.group(1))
        
        # 원문자 항
        if query in CIRCLED_NUMBERS:
            return node.type == '항' and node.number == CIRCLED_NUMBERS[query]
        
        # 숫자 호
        if query.isdigit():
            return node.type == '호' and node.number == int(query)
        
        # 한글 목
        if query in MOK_CHARS:
            return node.type == '목' and node.number == MOK_CHARS.index(query) + 1
        
        # 로마숫자 세목
        query_lower = query.strip('()').lower()
        if query_lower in ROMAN_NUMERALS:
            return node.type == '세목' and node.number == ROMAN_NUMERALS[query_lower]
        
        return False
    
    def print_tree(self, indent: int = 0, max_depth: int = 99) -> None:
        if indent > max_depth:
            return
        
        prefix = "│   " * indent
        marker_str = f"[{self.marker}]" if self.marker else f"[{self.type}]"
        title_short = self.title[:35] + "..." if len(self.title) > 35 else self.title
        ref_count = f" (refs:{len(self.references)})" if self.references else ""
        
        print(f"{prefix}├── {marker_str} {title_short}{ref_count}")
        
        for child in self.children:
            child.print_tree(indent + 1, max_depth)
    
    def get_all_by_type(self, node_type: str) -> List['HierarchyNode']:
        result = []
        if self.type == node_type:
            result.append(self)
        for child in self.children:
            result.extend(child.get_all_by_type(node_type))
        return result
    
    def get_all_references(self) -> List[Reference]:
        """모든 참조 수집"""
        refs = list(self.references)
        for child in self.children:
            refs.extend(child.get_all_references())
        return refs
    
    def get_full_text(self) -> str:
        texts = [self.content] if self.content else []
        for child in self.children:
            texts.append(child.get_full_text())
        return "\n".join(filter(None, texts))


# =============================================================================
# 참조 추출기
# =============================================================================

class ReferenceExtractor:
    """참조 패턴 추출"""
    
    def __init__(self, external_laws: set = None, current_doc_name: str = ""):
        self.external_laws = external_laws or set()
        self.current_doc_name = current_doc_name
        
        # 동적 패턴 생성 - 【법규N】에서 수집된 법률명 사용
        if self.external_laws:
            laws_pattern = '|'.join(re.escape(law) for law in self.external_laws)
            self.re_external = re.compile(
                rf'({laws_pattern})\s*제\s*(\d+)\s*조(?:의\s*(\d+))?\s*'
                rf'(?:제?\s*(\d+)\s*항)?(?:제?\s*(\d+)\s*호)?'
            )
        else:
            # fallback: 일반 패턴 (XX법, XX령, XX규정 등)
            self.re_external = re.compile(
                r'([가-힣]+(?:법|령|규정|규칙))\s*제\s*(\d+)\s*조(?:의\s*(\d+))?\s*'
                r'(?:제?\s*(\d+)\s*항)?(?:제?\s*(\d+)\s*호)?'
            )
        
        # 내부 참조 (동일 문서): "제6조(보험금의 청구)에서 정한", "제1항에서 보장하는"
        self.re_internal_jo = re.compile(
            r'제\s*(\d+)\s*조(?:의\s*(\d+))?\s*'
            r'(?:[(\[（]([^)\]）]*)[)\]）])?\s*'
            r'(?:제?\s*(\d+)\s*항)?'
            r'(?:제?\s*(\d+)\s*호)?'
            r'(?:([가나다라마바사아자차카타파하])\s*목)?'
        )
        
        # 항만 참조: "제1항에서", "제2항의"
        self.re_hang_only = re.compile(r'제\s*(\d+)\s*항')
        
        # 호만 참조: "제1호", "제2호의"
        self.re_ho_only = re.compile(r'제\s*(\d+)\s*호')
    
    def extract(self, content: str, source_id: str, current_jo: Optional[int] = None) -> List[Reference]:
        """
        텍스트에서 참조 추출
        
        Args:
            content: 분석할 텍스트
            source_id: 현재 노드 ID
            current_jo: 현재 조 번호 (상대 참조 해석용)
        """
        references = []
        
        # 1. 외부 법률 참조 추출
        for match in self.re_external.finditer(content):
            law_name = match.group(1)
            
            # 현재 문서명이 포함되면 내부 참조로 처리 (스킵)
            if self.current_doc_name and self.current_doc_name in law_name:
                continue
            
            # "약관"이 포함되면 내부 참조일 가능성 높음
            if "약관" in law_name:
                continue
            
            ref = Reference(
                ref_type='external',
                source_id=source_id,
                target_law=law_name,
                target_jo=int(match.group(2)),
                target_jo_branch=int(match.group(3)) if match.group(3) else None,
                target_hang=int(match.group(4)) if match.group(4) else None,
                target_ho=int(match.group(5)) if match.group(5) else None,
                raw_text=match.group(0)
            )
            references.append(ref)
        
        # 2. 내부 참조 추출 (외부 법률 참조와 겹치지 않는 것만)
        external_spans = [(m.start(), m.end()) for m in self.re_external.finditer(content)]
        
        for match in self.re_internal_jo.finditer(content):
            # 외부 참조와 겹치는지 확인
            is_external = False
            for start, end in external_spans:
                if start <= match.start() < end:
                    is_external = True
                    break
            
            if not is_external:
                ref = Reference(
                    ref_type='internal',
                    source_id=source_id,
                    target_jo=int(match.group(1)),
                    target_jo_branch=int(match.group(2)) if match.group(2) else None,
                    target_hang=int(match.group(4)) if match.group(4) else None,
                    target_ho=int(match.group(5)) if match.group(5) else None,
                    target_mok=match.group(6) if match.group(6) else None,
                    raw_text=match.group(0)
                )
                references.append(ref)
        
        # 3. 항만 참조 (현재 조 기준)
        # "제1항에서 보장하는" 같은 경우 → 현재 조의 제1항
        if current_jo:
            for match in self.re_hang_only.finditer(content):
                # 이미 조+항으로 추출된 것과 겹치는지 확인
                already_extracted = any(
                    r.target_jo and r.target_hang == int(match.group(1))
                    for r in references
                )
                if not already_extracted:
                    # 주변 컨텍스트 확인 - "제N조"가 근처에 없으면 현재 조 참조
                    context_start = max(0, match.start() - 20)
                    context = content[context_start:match.start()]
                    if not re.search(r'제\s*\d+\s*조', context):
                        ref = Reference(
                            ref_type='internal',
                            source_id=source_id,
                            target_jo=current_jo,
                            target_hang=int(match.group(1)),
                            raw_text=match.group(0)
                        )
                        references.append(ref)
        
        return references


# =============================================================================
# 패턴 매처
# =============================================================================

class PatternMatcher:
    """계층 패턴 매칭"""
    
    def __init__(self, doc_type: str = DOC_TYPE_INSURANCE):
        self.doc_type = doc_type
        
        # 편: 제N편
        self.re_pyeon = re.compile(r'^제\s*(\d+)\s*편\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        
        # 장: 제N장 또는 제N장의M (가지 장)
        self.re_jang_branch = re.compile(r'^제\s*(\d+)\s*장의\s*(\d+)\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        self.re_jang = re.compile(r'^제\s*(\d+)\s*장\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        
        # 절: 제N절
        self.re_jeol = re.compile(r'^제\s*(\d+)\s*절\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        
        # 관: 제N관
        self.re_gwan = re.compile(r'^제\s*(\d+)\s*관\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        
        # 조: 여러 형태 지원
        self.re_jo_branch_bracket = re.compile(r'^제\s*(\d+)\s*조의\s*(\d+)\s*\[([^\]]*)\](.*)', re.DOTALL)
        self.re_jo_branch = re.compile(r'^제\s*(\d+)\s*조의\s*(\d+)\s*[(\[（]([^)\]）]*)[)\]）]?(.*)', re.DOTALL)
        self.re_jo_bracket = re.compile(r'^제\s*(\d+)\s*조\s*\[([^\]]*)\](.*)', re.DOTALL)
        self.re_jo = re.compile(r'^제\s*(\d+)\s*조\s*[(\[（]([^)\]）]*)[)\]）](.*)', re.DOTALL)
        self.re_jo_no_paren = re.compile(r'^제\s*(\d+)\s*조\s+(.*)$')
        
        # 항: ①②③
        self.re_hang = re.compile(r'^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*(.*)$')
        
        # 호: 1. 2. 3.
        self.re_ho = re.compile(r'^(\d+)\.\s+(.+)$')
        
        # 목: 가. 나. 다.
        self.re_mok = re.compile(r'^([가나다라마바사아자차카타파하])\.\s+(.+)$')
        
        # 세목: (ⅰ) (ⅱ)
        self.re_semok = re.compile(r'^\s*[\(（]\s*([ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ]|i{1,3}|iv|vi{0,3}|ix|x)\s*[\)）]\s*(.+)$', re.IGNORECASE)
        
        # 대시: -
        self.re_dash = re.compile(r'^[-－‐–—]\s*(.+)$')
        
        # 특수 블록: 【】
        self.re_special = re.compile(r'^(?:【([^】]+)】|<([^>]+)>)')

    
    def match(self, content: str) -> Optional[Dict]:
        content = content.strip()
        if not content:
            return None
        
        re_jo_reference = re.compile(
            r'^제\s*\d+\s*조(?:의\s*\d+)?\s*'
            r'(?:[(\[（][^)\]）]*[)\]）])?\s*'
            r'(의\s|에\s|를\s|와\s|과\s|에서\s|으로\s|부터\s)'
        )
        if re_jo_reference.match(content):
            return None

        # 특수 블록
        m = self.re_special.match(content)
        if m:
            # 【】 또는 <> 둘 중 매칭된 것 사용
            title = m.group(1) or m.group(2)
            if m.group(1):
                marker = f"【{m.group(1)}】"
            else:
                marker = f"<{m.group(2)}>"
            return {
                'type': 'special', 'level': -1, 'number': None,
                'marker': marker, 'title': title,
                'body': '', 'rest': content
            }
        
        # 편
        m = self.re_pyeon.match(content)
        if m:
            return {
                'type': '편', 'level': LEVEL_PYEON,
                'number': int(m.group(1)), 'branch': None,
                'marker': f"제{m.group(1)}편",
                'title': m.group(2).strip() or content,
                'body': '', 'rest': ''
            }
        
        # 장의N (가지 장)
        m = self.re_jang_branch.match(content)
        if m:
            return {
                'type': '장', 'level': LEVEL_JANG,
                'number': int(m.group(1)), 'branch': int(m.group(2)),
                'marker': f"제{m.group(1)}장의{m.group(2)}",
                'title': m.group(3).strip() or content,
                'body': '', 'rest': ''
            }
        
        # 장
        m = self.re_jang.match(content)
        if m:
            return {
                'type': '장', 'level': LEVEL_JANG,
                'number': int(m.group(1)), 'branch': None,
                'marker': f"제{m.group(1)}장",
                'title': m.group(2).strip() or content,
                'body': '', 'rest': ''
            }
        
        # 절
        m = self.re_jeol.match(content)
        if m:
            return {
                'type': '절', 'level': LEVEL_JEOL,
                'number': int(m.group(1)), 'branch': None,
                'marker': f"제{m.group(1)}절",
                'title': m.group(2).strip() or content,
                'body': '', 'rest': ''
            }
        
        # 관
        m = self.re_gwan.match(content)
        if m:
            return {
                'type': '관', 'level': LEVEL_GWAN,
                'number': int(m.group(1)), 'branch': None,
                'marker': f"제{m.group(1)}관",
                'title': m.group(2).strip() or content,
                'body': '', 'rest': ''
            }
        
        # 조의N (가지조항) - 대괄호
        m = self.re_jo_branch_bracket.match(content)
        if m:
            return {
                'type': '조', 'level': LEVEL_JO,
                'number': int(m.group(1)), 'branch': int(m.group(2)),
                'marker': f"제{m.group(1)}조의{m.group(2)}",
                'title': m.group(3).strip(),
                'body': m.group(4).strip() if m.group(4) else '',
                'rest': content
            }
        
        # 조의N (가지조항) - 소괄호
        m = self.re_jo_branch.match(content)
        if m:
            return {
                'type': '조', 'level': LEVEL_JO,
                'number': int(m.group(1)), 'branch': int(m.group(2)),
                'marker': f"제{m.group(1)}조의{m.group(2)}",
                'title': m.group(3).strip() if m.group(3) else '',
                'body': m.group(4).strip() if m.group(4) else '',
                'rest': content
            }
        
        # 조 - 대괄호
        m = self.re_jo_bracket.match(content)
        if m:
            return {
                'type': '조', 'level': LEVEL_JO,
                'number': int(m.group(1)), 'branch': None,
                'marker': f"제{m.group(1)}조",
                'title': m.group(2).strip(),
                'body': m.group(3).strip() if m.group(3) else '',
                'rest': content
            }
        
        # 조 - 소괄호
        m = self.re_jo.match(content)
        if m:
            return {
                'type': '조', 'level': LEVEL_JO,
                'number': int(m.group(1)), 'branch': None,
                'marker': f"제{m.group(1)}조",
                'title': m.group(2).strip() if m.group(2) else '',
                'body': m.group(3).strip() if m.group(3) else '',
                'rest': content
            }
        
        # 조 - 괄호 없음
        m = self.re_jo_no_paren.match(content)
        if m:
            return {
                'type': '조', 'level': LEVEL_JO,
                'number': int(m.group(1)), 'branch': None,
                'marker': f"제{m.group(1)}조",
                'title': m.group(2).strip()[:20] if m.group(2) else '',
                'body': '', 'rest': content
            }
        
        # 항
        m = self.re_hang.match(content)
        if m:
            return {
                'type': '항', 'level': LEVEL_HANG,
                'number': CIRCLED_NUMBERS.get(m.group(1), 1), 'branch': None,
                'marker': m.group(1),
                'title': m.group(2)[:50] if m.group(2) else '',
                'body': '', 'rest': m.group(2)
            }
        
        # 호
        m = self.re_ho.match(content)
        if m:
            return {
                'type': '호', 'level': LEVEL_HO,
                'number': int(m.group(1)), 'branch': None,
                'marker': f"{m.group(1)}.",
                'title': m.group(2)[:50],
                'body': '', 'rest': m.group(2)
            }
        
        # 목
        m = self.re_mok.match(content)
        if m:
            return {
                'type': '목', 'level': LEVEL_MOK,
                'number': MOK_CHARS.index(m.group(1)) + 1, 'branch': None,
                'marker': f"{m.group(1)}.",
                'title': m.group(2)[:50],
                'body': '', 'rest': m.group(2)
            }
        
        # 세목
        m = self.re_semok.match(content)
        if m:
            return {
                'type': '세목', 'level': LEVEL_SEMOK,
                'number': ROMAN_NUMERALS.get(m.group(1).lower(), 1), 'branch': None,
                'marker': f"({m.group(1)})",
                'title': m.group(2)[:50],
                'body': '', 'rest': m.group(2)
            }
        
        # 대시
        m = self.re_dash.match(content)
        if m:
            return {
                'type': '대시', 'level': LEVEL_DASH,
                'number': None, 'branch': None,
                'marker': '-',
                'title': m.group(1)[:50],
                'body': '', 'rest': m.group(1)
            }
        
        return None


# =============================================================================
# 메인 파서
# =============================================================================

class DocumentParser:
    """보험약관/법률 문서 파서 v4"""
    
    def __init__(self, input_dir: str, doc_type: str = DOC_TYPE_INSURANCE):
        self.input_dir = Path(input_dir)
        self.doc_type = doc_type
        self.blocks: List[Dict] = []
        self.root = HierarchyNode(
            id="root", type="document", level=-1, title="문서"
        )
        self.matcher = PatternMatcher(doc_type)
        self.ref_extractor: Optional[ReferenceExtractor] = None  # parse()에서 초기화
        self.stats = defaultdict(int)
        self.all_references: List[Reference] = []
        
        # 동적으로 수집되는 정보
        self.external_laws: set = set()      # 【법규N】에서 추출된 법률명
        self.current_doc_name: str = ""       # 현재 문서명
    
    def load_blocks(self) -> None:
        """블록 로드"""
        print("=" * 80)
        print("블록 로딩")
        print("=" * 80)
        
        json_files = sorted(self.input_dir.glob("page_*_res.json"))
        print(f"파일 수: {len(json_files)}개")
        
        for json_file in json_files:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                page_index = data['page_index']
                
                for block in data['parsing_res_list']:
                    block['page_index'] = page_index
                    self.blocks.append(block)
        
        print(f"총 블록 수: {len(self.blocks)}개\n")
    
    def parse(self) -> HierarchyNode:
        """파싱 실행"""
        self.load_blocks()
        
        # Step 1: 외부 법률 목록 자동 수집
        print("=" * 80)
        print("외부 법률 수집")
        print("=" * 80)
        self.external_laws = self._collect_external_laws()
        if self.external_laws:
            print(f"감지된 외부 법률 ({len(self.external_laws)}개):")
            for law in sorted(self.external_laws):
                print(f"  - {law}")
        else:
            print("  (【법규】 섹션 없음 - fallback 패턴 사용)")
        
        # Step 2: 참조 추출기 초기화 (수집된 법률 목록 전달)
        self.ref_extractor = ReferenceExtractor(
            external_laws=self.external_laws,
            current_doc_name=self.current_doc_name
        )
        
        # Step 3: 섹션 감지
        print("\n" + "=" * 80)
        print("섹션 감지")
        print("=" * 80)
        sections = self._detect_sections()
        print(f"섹션 수: {len(sections)}개\n")
        
        # Step 4: 각 섹션 파싱
        print("=" * 80)
        print("계층 파싱")
        print("=" * 80)
        
        for section_info in sections:
            section_node = self._parse_section(section_info)
            self.root.children.append(section_node)
            jo_count = len(section_node.get_all_by_type('조'))
            ref_count = len(section_node.get_all_references())
            print(f"  {section_info['name'][:30]}: 조 {jo_count}개, 참조 {ref_count}개")
        
        # Step 5: 참조 해석
        print("\n" + "=" * 80)
        print("참조 해석")
        print("=" * 80)
        self._resolve_references()
        
        self._print_stats()
        return self.root
    
    def _collect_external_laws(self) -> set:
        """【법규N】 섹션에서 법률명 자동 추출"""
        laws = set()
        
        for block in self.blocks:
            content = block.get('block_content', '').strip()
            
            # 【법규N】 패턴: "【법규6】 보험업법 시행령" → "보험업법 시행령"
            match = re.match(r'^【법규\d*】\s*(.+)$', content)
            if match:
                law_name = match.group(1).strip()
                laws.add(law_name)
                continue
            
            # 단독 법률명 (섹션 제목): "민법", "상법" 등
            if re.match(r'^[가-힣]+(?:법|령|규정|규칙)\s*$', content):
                laws.add(content.strip())
        
        return laws
    
    def _detect_sections(self) -> List[Dict]:
        """섹션 감지"""
        sections = []
        
        # 섹션 제목 패턴
        section_patterns = [
            # 약관 패턴
            re.compile(r'^[가-힣A-Za-z0-9\s\(\),，및]+\s*(보통약관|특별약관|추가약관)\s*$'),
            re.compile(r'^[가-힣A-Za-z0-9\s,，및]+\s*(보통약관|특별약관|추가약관)\s*[\(（][^)）]*[\)）]\s*$'),
            
            # 법률 패턴 (동적 - XX법, XX령 등)
            re.compile(r'^[가-힣]+(?:법|령|규정|규칙)\s*$'),
            re.compile(r'^【법규\d*】'),
            
            # 민원/분쟁/유의사항
            re.compile(r'^주요\s*(민원|분쟁|사례|유의)'),
            re.compile(r'^(민원|분쟁)\s*(사례|안내|처리)'),
            re.compile(r'^유의\s*사항'),
            re.compile(r'민원.*분쟁.*유의', re.IGNORECASE),
            re.compile(r'분쟁.*사례.*유의', re.IGNORECASE),
            
            # 슬래시 구분 제목
            re.compile(r'^[가-힣A-Za-z0-9\s]+\s*/\s*[가-힣A-Za-z0-9\s]+'),
        ]
        
        # 섹션이 아닌 패턴 (문장)
        not_section_patterns = [
            re.compile(r'^이\s+'),
            re.compile(r'^본\s+'),
            re.compile(r'^회사는\s+'),
            re.compile(r'^보통약관에서\s+'),
            re.compile(r'^상기'),
            re.compile(r'합니다\.?\s*$'),
            re.compile(r'않습니다\.?\s*$'),
            re.compile(r'됩니다\.?\s*$'),
            re.compile(r'입니다\.?\s*$'),
        ]
        
        for i, block in enumerate(self.blocks):
            content = block.get('block_content', '').strip()
            
            if not content or len(content) > 80:
                continue
            
            # 계층 패턴 제외
            if re.match(r'^[가나다라마바사아자차카타파하]\.\s', content):
                continue
            if re.match(r'^\d+\.\s', content):
                continue
            if re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]', content):
                continue
            if re.match(r'^제\s*\d+\s*조', content):
                continue
            
            # 문장 패턴 제외
            is_sentence = any(p.search(content) for p in not_section_patterns)
            if is_sentence:
                continue
            
            # 섹션 패턴 체크
            is_section = any(p.match(content) or p.search(content) for p in section_patterns)
            
            if is_section:
                sections.append({'name': content.strip(), 'index': i})
        
        if not sections:
            return [{'name': '본문', 'index': 0, 'end': len(self.blocks)}]
        
        for i in range(len(sections)):
            sections[i]['end'] = sections[i+1]['index'] if i+1 < len(sections) else len(self.blocks)
        
        return sections
    
    def _parse_section(self, section_info: Dict) -> HierarchyNode:
        """섹션 내부 파싱"""
        section_node = HierarchyNode(
            id=section_info['name'],
            type='section',
            level=LEVEL_SECTION,
            title=section_info['name']
        )
        
        blocks = self.blocks[section_info['index']:section_info['end']]
        
        stack: Dict[int, HierarchyNode] = {LEVEL_SECTION: section_node}
        last_numbers: Dict[int, int] = {lvl: 0 for lvl in range(LEVEL_PYEON, LEVEL_DASH + 1)}
        
        in_special_block = False
        current_special_node: Optional[HierarchyNode] = None
        current_jo_number: Optional[int] = None  # 현재 조 번호 (참조 해석용)
        
        for i, block in enumerate(blocks):
            content = block.get('block_content', '').strip()
            page = block.get('page_index', 0)
            
            if not content:
                continue
            
            # 글로벌 특수 블록 체크
            global_special = self._check_global_special(content)
            if global_special:
                in_special_block = True
                self._reset_stack_below(stack, LEVEL_SECTION)
                last_numbers = {k: 0 for k in last_numbers}
                current_jo_number = None
                
                current_special_node = HierarchyNode(
                    id=f"{section_info['name']}.{global_special['marker']}",
                    type='special', level=-1,
                    marker=global_special['marker'],
                    title=global_special['title'],
                    content=content, page=page,
                    metadata={'special_type': global_special['type'], 'global': True}
                )
                section_node.children.append(current_special_node)
                self.stats['special'] += 1
                continue
            
            # 특수 블록 모드
            if in_special_block and current_special_node:
                # 글로벌 special은 조/관/장/절/편에서만 종료
                if current_special_node.metadata.get('global'):
                    if re.match(r'^제\s*\d+\s*(조|관|장|절|편)', content):
                        in_special_block = False
                        current_special_node = None
                    else:
                        current_special_node.content += "\n" + content
                        continue
                # 인라인 special은 계층 패턴(항/호/목 등)에서도 종료
                else:
                    if self.matcher.match(content):
                        in_special_block = False
                        current_special_node = None
                        # continue 하지 않음 - 아래에서 정상 파싱
                    else:
                        current_special_node.content += "\n" + content
                        continue
            
            # 패턴 매칭
            match_info = self.matcher.match(content)
            
            if match_info:
                node_type = match_info['type']
                node_level = match_info['level']
                node_number = match_info['number']
                node_branch = match_info.get('branch')
                
                # 인라인 특수 블록
                if node_type == 'special':
                    special_node = HierarchyNode(
                        id=f"{section_info['name']}.{match_info['marker']}",
                        type='special', level=-1,
                        marker=match_info['marker'],
                        title=match_info['title'],
                        content=content, page=page,
                        metadata={'special_type': match_info['title'], 'inline': True}
                    )
                    
                    # 현재 가장 깊은 노드의 부모에 형제로 추가
                    parent = self._find_parent_for_special(stack)
                    parent.children.append(special_node)
                    
                    current_special_node = special_node
                    in_special_block = True
                    
                    
                    self.stats['special'] += 1
                    continue                

                
                # 컨텍스트 관리
                self._manage_context(stack, last_numbers, node_type, node_level, node_number, page)
                
                # 노드 생성
                parent = self._find_parent(stack, node_level)
                node_content = content
                
                # 조인 경우 body 분리
                if node_type == '조' and match_info.get('body'):
                    jo_body = match_info['body']
                    node_content = content.replace(jo_body, '').strip()
                
                new_node = HierarchyNode(
                    id=f"{parent.id}.{match_info['marker']}",
                    type=node_type,
                    level=node_level,
                    number=node_number,
                    branch=node_branch,
                    marker=match_info['marker'],
                    title=match_info['title'],
                    content=node_content,
                    page=page
                )
                
                # 참조 추출
                refs = self.ref_extractor.extract(content, new_node.id, current_jo_number)
                new_node.references = refs
                self.all_references.extend(refs)
                
                parent.children.append(new_node)
                stack[node_level] = new_node
                
                if node_level in last_numbers and node_number:
                    last_numbers[node_level] = node_number
                
                self.stats[node_type] += 1
                
                # 조 처리
                if node_type == '조':
                    current_jo_number = node_number
                    stack[LEVEL_HANG] = None
                    
                    # body가 있으면 자동 1항
                    jo_body = match_info.get('body', '').strip()
                    if jo_body:
                        auto_hang = HierarchyNode(
                            id=f"{new_node.id}.①",
                            type='항', level=LEVEL_HANG,
                            number=1, marker='①',
                            title=jo_body[:30], content=jo_body, page=page,
                            metadata={'auto_generated': True}
                        )
                        # 자동 항에서도 참조 추출
                        hang_refs = self.ref_extractor.extract(jo_body, auto_hang.id, current_jo_number)
                        auto_hang.references = hang_refs
                        self.all_references.extend(hang_refs)
                        
                        new_node.children.append(auto_hang)
                        stack[LEVEL_HANG] = auto_hang
                        self.stats['항(자동)'] += 1
            
            else:
                # 패턴 없는 블록
                if in_special_block and current_special_node:
                    current_special_node.content += "\n" + content
                    continue
                
                if LEVEL_JO in stack and stack[LEVEL_JO]:
                    jo_node = stack[LEVEL_JO]
                    
                    if LEVEL_HANG not in stack or stack[LEVEL_HANG] is None:
                        auto_hang = HierarchyNode(
                            id=f"{jo_node.id}.①",
                            type='항', level=LEVEL_HANG,
                            number=1, marker='①',
                            title=content[:30], content=content, page=page,
                            metadata={'auto_generated': True}
                        )
                        refs = self.ref_extractor.extract(content, auto_hang.id, current_jo_number)
                        auto_hang.references = refs
                        self.all_references.extend(refs)
                        
                        jo_node.children.append(auto_hang)
                        stack[LEVEL_HANG] = auto_hang
                        self.stats['항(자동)'] += 1
                    else:
                        recent = self._find_most_recent(stack)
                        if recent and recent.type != 'section':
                            recent.content += "\n" + content
                            # 추가된 내용에서도 참조 추출
                            refs = self.ref_extractor.extract(content, recent.id, current_jo_number)
                            recent.references.extend(refs)
                            self.all_references.extend(refs)
                else:
                    recent = self._find_most_recent(stack)
                    if recent and recent.type != 'section':
                        recent.content += "\n" + content
        
        return section_node
    
    def _check_global_special(self, content: str) -> Optional[Dict]:
        """글로벌 특수 블록 체크"""
        if re.match(r'^[\[【]별표\s*(\d*)[\]】]', content):
            m = re.match(r'^[\[【]별표\s*(\d*)[\]】]', content)
            return {'type': 'appendix', 'marker': f"[별표{m.group(1)}]", 'title': content[:50]}
        
        if re.match(r'^※\s*용어', content):
            return {'type': 'glossary', 'marker': '※용어정의', 'title': content[:50]}
        
        if re.match(r'^비고\s*$', content) or re.match(r'^비고\s*\d', content):
            return {'type': 'note', 'marker': '비고', 'title': content[:50]}
        
        return None
    
    def _manage_context(self, stack: Dict, last_numbers: Dict, 
                        node_type: str, node_level: int, node_number: int, page: int):
        """컨텍스트 관리"""
        if node_type in ('편', '장', '절', '관', '조'):
            self._reset_stack_below(stack, node_level)
            for lvl in range(node_level + 1, LEVEL_DASH + 1):
                if lvl in last_numbers:
                    last_numbers[lvl] = 0
        
        elif node_type == '항':
            self._reset_stack_below(stack, LEVEL_HANG)
            for lvl in [LEVEL_HO, LEVEL_MOK, LEVEL_SEMOK]:
                last_numbers[lvl] = 0
        
        elif node_type == '호':
            if node_number == 1 or node_number == last_numbers[LEVEL_HO] + 1:
                self._ensure_hang_exists(stack, page)
                self._reset_stack_below(stack, LEVEL_HO)
                last_numbers[LEVEL_MOK] = 0
                last_numbers[LEVEL_SEMOK] = 0
            else:
                self._ensure_hang_exists(stack, page)
        
        elif node_type == '목':
            if node_number == 1 or node_number == last_numbers[LEVEL_MOK] + 1:
                self._reset_stack_below(stack, LEVEL_MOK)
                last_numbers[LEVEL_SEMOK] = 0
        
        elif node_type == '세목':
            if node_number == 1:
                self._reset_stack_below(stack, LEVEL_SEMOK)
        
        # 항 자동 생성
        if node_level > LEVEL_HANG and LEVEL_JO in stack and stack[LEVEL_JO]:
            if LEVEL_HANG not in stack or stack[LEVEL_HANG] is None:
                self._ensure_hang_exists(stack, page)
    
    def _reset_stack_below(self, stack: Dict, level: int):
        for lvl in list(stack.keys()):
            if lvl > level:
                del stack[lvl]
    
    def _ensure_hang_exists(self, stack: Dict, page: int):
        if LEVEL_JO in stack and stack[LEVEL_JO]:
            if LEVEL_HANG not in stack or stack[LEVEL_HANG] is None:
                jo_node = stack[LEVEL_JO]
                auto_hang = HierarchyNode(
                    id=f"{jo_node.id}.①",
                    type='항', level=LEVEL_HANG,
                    number=1, marker='①',
                    title='(자동생성)', content='', page=page,
                    metadata={'auto_generated': True}
                )
                jo_node.children.append(auto_hang)
                stack[LEVEL_HANG] = auto_hang
                self.stats['항(자동)'] += 1
    
    def _find_parent(self, stack: Dict, child_level: int) -> HierarchyNode:
        for lvl in sorted(stack.keys(), reverse=True):
            if lvl < child_level and stack[lvl] is not None:
                return stack[lvl]
        return stack.get(LEVEL_SECTION, list(stack.values())[0])
    
    def _find_parent_for_special(self, stack: Dict) -> HierarchyNode:
        deepest_level = max(stack.keys())
        for lvl in sorted(stack.keys(), reverse=True):
            if lvl < deepest_level and stack[lvl] is not None:
                return stack[lvl]
        return stack.get(LEVEL_SECTION, list(stack.values())[0])
    
    def _find_most_recent(self, stack: Dict) -> Optional[HierarchyNode]:
        for lvl in sorted(stack.keys(), reverse=True):
            if stack[lvl] is not None:
                return stack[lvl]
        return None
    
    def _resolve_references(self):
        """참조 해석 - resolved_id 설정"""
        # 모든 조 수집
        all_jos = {}
        for section in self.root.children:
            for jo in section.get_all_by_type('조'):
                key = (section.id, jo.number, jo.branch)
                all_jos[key] = jo.id
        
        resolved_count = 0
        for ref in self.all_references:
            if ref.ref_type == 'internal' and ref.target_jo:
                # 동일 섹션에서 찾기
                source_section = ref.source_id.split('.')[0]
                key = (source_section, ref.target_jo, ref.target_jo_branch)
                
                if key in all_jos:
                    base_id = all_jos[key]
                    parts = [base_id]
                    
                    if ref.target_hang:
                        hang_marker = list(CIRCLED_NUMBERS.keys())[ref.target_hang - 1] if ref.target_hang <= 20 else f"제{ref.target_hang}항"
                        parts.append(hang_marker)
                    
                    if ref.target_ho:
                        parts.append(f"{ref.target_ho}.")
                    
                    if ref.target_mok:
                        parts.append(f"{ref.target_mok}.")
                    
                    ref.resolved_id = ".".join(parts) if len(parts) > 1 else base_id
                    resolved_count += 1
        
        print(f"  해석된 참조: {resolved_count}개 / 전체 {len(self.all_references)}개")
    
    def _print_stats(self):
        print("\n" + "=" * 80)
        print("파싱 통계")
        print("=" * 80)
        
        order = ['편', '장', '절', '관', '조', '항', '항(자동)', '호', '목', '세목', '대시', 'special']
        for key in order:
            if key in self.stats:
                print(f"  {key}: {self.stats[key]}개")
        
        print(f"\n  총 참조: {len(self.all_references)}개")
        internal = sum(1 for r in self.all_references if r.ref_type == 'internal')
        external = sum(1 for r in self.all_references if r.ref_type == 'external')
        print(f"    - 내부 참조: {internal}개")
        print(f"    - 외부 참조: {external}개")
    
    def save(self, output_path: str) -> tuple[Path, Path]:
        """
        결과 저장
        
        Args:
            output_path: 출력 파일 경로 (메인 트리)
        
        Returns:
            (메인 파일 경로, 참조 파일 경로) 튜플
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 메인 트리 저장
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.root.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"\n트리 저장: {output_file}")
        
        # 참조 목록 별도 저장
        ref_file = output_file.parent / f"{output_file.stem}_references.json"
        with open(ref_file, 'w', encoding='utf-8') as f:
            json.dump([r.to_dict() for r in self.all_references], f, ensure_ascii=False, indent=2)
        print(f"참조 저장: {ref_file}")
        
        return output_file, ref_file


# =============================================================================
# 유틸리티
# =============================================================================

def load_document(json_path: str) -> HierarchyNode:
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return _dict_to_node(data)


def _dict_to_node(data: Dict) -> HierarchyNode:
    node = HierarchyNode(
        id=data['id'],
        type=data['type'],
        level=data.get('level', 0),
        number=data.get('number'),
        branch=data.get('branch'),
        marker=data.get('marker', ''),
        title=data.get('title', ''),
        content=data.get('content', ''),
        page=data.get('page', 0),
        metadata=data.get('metadata', {})
    )
    
    for ref_data in data.get('references', []):
        ref = Reference(
            ref_type=ref_data['ref_type'],
            source_id=ref_data['source_id'],
            target_law=ref_data.get('target_law'),
            target_jo=ref_data.get('target_jo'),
            target_jo_branch=ref_data.get('target_jo_branch'),
            target_hang=ref_data.get('target_hang'),
            target_ho=ref_data.get('target_ho'),
            target_mok=ref_data.get('target_mok'),
            raw_text=ref_data.get('raw_text', ''),
            resolved_id=ref_data.get('resolved_id')
        )
        node.references.append(ref)
    
    for child in data.get('children', []):
        node.children.append(_dict_to_node(child))
    
    return node


# =============================================================================
# 파이프라인 함수
# =============================================================================

def process_hierarchy_parsing(
    parsing_results_dir: Path,
    output_file: Path,
    doc_type: str = DOC_TYPE_INSURANCE
) -> tuple[Path, Path]:
    """
    계층 구조 파싱 실행
    
    Args:
        parsing_results_dir: parsing_results 디렉토리 경로
        output_file: 출력 JSON 파일 경로 (메인 트리)
        doc_type: 문서 타입 (DOC_TYPE_INSURANCE 또는 DOC_TYPE_LAW)
    
    Returns:
        (메인 파일 경로, 참조 파일 경로) 튜플
    """
    parser = DocumentParser(str(parsing_results_dir), doc_type=doc_type)
    root = parser.parse()
    main_file, ref_file = parser.save(str(output_file))
    return main_file, ref_file


# =============================================================================
# 메인 (단일 실행용)
# =============================================================================

def main():
    input_dir = r"C:\Users\bigda\Desktop\graph_rag\output\test_full\layout_parsing_output\parsing_results"
    output_file = r"C:\Users\bigda\Desktop\graph_rag\output\test_full\parsed_hierarchy_v4.json"
    
    # 파싱 실행
    parser = DocumentParser(input_dir, doc_type=DOC_TYPE_INSURANCE)
    root = parser.parse()
    parser.save(output_file)
    
    # 트리 미리보기
    print("\n" + "=" * 80)
    print("트리 구조 (깊이 3)")
    print("=" * 80)
    root.print_tree(max_depth=3)
    
    # 참조 예시 출력
    print("\n" + "=" * 80)
    print("참조 예시 (처음 10개)")
    print("=" * 80)
    for ref in parser.all_references[:10]:
        print(f"  [{ref.ref_type}] {ref.raw_text}")
        print(f"    → 대상: 조{ref.target_jo}, 항{ref.target_hang}, 호{ref.target_ho}")
        if ref.resolved_id:
            print(f"    → 해석: {ref.resolved_id}")
        print()


if __name__ == "__main__":
    main()