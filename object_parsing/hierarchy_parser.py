"""
보험약관/법률 계층 구조 파싱 시스템 v4 (박스 감지 지원)

주요 기능:
1. 보험약관 및 법률 문서 계층 파싱
2. 참조(reference) 자동 추출 및 연결
3. 장의2, 조의2 등 가지 조항 지원
4. 트리 구조 저장 및 탐색
5. inside_box 기반 special 블록 경계 감지

계층 구조:
- 보험약관: 약관 → 관 → 조 → 항 → 호 → 목 → 세목 → 대시
- 법률: 법률 → 편 → 장 → 절 → 관 → 조 → 항 → 호 → 목 → 세목

Special 블록 처리:
- 글로벌 special (별표, 법규): 제N조에서 종료
- 인라인 special (박스 있음): inside_box=False 나올 때 종료
- 인라인 special (박스 없음): 새 계층 패턴 나올 때 종료
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

CIRCLED_NUMBERS = {
    '①':1, '②':2, '③':3, '④':4, '⑤':5,
    '⑥':6, '⑦':7, '⑧':8, '⑨':9, '⑩':10,
    '⑪':11, '⑫':12, '⑬':13, '⑭':14, '⑮':15,
    '⑯':16, '⑰':17, '⑱':18, '⑲':19, '⑳':20
}

ROMAN_NUMERALS = {
    'ⅰ':1, 'ⅱ':2, 'ⅲ':3, 'ⅳ':4, 'ⅴ':5,
    'ⅵ':6, 'ⅶ':7, 'ⅷ':8, 'ⅸ':9, 'ⅹ':10,
    'i':1, 'ii':2, 'iii':3, 'iv':4, 'v':5,
    'vi':6, 'vii':7, 'viii':8, 'ix':9, 'x':10
}

MOK_CHARS = "가나다라마바사아자차카타파하"

LEVEL_SECTION = 0
LEVEL_PYEON = 1
LEVEL_JANG = 2
LEVEL_JEOL = 3
LEVEL_GWAN = 4
LEVEL_JO = 5
LEVEL_HANG = 6
LEVEL_HO = 7
LEVEL_MOK = 8
LEVEL_SEMOK = 9
LEVEL_DASH = 10

DOC_TYPE_INSURANCE = 'insurance'
DOC_TYPE_LAW = 'law'


# =============================================================================
# 참조(Reference) 데이터 클래스
# =============================================================================

@dataclass
class Reference:
    ref_type: str
    source_id: str
    target_law: Optional[str] = None
    target_jo: Optional[int] = None
    target_jo_branch: Optional[int] = None
    target_hang: Optional[int] = None
    target_ho: Optional[int] = None
    target_mok: Optional[str] = None
    raw_text: str = ""
    resolved_id: Optional[str] = None
    
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
    id: str
    type: str
    level: int
    number: Optional[int] = None
    branch: Optional[int] = None
    marker: str = ""
    title: str = ""
    content: str = ""
    page: int = 0
    children: List['HierarchyNode'] = field(default_factory=list)
    references: List[Reference] = field(default_factory=list)
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
        m = re.match(r'제(\d+)편', query)
        if m:
            return node.type == '편' and node.number == int(m.group(1))
        
        m = re.match(r'제(\d+)장(?:의(\d+))?', query)
        if m:
            if node.type == '장' and node.number == int(m.group(1)):
                if m.group(2):
                    return node.branch == int(m.group(2))
                return node.branch is None
            return False
        
        m = re.match(r'제(\d+)절', query)
        if m:
            return node.type == '절' and node.number == int(m.group(1))
        
        m = re.match(r'제(\d+)조(?:의(\d+))?', query)
        if m:
            if node.type == '조' and node.number == int(m.group(1)):
                if m.group(2):
                    return node.branch == int(m.group(2))
                return node.branch is None
            return False
        
        m = re.match(r'제(\d+)관', query)
        if m:
            return node.type == '관' and node.number == int(m.group(1))
        
        if query in CIRCLED_NUMBERS:
            return node.type == '항' and node.number == CIRCLED_NUMBERS[query]
        
        if query.isdigit():
            return node.type == '호' and node.number == int(query)
        
        if query in MOK_CHARS:
            return node.type == '목' and node.number == MOK_CHARS.index(query) + 1
        
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
    def __init__(self, external_laws: set = None, current_doc_name: str = ""):
        self.external_laws = external_laws or set()
        self.current_doc_name = current_doc_name
        
        if self.external_laws:
            laws_pattern = '|'.join(re.escape(law) for law in self.external_laws)
            self.re_external = re.compile(
                rf'({laws_pattern})\s*제\s*(\d+)\s*조(?:의\s*(\d+))?\s*'
                rf'(?:제?\s*(\d+)\s*항)?(?:제?\s*(\d+)\s*호)?'
            )
        else:
            self.re_external = re.compile(
                r'([가-힣]+(?:법|령|규정|규칙))\s*제\s*(\d+)\s*조(?:의\s*(\d+))?\s*'
                r'(?:제?\s*(\d+)\s*항)?(?:제?\s*(\d+)\s*호)?'
            )
        
        self.re_internal_jo = re.compile(
            r'제\s*(\d+)\s*조(?:의\s*(\d+))?\s*'
            r'(?:[(\[（]([^)\]）]*)[)\]）])?\s*'
            r'(?:제?\s*(\d+)\s*항)?'
            r'(?:제?\s*(\d+)\s*호)?'
            r'(?:([가나다라마바사아자차카타파하])\s*목)?'
        )
        
        self.re_hang_only = re.compile(r'제\s*(\d+)\s*항')
        self.re_ho_only = re.compile(r'제\s*(\d+)\s*호')
    
    def extract(self, content: str, source_id: str, current_jo: Optional[int] = None) -> List[Reference]:
        references = []
        
        for match in self.re_external.finditer(content):
            law_name = match.group(1)
            if self.current_doc_name and self.current_doc_name in law_name:
                continue
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
        
        external_spans = [(m.start(), m.end()) for m in self.re_external.finditer(content)]
        
        for match in self.re_internal_jo.finditer(content):
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
        
        if current_jo:
            for match in self.re_hang_only.finditer(content):
                already_extracted = any(
                    r.target_jo and r.target_hang == int(match.group(1))
                    for r in references
                )
                if not already_extracted:
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
    def __init__(self, doc_type: str = DOC_TYPE_INSURANCE):
        self.doc_type = doc_type
        
        self.re_pyeon = re.compile(r'^제\s*(\d+)\s*편\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        self.re_jang_branch = re.compile(r'^제\s*(\d+)\s*장의\s*(\d+)\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        self.re_jang = re.compile(r'^제\s*(\d+)\s*장\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        self.re_jeol = re.compile(r'^제\s*(\d+)\s*절\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        self.re_gwan = re.compile(r'^제\s*(\d+)\s*관\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        
        self.re_jo_branch_bracket = re.compile(r'^제\s*(\d+)\s*조의\s*(\d+)\s*\[([^\]]*)\](.*)', re.DOTALL)
        self.re_jo_branch = re.compile(r'^제\s*(\d+)\s*조의\s*(\d+)\s*[(\[（]([^)\]）]*)[)\]）]?(.*)', re.DOTALL)
        self.re_jo_bracket = re.compile(r'^제\s*(\d+)\s*조\s*\[([^\]]*)\](.*)', re.DOTALL)
        self.re_jo = re.compile(r'^제\s*(\d+)\s*조\s*[(\[（]([^)\]）]*)[)\]）](.*)', re.DOTALL)
        self.re_jo_no_paren = re.compile(r'^제\s*(\d+)\s*조\s+(.*)$')
        
        self.re_hang = re.compile(r'^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*(.*)$')
        self.re_ho = re.compile(r'^(\d+)\.\s+(.+)$')
        self.re_mok = re.compile(r'^([가나다라마바사아자차카타파하])\.\s+(.+)$')
        self.re_semok = re.compile(r'^\s*[\(（]\s*([ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ]|i{1,3}|iv|vi{0,3}|ix|x)\s*[\)）]\s*(.+)$', re.IGNORECASE)
        self.re_dash = re.compile(r'^[-－‐–—]\s*(.+)$')
        self.re_special = re.compile(r'^(?:【([^】]+)】|<([^>]+)>)')

    def match(self, content: str) -> Optional[Dict]:
        content = content.strip()
        if not content:
            return None
        
        re_jo_reference = re.compile(
            r'^제\s*\d+\s*조(?:의\s*\d+)?\s*'
            r'(?:[(\[（][^)\]）]*[)\]）])?\s*'
            r'(?:제?\s*\d+\s*(?:항|호|목)[\s,]*)*'
            r'(?:및\s*제?\s*\d+\s*(?:항|호|목)[\s,]*)*'
            r'(의|에|를|와|과|에서|으로|부터|에\s*따라|에\s*의하여|에\s*해당|에\s*관한|에\s*대하여)'
        )
        
        if re_jo_reference.match(content):
            return None

        m = self.re_special.match(content)
        if m:
            title = m.group(1) or m.group(2)
            marker = f"【{m.group(1)}】" if m.group(1) else f"<{m.group(2)}>"
            return {'type': 'special', 'level': -1, 'number': None, 'marker': marker, 'title': title, 'body': '', 'rest': content}
        
        m = self.re_pyeon.match(content)
        if m:
            return {'type': '편', 'level': LEVEL_PYEON, 'number': int(m.group(1)), 'branch': None, 'marker': f"제{m.group(1)}편", 'title': m.group(2).strip() or content, 'body': '', 'rest': ''}
        
        m = self.re_jang_branch.match(content)
        if m:
            return {'type': '장', 'level': LEVEL_JANG, 'number': int(m.group(1)), 'branch': int(m.group(2)), 'marker': f"제{m.group(1)}장의{m.group(2)}", 'title': m.group(3).strip() or content, 'body': '', 'rest': ''}
        
        m = self.re_jang.match(content)
        if m:
            return {'type': '장', 'level': LEVEL_JANG, 'number': int(m.group(1)), 'branch': None, 'marker': f"제{m.group(1)}장", 'title': m.group(2).strip() or content, 'body': '', 'rest': ''}
        
        m = self.re_jeol.match(content)
        if m:
            return {'type': '절', 'level': LEVEL_JEOL, 'number': int(m.group(1)), 'branch': None, 'marker': f"제{m.group(1)}절", 'title': m.group(2).strip() or content, 'body': '', 'rest': ''}
        
        m = self.re_gwan.match(content)
        if m:
            return {'type': '관', 'level': LEVEL_GWAN, 'number': int(m.group(1)), 'branch': None, 'marker': f"제{m.group(1)}관", 'title': m.group(2).strip() or content, 'body': '', 'rest': ''}
        
        m = self.re_jo_branch_bracket.match(content)
        if m:
            return {'type': '조', 'level': LEVEL_JO, 'number': int(m.group(1)), 'branch': int(m.group(2)), 'marker': f"제{m.group(1)}조의{m.group(2)}", 'title': m.group(3).strip(), 'body': m.group(4).strip() if m.group(4) else '', 'rest': content}
        
        m = self.re_jo_branch.match(content)
        if m:
            return {'type': '조', 'level': LEVEL_JO, 'number': int(m.group(1)), 'branch': int(m.group(2)), 'marker': f"제{m.group(1)}조의{m.group(2)}", 'title': m.group(3).strip() if m.group(3) else '', 'body': m.group(4).strip() if m.group(4) else '', 'rest': content}
        
        m = self.re_jo_bracket.match(content)
        if m:
            return {'type': '조', 'level': LEVEL_JO, 'number': int(m.group(1)), 'branch': None, 'marker': f"제{m.group(1)}조", 'title': m.group(2).strip(), 'body': m.group(3).strip() if m.group(3) else '', 'rest': content}
        
        m = self.re_jo.match(content)
        if m:
            return {'type': '조', 'level': LEVEL_JO, 'number': int(m.group(1)), 'branch': None, 'marker': f"제{m.group(1)}조", 'title': m.group(2).strip() if m.group(2) else '', 'body': m.group(3).strip() if m.group(3) else '', 'rest': content}
        
        m = self.re_jo_no_paren.match(content)
        if m:
            return {'type': '조', 'level': LEVEL_JO, 'number': int(m.group(1)), 'branch': None, 'marker': f"제{m.group(1)}조", 'title': m.group(2).strip()[:20] if m.group(2) else '', 'body': '', 'rest': content}
        
        m = self.re_hang.match(content)
        if m:
            return {'type': '항', 'level': LEVEL_HANG, 'number': CIRCLED_NUMBERS.get(m.group(1), 1), 'branch': None, 'marker': m.group(1), 'title': m.group(2)[:50] if m.group(2) else '', 'body': '', 'rest': m.group(2)}
        
        m = self.re_ho.match(content)
        if m:
            return {'type': '호', 'level': LEVEL_HO, 'number': int(m.group(1)), 'branch': None, 'marker': f"{m.group(1)}.", 'title': m.group(2)[:50], 'body': '', 'rest': m.group(2)}
        
        m = self.re_mok.match(content)
        if m:
            return {'type': '목', 'level': LEVEL_MOK, 'number': MOK_CHARS.index(m.group(1)) + 1, 'branch': None, 'marker': f"{m.group(1)}.", 'title': m.group(2)[:50], 'body': '', 'rest': m.group(2)}
        
        m = self.re_semok.match(content)
        if m:
            return {'type': '세목', 'level': LEVEL_SEMOK, 'number': ROMAN_NUMERALS.get(m.group(1).lower(), 1), 'branch': None, 'marker': f"({m.group(1)})", 'title': m.group(2)[:50], 'body': '', 'rest': m.group(2)}
        
        m = self.re_dash.match(content)
        if m:
            return {'type': '대시', 'level': LEVEL_DASH, 'number': None, 'branch': None, 'marker': '-', 'title': m.group(1)[:50], 'body': '', 'rest': m.group(1)}
        
        return None


# =============================================================================
# 메인 파서
# =============================================================================

class DocumentParser:
    """보험약관/법률 문서 파서 v4 (박스 감지 지원)"""
    
    def __init__(self, input_dir: str, doc_type: str = DOC_TYPE_INSURANCE):
        self.input_dir = Path(input_dir)
        self.doc_type = doc_type
        self.blocks: List[Dict] = []
        self.root = HierarchyNode(id="root", type="document", level=-1, title="문서")
        self.matcher = PatternMatcher(doc_type)
        self.ref_extractor: Optional[ReferenceExtractor] = None
        self.stats = defaultdict(int)
        self.all_references: List[Reference] = []
        self.external_laws: set = set()
        self.current_doc_name: str = ""
    
    def load_blocks(self) -> None:
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
        
        box_blocks = sum(1 for b in self.blocks if b.get('inside_box'))
        print(f"총 블록 수: {len(self.blocks)}개 (박스 내부: {box_blocks}개)\n")
    
    def parse(self) -> HierarchyNode:
        self.load_blocks()
        
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
        
        self.ref_extractor = ReferenceExtractor(
            external_laws=self.external_laws,
            current_doc_name=self.current_doc_name
        )
        
        print("\n" + "=" * 80)
        print("섹션 감지")
        print("=" * 80)
        sections = self._detect_sections()
        print(f"섹션 수: {len(sections)}개\n")
        
        print("=" * 80)
        print("계층 파싱")
        print("=" * 80)
        
        for section_info in sections:
            section_node = self._parse_section(section_info)
            self.root.children.append(section_node)
            jo_count = len(section_node.get_all_by_type('조'))
            ref_count = len(section_node.get_all_references())
            print(f"  {section_info['name'][:30]}: 조 {jo_count}개, 참조 {ref_count}개")
        
        print("\n" + "=" * 80)
        print("참조 해석")
        print("=" * 80)
        self._resolve_references()
        
        self._print_stats()
        return self.root
    
    def _collect_external_laws(self) -> set:
        laws = set()
        for block in self.blocks:
            content = block.get('block_content', '').strip()
            match = re.match(r'^【법규\d*】\s*(.+)$', content)
            if match:
                laws.add(match.group(1).strip())
                continue
            if re.match(r'^[가-힣]+(?:법|령|규정|규칙)\s*$', content):
                laws.add(content.strip())
        return laws
    
    def _detect_sections(self) -> List[Dict]:
        sections = []
        
        section_patterns = [
            re.compile(r'^[가-힣A-Za-z0-9\s\(\),，및]+\s*(보통약관|특별약관|추가약관)\s*$'),
            re.compile(r'^[가-힣A-Za-z0-9\s,，및]+\s*(보통약관|특별약관|추가약관)\s*[\(（][^)）]*[\)）]\s*$'),
            re.compile(r'^[가-힣]+(?:법|령|규정|규칙)\s*$'),
            re.compile(r'^【법규\d*】'),
            re.compile(r'^주요\s*(민원|분쟁|사례|유의)'),
            re.compile(r'^(민원|분쟁)\s*(사례|안내|처리)'),
            re.compile(r'^유의\s*사항'),
            re.compile(r'민원.*분쟁.*유의', re.IGNORECASE),
            re.compile(r'분쟁.*사례.*유의', re.IGNORECASE),
            re.compile(r'^[가-힣A-Za-z\s]+\s*/\s*[가-힣A-Za-z\s]+'),
        ]
        
        not_section_patterns = [
            re.compile(r'^이\s+'), re.compile(r'^본\s+'), re.compile(r'^회사는\s+'),
            re.compile(r'^보통약관에서\s+'), re.compile(r'^상기'),
            re.compile(r'합니다\.?\s*$'), re.compile(r'않습니다\.?\s*$'),
            re.compile(r'됩니다\.?\s*$'), re.compile(r'입니다\.?\s*$'),
        ]
        
        for i, block in enumerate(self.blocks):
            content = block.get('block_content', '').strip()
            if not content or len(content) > 80:
                continue
            if re.match(r'^[가나다라마바사아자차카타파하]\.\s', content):
                continue
            if re.match(r'^\d+\.\s', content):
                continue
            if re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]', content):
                continue
            if re.match(r'^제\s*\d+\s*조', content):
                continue
            if any(p.search(content) for p in not_section_patterns):
                continue
            if any(p.match(content) or p.search(content) for p in section_patterns):
                sections.append({'name': content.strip(), 'index': i})
        
        if not sections:
            return [{'name': '본문', 'index': 0, 'end': len(self.blocks)}]
        
        for i in range(len(sections)):
            sections[i]['end'] = sections[i+1]['index'] if i+1 < len(sections) else len(self.blocks)
        
        return sections
    
    def _parse_section(self, section_info: Dict) -> HierarchyNode:
        """섹션 내부 파싱 (박스 감지 지원)"""
        section_node = HierarchyNode(
            id=section_info['name'], type='section',
            level=LEVEL_SECTION, title=section_info['name']
        )
        
        blocks = self.blocks[section_info['index']:section_info['end']]
        stack: Dict[int, HierarchyNode] = {LEVEL_SECTION: section_node}
        last_numbers: Dict[int, int] = {lvl: 0 for lvl in range(LEVEL_PYEON, LEVEL_DASH + 1)}
        
        in_special_block = False
        current_special_node: Optional[HierarchyNode] = None
        current_special_box_id: Optional[int] = None
        current_jo_number: Optional[int] = None
        
        for i, block in enumerate(blocks):
            content = block.get('block_content', '').strip()
            page = block.get('page_index', 0)
            inside_box = block.get('inside_box', False)
            box_id = block.get('box_id')
            
            if not content:
                continue
            
            # 글로벌 특수 블록 체크
            global_special = self._check_global_special(content)
            if global_special:
                in_special_block = True
                current_special_box_id = None
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
            
            # 특수 블록 모드 처리
            if in_special_block and current_special_node:
                # 글로벌 special
                if current_special_node.metadata.get('global'):
                    new_global = self._check_global_special(content)
                    if re.match(r'^제\s*\d+\s*(조|관|장|절|편)', content) or new_global:
                        in_special_block = False
                        current_special_node = None
                        current_special_box_id = None
                    else:
                        current_special_node.content += "\n" + content
                        continue
                # 인라인 special
                else:
                    # 박스 기반 special
                    if current_special_box_id is not None:
                        if inside_box and box_id == current_special_box_id:
                            current_special_node.content += "\n" + content
                            continue
                        else:
                            in_special_block = False
                            current_special_node = None
                            current_special_box_id = None
                    # 박스 없는 special
                    else:
                        if self.matcher.match(content):
                            in_special_block = False
                            current_special_node = None
                            current_special_box_id = None
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
                
                # 인라인 특수 블록 시작
                if node_type == 'special':
                    special_node = HierarchyNode(
                        id=f"{section_info['name']}.{match_info['marker']}",
                        type='special', level=-1,
                        marker=match_info['marker'],
                        title=match_info['title'],
                        content=content, page=page,
                        metadata={
                            'special_type': match_info['title'],
                            'inline': True,
                            'inside_box': inside_box,
                            'box_id': box_id
                        }
                    )
                    
                    parent = self._find_parent_for_special(stack)
                    parent.children.append(special_node)
                    
                    current_special_node = special_node
                    in_special_block = True
                    current_special_box_id = box_id if inside_box else None
                    
                    self.stats['special'] += 1
                    continue
                
                # 일반 계층 노드
                self._manage_context(stack, last_numbers, node_type, node_level, node_number, page)
                
                parent = self._find_parent(stack, node_level)
                node_content = content
                
                if node_type == '조' and match_info.get('body'):
                    jo_body = match_info['body']
                    node_content = content.replace(jo_body, '').strip()
                
                new_node = HierarchyNode(
                    id=f"{parent.id}.{match_info['marker']}",
                    type=node_type, level=node_level,
                    number=node_number, branch=node_branch,
                    marker=match_info['marker'],
                    title=match_info['title'],
                    content=node_content, page=page
                )
                
                refs = self.ref_extractor.extract(content, new_node.id, current_jo_number)
                new_node.references = refs
                self.all_references.extend(refs)
                
                parent.children.append(new_node)
                stack[node_level] = new_node
                
                if node_level in last_numbers and node_number:
                    last_numbers[node_level] = node_number
                
                self.stats[node_type] += 1
                
                if node_type == '조':
                    current_jo_number = node_number
                    stack[LEVEL_HANG] = None
                    
                    jo_body = match_info.get('body', '').strip()
                    if jo_body:
                        auto_hang = HierarchyNode(
                            id=f"{new_node.id}.①",
                            type='항', level=LEVEL_HANG,
                            number=1, marker='①',
                            title=jo_body[:30], content=jo_body, page=page,
                            metadata={'auto_generated': True}
                        )
                        hang_refs = self.ref_extractor.extract(jo_body, auto_hang.id, current_jo_number)
                        auto_hang.references = hang_refs
                        self.all_references.extend(hang_refs)
                        
                        new_node.children.append(auto_hang)
                        stack[LEVEL_HANG] = auto_hang
                        self.stats['항(자동)'] += 1
            
            else:
                # 패턴이 없는 블록 (special 블록 모드 처리에서 이미 처리됨)
                # 하지만 안전장치로 한 번 더 체크
                if in_special_block and current_special_node:
                    # 박스 기반 special이면 박스 체크 필요
                    if current_special_box_id is not None:
                        if inside_box and box_id == current_special_box_id:
                            current_special_node.content += "\n" + content
                            continue
                        else:
                            # 박스 밖으로 나왔지만 패턴 매칭에서 처리되지 않은 경우
                            in_special_block = False
                            current_special_node = None
                            current_special_box_id = None
                    else:
                        # 박스 없는 special (기존 로직)
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
                            refs = self.ref_extractor.extract(content, recent.id, current_jo_number)
                            recent.references.extend(refs)
                            self.all_references.extend(refs)
                else:
                    recent = self._find_most_recent(stack)
                    if recent and recent.type != 'section':
                        recent.content += "\n" + content
        
        return section_node
    
    def _check_global_special(self, content: str) -> Optional[Dict]:
        if re.match(r'^[\[【]별표\s*(\d*)[\]】]', content):
            m = re.match(r'^[\[【]별표\s*(\d*)[\]】]', content)
            return {'type': 'appendix', 'marker': f"[별표{m.group(1)}]", 'title': content[:50]}
        if re.match(r'^※\s*용어', content):
            return {'type': 'glossary', 'marker': '※용어정의', 'title': content[:50]}
        if re.match(r'^비고\s*$', content) or re.match(r'^비고\s*\d', content):
            return {'type': 'note', 'marker': '비고', 'title': content[:50]}
        if '약관에서 인용된 법' in content or re.match(r'^[\[【]법규', content):
            return {'type': 'law_reference', 'marker': '법규정', 'title': content[:50]}
        return None
    
    def _manage_context(self, stack: Dict, last_numbers: Dict, node_type: str, node_level: int, node_number: int, page: int):
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
                    id=f"{jo_node.id}.①", type='항', level=LEVEL_HANG,
                    number=1, marker='①', title='(자동생성)', content='', page=page,
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
        all_jos = {}
        for section in self.root.children:
            for jo in section.get_all_by_type('조'):
                key = (section.id, jo.number, jo.branch)
                all_jos[key] = jo.id
        
        resolved_count = 0
        for ref in self.all_references:
            if ref.ref_type == 'internal' and ref.target_jo:
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
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.root.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"\n트리 저장: {output_file}")
        
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
        id=data['id'], type=data['type'], level=data.get('level', 0),
        number=data.get('number'), branch=data.get('branch'),
        marker=data.get('marker', ''), title=data.get('title', ''),
        content=data.get('content', ''), page=data.get('page', 0),
        metadata=data.get('metadata', {})
    )
    for ref_data in data.get('references', []):
        ref = Reference(
            ref_type=ref_data['ref_type'], source_id=ref_data['source_id'],
            target_law=ref_data.get('target_law'), target_jo=ref_data.get('target_jo'),
            target_jo_branch=ref_data.get('target_jo_branch'),
            target_hang=ref_data.get('target_hang'), target_ho=ref_data.get('target_ho'),
            target_mok=ref_data.get('target_mok'), raw_text=ref_data.get('raw_text', ''),
            resolved_id=ref_data.get('resolved_id')
        )
        node.references.append(ref)
    for child in data.get('children', []):
        node.children.append(_dict_to_node(child))
    return node


def process_hierarchy_parsing(
    parsing_results_dir: Path,
    output_file: Path,
    doc_type: str = DOC_TYPE_INSURANCE
) -> tuple[Path, Path]:
    parser = DocumentParser(str(parsing_results_dir), doc_type=doc_type)
    root = parser.parse()
    main_file, ref_file = parser.save(str(output_file))
    return main_file, ref_file


def main():
    script_dir = Path(__file__).parent.parent
    input_dir = script_dir / "output" / "test_full" / "layout_parsing_output" / "parsing_results"
    output_file = script_dir / "output" / "test_full" / "parsed_hierarchy_v4.json"
    
    parser = DocumentParser(str(input_dir), doc_type=DOC_TYPE_INSURANCE)
    root = parser.parse()
    parser.save(str(output_file))
    
    print("\n" + "=" * 80)
    print("트리 구조 (깊이 3)")
    print("=" * 80)
    root.print_tree(max_depth=3)


if __name__ == "__main__":
    main()