"""
보험약관 계층 구조 파싱 시스템 v3

실제 보험약관 계층 구조:
조 → 항(①②③ 또는 암묵적) → 호(1. 2. 3.) → 목(가. 나. 다.) → 세목((ⅰ)(ⅱ)) → 대시(-)

예시:
제2조(용어의 정의)
├── (암묵적 항) "이 계약에서..."
│   ├── 1. 계약 관련 용어           [호]
│   │   ├── 가. 계약자              [목]
│   │   ├── 나. 피보험자            [목]
│   │   └── 라. 보험의 목적         [목]
│   │       ├── (ⅰ) 주택으로만...   [세목]
│   │       │   ├── - 단독주택      [대시]
│   │       │   └── - 주택의 부속   [대시]
│   │       └── (ⅱ) 주택병용...     [세목]
│   └── 2. 보상 관련 용어           [호]
│       ├── 가. 보험가입금액        [목]
│       └── 나. 보험가액            [목]
└── 【설명】                        [특수블록]
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

# 섹션 키워드
SECTION_KEYWORDS = ["보통약관", "추가약관", "특별약관", "법률", "【법규】"]

# 계층 레벨 정의
# 
# [보험약관 구조]          [법률 구조]
# 약관 (SECTION)          법률 (SECTION)
#  └─ 관                   └─ 편 (PYEON)
#      └─ 조                   └─ 장 (JANG)
#          └─ 항                   └─ 절 (JEOL)
#              └─ 호                   └─ 관 (GWAN)
#                  └─ 목                   └─ 조
#                      └─ 세목                 └─ 항
#                          └─ 대시                 └─ 호
#                                                      └─ 목
#                                                          └─ 세목

LEVEL_SECTION = 0   # 약관 / 법률

# 상위 구조 (법률용)
LEVEL_PYEON = 1     # 편 (법률)
LEVEL_JANG = 2      # 장 (법률)
LEVEL_JEOL = 3      # 절 (법률)

# 공통 구조
LEVEL_GWAN = 4      # 관 (약관: 최상위 / 법률: 절 하위)
LEVEL_JO = 5        # 조
LEVEL_HANG = 6      # 항 (①②③ 또는 암묵적)
LEVEL_HO = 7        # 호 (1. 2. 3.)
LEVEL_MOK = 8       # 목 (가. 나. 다.)
LEVEL_SEMOK = 9     # 세목 ((ⅰ) (ⅱ))
LEVEL_DASH = 10     # 대시 (-)

# 문서 타입
DOC_TYPE_INSURANCE = 'insurance'  # 보험약관
DOC_TYPE_LAW = 'law'              # 법률


# =============================================================================
# 데이터 클래스
# =============================================================================

@dataclass
class HierarchyNode:
    """계층 구조 노드"""
    id: str
    type: str                   # section, 관, 조, 항, 호, 목, 세목, 대시, special
    level: int                  # 계층 레벨
    number: Optional[int] = None
    marker: str = ""            # 원본 마커 (①, 1., 가., (ⅰ), -)
    title: str = ""
    content: str = ""
    page: int = 0
    children: List['HierarchyNode'] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'type': self.type,
            'level': self.level,
            'number': self.number,
            'marker': self.marker,
            'title': self.title,
            'content': self.content,
            'page': self.page,
            'children': [c.to_dict() for c in self.children],
            'metadata': self.metadata
        }
    
    def find(self, path: str) -> Optional['HierarchyNode']:
        """
        경로로 노드 찾기
        예: "제2조" → 제2조
            "제2조.1" → 제2조의 1호
            "제2조.1.가" → 제2조 1호의 가목
            "제2조.1.가.(ⅰ)" → 세목까지
        """
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
        if re.match(r'제(\d+)편', query):
            num = int(re.match(r'제(\d+)편', query).group(1))
            return node.type == '편' and node.number == num
        
        # 제N장
        if re.match(r'제(\d+)장', query):
            num = int(re.match(r'제(\d+)장', query).group(1))
            return node.type == '장' and node.number == num
        
        # 제N절
        if re.match(r'제(\d+)절', query):
            num = int(re.match(r'제(\d+)절', query).group(1))
            return node.type == '절' and node.number == num
        
        # 제N조
        if re.match(r'제(\d+)조', query):
            num = int(re.match(r'제(\d+)조', query).group(1))
            return node.type == '조' and node.number == num
        
        # 제N관
        if re.match(r'제(\d+)관', query):
            num = int(re.match(r'제(\d+)관', query).group(1))
            return node.type == '관' and node.number == num
        
        # 원문자 항 (①②)
        if query in CIRCLED_NUMBERS:
            return node.type == '항' and node.number == CIRCLED_NUMBERS[query]
        
        # 숫자 호 (1, 2, 3)
        if query.isdigit():
            return node.type == '호' and node.number == int(query)
        
        # 한글 목 (가, 나, 다)
        if query in MOK_CHARS:
            return node.type == '목' and node.number == MOK_CHARS.index(query) + 1
        
        # 로마숫자 세목
        query_lower = query.strip('()').lower()
        if query_lower in ROMAN_NUMERALS:
            return node.type == '세목' and node.number == ROMAN_NUMERALS[query_lower]
        
        return False
    
    def print_tree(self, indent: int = 0, max_depth: int = 99) -> None:
        """트리 출력"""
        if indent > max_depth:
            return
        
        prefix = "│   " * indent
        marker_str = f"[{self.marker}]" if self.marker else f"[{self.type}]"
        title_short = self.title[:35] + "..." if len(self.title) > 35 else self.title
        
        print(f"{prefix}├── {marker_str} {title_short}")
        
        for child in self.children:
            child.print_tree(indent + 1, max_depth)
    
    def get_all_by_type(self, node_type: str) -> List['HierarchyNode']:
        """특정 타입의 모든 노드 반환"""
        result = []
        if self.type == node_type:
            result.append(self)
        for child in self.children:
            result.extend(child.get_all_by_type(node_type))
        return result
    
    def get_full_text(self) -> str:
        """전체 텍스트 반환"""
        texts = [self.content] if self.content else []
        for child in self.children:
            texts.append(child.get_full_text())
        return "\n".join(filter(None, texts))


# =============================================================================
# 패턴 인식기
# =============================================================================

class PatternMatcher:
    """계층 패턴 매칭"""
    
    def __init__(self, doc_type: str = DOC_TYPE_INSURANCE):
        self.doc_type = doc_type
        
        # 편: 제N편 (법률)
        self.re_pyeon = re.compile(r'^제\s*(\d+)\s*편\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        
        # 장: 제N장 (법률)
        self.re_jang = re.compile(r'^제\s*(\d+)\s*장\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        
        # 절: 제N절 (법률)
        self.re_jeol = re.compile(r'^제\s*(\d+)\s*절\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        
        # 관: 제N관 (보험약관/법률 공통)
        self.re_gwan = re.compile(r'^제\s*(\d+)\s*관\s*[(\[]?([^)\]]*)[)\]]?\s*$')
        
        # 조: 제N조[제목(부제목)] 또는 제N조(제목) 형태
        # 대괄호 버전: 제N조[제목] - 대괄호 안에 소괄호 허용
        self.re_jo_bracket = re.compile(r'^제\s*(\d+)\s*조\s*\[([^\]]*)\](.*)', re.DOTALL)
        
        # 소괄호 버전: 제N조(제목)본문
        # 그룹1: 조번호, 그룹2: 제목(괄호 안), 그룹3: 본문(괄호 뒤)
        self.re_jo = re.compile(r'^제\s*(\d+)\s*조\s*[(\[（]([^)\]）]*)[)\]）](.*)', re.DOTALL)
        
        # 조: 제N조 제목 (괄호 없이)
        self.re_jo_no_paren = re.compile(r'^제\s*(\d+)\s*조\s+(.*)$')
        
        # 조의2, 조의3 등 (가지조항) - 대괄호/소괄호 모두 지원
        self.re_jo_branch_bracket = re.compile(r'^제\s*(\d+)\s*조의\s*(\d+)\s*\[([^\]]*)\](.*)', re.DOTALL)
        self.re_jo_branch = re.compile(r'^제\s*(\d+)\s*조의\s*(\d+)\s*[(\[（]([^)\]）]*)[)\]）]?(.*)', re.DOTALL)
        
        # 항: ①②③ (문장 시작)
        self.re_hang = re.compile(r'^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*(.*)$')
        
        # 호: 1. 2. 3. (문장 시작, 뒤에 내용)
        self.re_ho = re.compile(r'^(\d+)\.\s+(.+)$')
        
        # 목: 가. 나. 다. (문장 시작)
        self.re_mok = re.compile(r'^([가나다라마바사아자차카타파하])\.\s+(.+)$')
        
        # 세목: (ⅰ) (ⅱ) 또는 (i) (ii)
        self.re_semok = re.compile(r'^\s*[\(（]\s*([ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ]|i{1,3}|iv|vi{0,3}|ix|x)\s*[\)）]\s*(.+)$', re.IGNORECASE)
        
        # 대시: - 항목
        self.re_dash = re.compile(r'^[-－‐–—]\s*(.+)$')
        
        # 특수 블록: 【】
        self.re_special = re.compile(r'^【([^】]+)】')
    
    def match(self, content: str) -> Optional[Dict]:
        """
        콘텐츠 패턴 매칭
        Returns: {'type': str, 'level': int, 'number': int, 'marker': str, 'title': str, 'rest': str}
        """
        content = content.strip()
        if not content:
            return None
        
        # 특수 블록
        special_match = self.re_special.match(content)
        if special_match:
            return {
                'type': 'special',
                'level': -1,
                'number': None,
                'marker': f"【{special_match.group(1)}】",
                'title': special_match.group(1),
                'rest': content
            }
        
        # 편 (법률)
        pyeon_match = self.re_pyeon.match(content)
        if pyeon_match:
            return {
                'type': '편',
                'level': LEVEL_PYEON,
                'number': int(pyeon_match.group(1)),
                'marker': f"제{pyeon_match.group(1)}편",
                'title': pyeon_match.group(2).strip() or content,
                'rest': ''
            }
        
        # 장 (법률)
        jang_match = self.re_jang.match(content)
        if jang_match:
            return {
                'type': '장',
                'level': LEVEL_JANG,
                'number': int(jang_match.group(1)),
                'marker': f"제{jang_match.group(1)}장",
                'title': jang_match.group(2).strip() or content,
                'rest': ''
            }
        
        # 절 (법률)
        jeol_match = self.re_jeol.match(content)
        if jeol_match:
            return {
                'type': '절',
                'level': LEVEL_JEOL,
                'number': int(jeol_match.group(1)),
                'marker': f"제{jeol_match.group(1)}절",
                'title': jeol_match.group(2).strip() or content,
                'rest': ''
            }
        
        # 관
        gwan_match = self.re_gwan.match(content)
        if gwan_match:
            return {
                'type': '관',
                'level': LEVEL_GWAN,
                'number': int(gwan_match.group(1)),
                'marker': f"제{gwan_match.group(1)}관",
                'title': gwan_match.group(2).strip() or content,
                'rest': ''
            }
        
        # 조의N (가지조항) - 대괄호 버전 먼저
        jo_branch_bracket_match = self.re_jo_branch_bracket.match(content)
        if jo_branch_bracket_match:
            main_num = int(jo_branch_bracket_match.group(1))
            branch_num = int(jo_branch_bracket_match.group(2))
            title = jo_branch_bracket_match.group(3).strip() if jo_branch_bracket_match.group(3) else ""
            body = jo_branch_bracket_match.group(4).strip() if jo_branch_bracket_match.group(4) else ""
            return {
                'type': '조',
                'level': LEVEL_JO,
                'number': main_num,
                'branch': branch_num,
                'marker': f"제{main_num}조의{branch_num}",
                'title': title,
                'body': body,
                'rest': content
            }
        
        # 조의N (가지조항) - 소괄호 버전
        jo_branch_match = self.re_jo_branch.match(content)
        if jo_branch_match:
            main_num = int(jo_branch_match.group(1))
            branch_num = int(jo_branch_match.group(2))
            title = jo_branch_match.group(3).strip() if jo_branch_match.group(3) else ""
            body = jo_branch_match.group(4).strip() if jo_branch_match.group(4) else ""
            return {
                'type': '조',
                'level': LEVEL_JO,
                'number': main_num,
                'branch': branch_num,
                'marker': f"제{main_num}조의{branch_num}",
                'title': title,
                'body': body,
                'rest': content
            }
        
        # 조 (대괄호 버전): 제N조[제목(부제목)]본문
        # 대괄호 안에 소괄호가 있어도 됨
        jo_bracket_match = self.re_jo_bracket.match(content)
        if jo_bracket_match:
            jo_num = int(jo_bracket_match.group(1))
            title = jo_bracket_match.group(2).strip() if jo_bracket_match.group(2) else ""
            body = jo_bracket_match.group(3).strip() if jo_bracket_match.group(3) else ""
            return {
                'type': '조',
                'level': LEVEL_JO,
                'number': jo_num,
                'marker': f"제{jo_num}조",
                'title': title,
                'body': body,
                'rest': content
            }
        
        # 조 (소괄호 버전): 제N조(제목)본문
        jo_match = self.re_jo.match(content)
        if jo_match:
            jo_num = int(jo_match.group(1))
            title = jo_match.group(2).strip() if jo_match.group(2) else ""
            body = jo_match.group(3).strip() if jo_match.group(3) else ""
            return {
                'type': '조',
                'level': LEVEL_JO,
                'number': jo_num,
                'marker': f"제{jo_num}조",
                'title': title,
                'body': body,
                'rest': content
            }
        
        # 조 (괄호 없음): 제N조 제목
        jo_no_paren_match = self.re_jo_no_paren.match(content)
        if jo_no_paren_match:
            jo_num = int(jo_no_paren_match.group(1))
            rest = jo_no_paren_match.group(2).strip() if jo_no_paren_match.group(2) else ""
            return {
                'type': '조',
                'level': LEVEL_JO,
                'number': jo_num,
                'marker': f"제{jo_num}조",
                'title': rest[:20] if rest else "",
                'body': '',
                'rest': content
            }
        
        # 항 (원문자)
        hang_match = self.re_hang.match(content)
        if hang_match:
            marker = hang_match.group(1)
            return {
                'type': '항',
                'level': LEVEL_HANG,
                'number': CIRCLED_NUMBERS.get(marker, 1),
                'marker': marker,
                'title': hang_match.group(2)[:50],
                'rest': hang_match.group(2)
            }
        
        # 호 (숫자점)
        ho_match = self.re_ho.match(content)
        if ho_match:
            return {
                'type': '호',
                'level': LEVEL_HO,
                'number': int(ho_match.group(1)),
                'marker': f"{ho_match.group(1)}.",
                'title': ho_match.group(2)[:50],
                'rest': ho_match.group(2)
            }
        
        # 목 (한글점)
        mok_match = self.re_mok.match(content)
        if mok_match:
            char = mok_match.group(1)
            return {
                'type': '목',
                'level': LEVEL_MOK,
                'number': MOK_CHARS.index(char) + 1,
                'marker': f"{char}.",
                'title': mok_match.group(2)[:50],
                'rest': mok_match.group(2)
            }
        
        # 세목 (로마숫자)
        semok_match = self.re_semok.match(content)
        if semok_match:
            roman = semok_match.group(1).lower()
            return {
                'type': '세목',
                'level': LEVEL_SEMOK,
                'number': ROMAN_NUMERALS.get(roman, 1),
                'marker': f"({semok_match.group(1)})",
                'title': semok_match.group(2)[:50],
                'rest': semok_match.group(2)
            }
        
        # 대시
        dash_match = self.re_dash.match(content)
        if dash_match:
            return {
                'type': '대시',
                'level': LEVEL_DASH,
                'number': None,
                'marker': '-',
                'title': dash_match.group(1)[:50],
                'rest': dash_match.group(1)
            }
        
        return None


# =============================================================================
# 메인 파서
# =============================================================================

class InsuranceDocumentParserV3:
    """보험약관/법률 파서 v3"""
    
    def __init__(self, input_dir: str, doc_type: str = DOC_TYPE_INSURANCE):
        self.input_dir = Path(input_dir)
        self.doc_type = doc_type
        self.blocks: List[Dict] = []
        self.root = HierarchyNode(
            id="root", 
            type="document", 
            level=-1,
            title="문서"
        )
        self.matcher = PatternMatcher(doc_type)
        self.stats = defaultdict(int)
    
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
        
        # 섹션 감지
        print("=" * 80)
        print("섹션 감지")
        print("=" * 80)
        sections = self._detect_sections()
        print(f"섹션 수: {len(sections)}개\n")
        
        # 각 섹션 파싱
        print("=" * 80)
        print("계층 파싱")
        print("=" * 80)
        
        for section_info in sections:
            section_node = self._parse_section(section_info)
            self.root.children.append(section_node)
            jo_count = len(section_node.get_all_by_type('조'))
            print(f"  {section_info['name'][:30]}: 조 {jo_count}개")
        
        self._print_stats()
        return self.root
    
    def _detect_sections(self) -> List[Dict]:
        """
        섹션 감지 - 약관/법률 제목 패턴 기반
        
        진짜 섹션 예시:
        - "KB주택화재보험 보통약관"
        - "전기위험 특별약관"
        - "날짜인식오류 보장제외 추가약관"
        - "민법 제1편 총칙"
        
        섹션이 아닌 것:
        - "이 특별약관에 정하지 않은 사항은 보통약관을 따릅니다." (문장)
        - "회사는 보통약관 제3조에 따라..." (문장)
        - "보통약관에서 정한 화재는..." (문장)
        """
        sections = []
        
        # 섹션 제목 패턴 (문장이 아닌 제목 형태)
        section_title_patterns = [
            # "XXX 보통약관", "XXX 특별약관", "XXX 추가약관" (제목 형태)
            re.compile(r'^[가-힣A-Za-z0-9\s\(\)]+\s*(보통약관|특별약관|추가약관)\s*$'),
            
            # "XXX 특별약관(YYY)" 형태
            re.compile(r'^[가-힣A-Za-z0-9\s]+\s*(보통약관|특별약관|추가약관)\s*[\(（][^)）]*[\)）]\s*$'),
            
            # 법률명: "민법", "상법", "보험업법" 등 (단독)
            re.compile(r'^(민법|상법|보험업법|개인정보\s*보호법|전자금융거래법|상법시행령)\s*$'),
            
            # "【법규N】" 형태
            re.compile(r'^【법규\d*】'),
        ]
        
        # 섹션이 아닌 패턴 (문장 형태)
        not_section_patterns = [
            re.compile(r'^이\s+'),           # "이 특별약관에...", "이 계약에서..."
            re.compile(r'^본\s+'),           # "본 추가약관은..."
            re.compile(r'^회사는\s+'),       # "회사는..."
            re.compile(r'^보통약관에서\s+'), # "보통약관에서 정한..."
            re.compile(r'^상기'),            # "상기에도 불구하고..."
            re.compile(r'합니다\.?\s*$'),    # "...합니다." 로 끝나는 문장
            re.compile(r'않습니다\.?\s*$'),  # "...않습니다." 로 끝나는 문장
            re.compile(r'됩니다\.?\s*$'),    # "...됩니다." 로 끝나는 문장
            re.compile(r'입니다\.?\s*$'),    # "...입니다." 로 끝나는 문장
            re.compile(r'바꿉니다\.?\s*$'),  # "...바꿉니다." 로 끝나는 문장
        ]
        
        for i, block in enumerate(self.blocks):
            content = block.get('block_content', '').strip()
            
            # 빈 내용 스킵
            if not content:
                continue
            
            # 너무 긴 내용은 제목이 아님 (보통 제목은 50자 이내)
            if len(content) > 80:
                continue
            
            # 계층 패턴으로 시작하면 섹션이 아님
            if re.match(r'^[가나다라마바사아자차카타파하]\.\s', content):
                continue
            if re.match(r'^\d+\.\s', content):
                continue
            if re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]', content):
                continue
            if re.match(r'^제\s*\d+\s*조', content):  # 제N조는 섹션이 아님
                continue
            
            # 문장 패턴이면 섹션이 아님
            is_sentence = False
            for pattern in not_section_patterns:
                if pattern.search(content):
                    is_sentence = True
                    break
            if is_sentence:
                continue
            
            # 섹션 제목 패턴 체크
            is_section = False
            for pattern in section_title_patterns:
                if pattern.match(content):
                    is_section = True
                    break
            
            if is_section:
                sections.append({
                    'name': content.strip(),
                    'index': i
                })
        
        # 섹션이 없으면 전체를 하나로
        if not sections:
            return [{'name': '본문', 'index': 0, 'end': len(self.blocks)}]
        
        # 범위 설정
        for i in range(len(sections)):
            sections[i]['end'] = sections[i+1]['index'] if i+1 < len(sections) else len(self.blocks)
        
        return sections
    
    def _parse_section(self, section_info: Dict) -> HierarchyNode:
        """섹션 내부 파싱 - 페이지 넘김에도 컨텍스트 유지"""
        section_node = HierarchyNode(
            id=section_info['name'],
            type='section',
            level=LEVEL_SECTION,
            title=section_info['name']
        )
        
        start = section_info['index']
        end = section_info['end']
        blocks = self.blocks[start:end]
        
        # 현재 컨텍스트 스택 - 각 레벨별 현재 노드
        stack: Dict[int, HierarchyNode] = {
            LEVEL_SECTION: section_node
        }
        
        # 마지막으로 파싱된 각 레벨의 번호 (순서 검증용)
        last_numbers: Dict[int, int] = {
            LEVEL_PYEON: 0,
            LEVEL_JANG: 0,
            LEVEL_JEOL: 0,
            LEVEL_GWAN: 0,
            LEVEL_JO: 0,
            LEVEL_HANG: 0,
            LEVEL_HO: 0,
            LEVEL_MOK: 0,
            LEVEL_SEMOK: 0
        }
        
        # 특수 블록 모드 (별표, 용어집 등 진입 시)
        in_special_block = False
        current_special_node: Optional[HierarchyNode] = None
        
        for i, block in enumerate(blocks):
            content = block.get('block_content', '').strip()
            page = block.get('page_index', 0)
            
            if not content:
                continue
            
            # ================================================================
            # 1. 글로벌 특수 블록 체크 (별표, 용어집 등) - 컨텍스트 리셋
            # ================================================================
            global_special = self._check_global_special_block(content)
            if global_special:
                # 조/항/호 컨텍스트 완전 리셋
                in_special_block = True
                self._reset_stack_below(stack, LEVEL_SECTION)
                last_numbers = {k: 0 for k in last_numbers}
                
                current_special_node = HierarchyNode(
                    id=f"{section_info['name']}.{global_special['marker']}",
                    type='special',
                    level=-1,
                    marker=global_special['marker'],
                    title=global_special['title'],
                    content=content,
                    page=page,
                    metadata={'special_type': global_special['type'], 'global': True}
                )
                section_node.children.append(current_special_node)
                self.stats['special'] += 1
                continue
            
            # ================================================================
            # 2. 특수 블록 모드에서 표/비고 등 처리
            # ================================================================
            if in_special_block and current_special_node:
                # 새로운 조/관이 나오면 특수 블록 모드 종료
                if re.match(r'^제\s*\d+\s*(조|관|장|절|편)', content):
                    in_special_block = False
                    current_special_node = None
                    # 아래로 계속 진행하여 정상 파싱
                else:
                    # 특수 블록에 내용 추가
                    current_special_node.content += "\n" + content
                    continue
            
            # ================================================================
            # 3. 패턴 매칭
            # ================================================================
            match_info = self.matcher.match(content)
            
            if match_info:
                node_type = match_info['type']
                node_level = match_info['level']
                node_number = match_info['number']
                
                # ============================================================
                # 3-1. 인라인 특수 블록 (【설명】, 【공제계약】 등)
                # ============================================================
                if node_type == 'special':
                    special_node = HierarchyNode(
                        id=f"{section_info['name']}.{match_info['marker']}",
                        type='special',
                        level=-1,
                        marker=match_info['marker'],
                        title=match_info['title'],
                        content=content,
                        page=page,
                        metadata={'special_type': match_info['title'], 'inline': True}
                    )
                    
                    # 현재 컨텍스트의 가장 깊은 노드의 **sibling**으로 추가
                    # (children이 아님!)
                    parent = self._find_parent_for_special(stack)
                    parent.children.append(special_node)
                    
                    # 이 특수 블록을 현재 특수 블록으로 설정 (다음 텍스트가 여기에 추가됨)
                    current_special_node = special_node
                    in_special_block = True  # 인라인 특수 블록 모드
                    
                    self.stats['special'] += 1
                    continue
                
                # 인라인 특수 블록 모드 종료 (새 계층 패턴 발견)
                if in_special_block and current_special_node and current_special_node.metadata.get('inline'):
                    in_special_block = False
                    current_special_node = None
                
                # ============================================================
                # 3-2. 순서 검증 및 컨텍스트 결정
                # ============================================================
                
                if node_type == '편':
                    self._reset_stack_below(stack, LEVEL_PYEON)
                    last_numbers = {k: 0 for k in last_numbers}
                    
                elif node_type == '장':
                    self._reset_stack_below(stack, LEVEL_JANG)
                    for lvl in [LEVEL_JEOL, LEVEL_GWAN, LEVEL_JO, LEVEL_HANG, LEVEL_HO, LEVEL_MOK, LEVEL_SEMOK]:
                        if lvl in last_numbers:
                            last_numbers[lvl] = 0
                    
                elif node_type == '절':
                    self._reset_stack_below(stack, LEVEL_JEOL)
                    for lvl in [LEVEL_GWAN, LEVEL_JO, LEVEL_HANG, LEVEL_HO, LEVEL_MOK, LEVEL_SEMOK]:
                        if lvl in last_numbers:
                            last_numbers[lvl] = 0
                
                elif node_type == '관':
                    self._reset_stack_below(stack, LEVEL_GWAN)
                    for lvl in [LEVEL_JO, LEVEL_HANG, LEVEL_HO, LEVEL_MOK, LEVEL_SEMOK]:
                        if lvl in last_numbers:
                            last_numbers[lvl] = 0
                    
                elif node_type == '조':
                    self._reset_stack_below(stack, LEVEL_JO)
                    for lvl in [LEVEL_HANG, LEVEL_HO, LEVEL_MOK, LEVEL_SEMOK]:
                        last_numbers[lvl] = 0
                    
                elif node_type == '항':
                    self._reset_stack_below(stack, LEVEL_HANG)
                    for lvl in [LEVEL_HO, LEVEL_MOK, LEVEL_SEMOK]:
                        last_numbers[lvl] = 0
                        
                elif node_type == '호':
                    if node_number == 1:
                        self._ensure_hang_exists(stack, page)
                        self._reset_stack_below(stack, LEVEL_HO)
                        last_numbers[LEVEL_MOK] = 0
                        last_numbers[LEVEL_SEMOK] = 0
                    elif node_number == last_numbers[LEVEL_HO] + 1:
                        self._reset_stack_below(stack, LEVEL_HO)
                        last_numbers[LEVEL_MOK] = 0
                        last_numbers[LEVEL_SEMOK] = 0
                    else:
                        self._ensure_hang_exists(stack, page)
                        
                elif node_type == '목':
                    if node_number == 1:
                        self._ensure_ho_exists(stack, page, last_numbers)
                        self._reset_stack_below(stack, LEVEL_MOK)
                        last_numbers[LEVEL_SEMOK] = 0
                    elif node_number == last_numbers[LEVEL_MOK] + 1:
                        self._reset_stack_below(stack, LEVEL_MOK)
                        last_numbers[LEVEL_SEMOK] = 0
                        
                elif node_type == '세목':
                    if node_number == 1:
                        self._ensure_mok_exists(stack, page, last_numbers)
                        self._reset_stack_below(stack, LEVEL_SEMOK)
                
                # 항이 필요한데 없으면 자동 생성
                if node_level > LEVEL_HANG and LEVEL_JO in stack and stack[LEVEL_JO]:
                    if LEVEL_HANG not in stack or stack[LEVEL_HANG] is None:
                        self._ensure_hang_exists(stack, page)
                
                # 새 노드 생성
                parent = self._find_parent(stack, node_level)
                
                # 조인 경우 content는 제목까지만 (body는 1항으로 분리)
                node_content = content
                if node_type == '조' and match_info.get('body'):
                    # "제N조(제목)" 까지만 content로
                    jo_body = match_info.get('body', '')
                    if jo_body:
                        node_content = content.replace(jo_body, '').strip()
                
                new_node = HierarchyNode(
                    id=f"{parent.id}.{match_info['marker']}",
                    type=node_type,
                    level=node_level,
                    number=node_number,
                    marker=match_info['marker'],
                    title=match_info['title'],
                    content=node_content,
                    page=page
                )
                
                parent.children.append(new_node)
                stack[node_level] = new_node
                
                if node_level in last_numbers and node_number:
                    last_numbers[node_level] = node_number
                
                self.stats[node_type] += 1
                
                # 조인 경우: body가 있으면 자동으로 1항 생성
                if node_type == '조':
                    stack[LEVEL_HANG] = None
                    
                    # 조 제목 뒤에 본문이 바로 붙어있으면 1항으로 분리
                    jo_body = match_info.get('body', '').strip()
                    if jo_body:
                        auto_hang = HierarchyNode(
                            id=f"{new_node.id}.①",
                            type='항',
                            level=LEVEL_HANG,
                            number=1,
                            marker='①',
                            title=jo_body[:30],
                            content=jo_body,
                            page=page,
                            metadata={'auto_generated': True}
                        )
                        new_node.children.append(auto_hang)
                        stack[LEVEL_HANG] = auto_hang
                        self.stats['항(자동)'] += 1
                
            else:
                # ============================================================
                # 4. 패턴 없는 블록 - 연속 본문
                # ============================================================
                
                # 인라인 특수 블록 모드면 특수 블록에 추가
                if in_special_block and current_special_node:
                    current_special_node.content += "\n" + content
                    continue
                
                # 조가 있으면 항에 추가
                if LEVEL_JO in stack and stack[LEVEL_JO]:
                    jo_node = stack[LEVEL_JO]
                    
                    if LEVEL_HANG not in stack or stack[LEVEL_HANG] is None:
                        auto_hang = HierarchyNode(
                            id=f"{jo_node.id}.①",
                            type='항',
                            level=LEVEL_HANG,
                            number=1,
                            marker='①',
                            title=content[:30],
                            content=content,
                            page=page,
                            metadata={'auto_generated': True}
                        )
                        jo_node.children.append(auto_hang)
                        stack[LEVEL_HANG] = auto_hang
                        self.stats['항(자동)'] += 1
                    else:
                        recent = self._find_most_recent(stack)
                        if recent and recent.type != 'section':
                            recent.content += "\n" + content
                else:
                    recent = self._find_most_recent(stack)
                    if recent and recent.type != 'section':
                        recent.content += "\n" + content
        
        return section_node
    
    def _check_global_special_block(self, content: str) -> Optional[Dict]:
        """
        글로벌 특수 블록 체크 (별표, 용어집 등)
        이 블록들은 조/항 컨텍스트를 리셋함
        """
        # [별표 N] 또는 【별표 N】
        byulpyo_match = re.match(r'^[\[【]별표\s*(\d*)[\]】]', content)
        if byulpyo_match:
            num = byulpyo_match.group(1) or ""
            return {
                'type': 'appendix',
                'marker': f"[별표{num}]",
                'title': content[:50]
            }
        
        # ※ 용어의 정의
        if re.match(r'^※\s*용어', content):
            return {
                'type': 'glossary',
                'marker': '※용어정의',
                'title': content[:50]
            }
        
        # 비고 (별표 뒤에 나오는)
        if re.match(r'^비고\s*$', content) or re.match(r'^비고\s*\d', content):
            return {
                'type': 'note',
                'marker': '비고',
                'title': content[:50]
            }
        
        return None
    
    def _find_parent_for_special(self, stack: Dict[int, HierarchyNode]) -> HierarchyNode:
        """특수 블록의 부모 찾기 (가장 깊은 노드의 부모)"""
        # 가장 깊은 노드의 부모를 찾음 (sibling으로 추가하기 위해)
        deepest_level = max(stack.keys())
        
        # 부모 레벨 찾기
        for lvl in sorted(stack.keys(), reverse=True):
            if lvl < deepest_level and stack[lvl] is not None:
                return stack[lvl]
        
        return stack.get(LEVEL_SECTION, list(stack.values())[0])
    
    def _reset_stack_below(self, stack: Dict[int, HierarchyNode], level: int) -> None:
        """특정 레벨 이하의 스택 초기화"""
        for lvl in list(stack.keys()):
            if lvl > level:
                del stack[lvl]
    
    def _ensure_hang_exists(self, stack: Dict[int, HierarchyNode], page: int) -> None:
        """항이 없으면 자동 생성"""
        if LEVEL_JO in stack and stack[LEVEL_JO]:
            if LEVEL_HANG not in stack or stack[LEVEL_HANG] is None:
                jo_node = stack[LEVEL_JO]
                auto_hang = HierarchyNode(
                    id=f"{jo_node.id}.①",
                    type='항',
                    level=LEVEL_HANG,
                    number=1,
                    marker='①',
                    title='(자동생성)',
                    content='',
                    page=page,
                    metadata={'auto_generated': True}
                )
                jo_node.children.append(auto_hang)
                stack[LEVEL_HANG] = auto_hang
                self.stats['항(자동)'] += 1
    
    def _ensure_ho_exists(self, stack: Dict[int, HierarchyNode], page: int, 
                          last_numbers: Dict[int, int]) -> None:
        """호가 없으면 현재 컨텍스트 확인"""
        # 항이 있어야 호를 넣을 수 있음
        self._ensure_hang_exists(stack, page)
    
    def _ensure_mok_exists(self, stack: Dict[int, HierarchyNode], page: int,
                           last_numbers: Dict[int, int]) -> None:
        """목이 없으면 현재 컨텍스트 확인"""
        # 호가 있어야 목을 넣을 수 있음
        self._ensure_ho_exists(stack, page, last_numbers)
    
    def _find_parent(self, stack: Dict[int, HierarchyNode], child_level: int) -> HierarchyNode:
        """자식 레벨에 맞는 부모 찾기"""
        # child_level보다 작은 레벨 중 가장 큰 것
        for lvl in sorted(stack.keys(), reverse=True):
            if lvl < child_level and stack[lvl] is not None:
                return stack[lvl]
        
        # 못 찾으면 섹션 반환
        return stack.get(LEVEL_SECTION, list(stack.values())[0])
    
    def _find_most_recent(self, stack: Dict[int, HierarchyNode]) -> Optional[HierarchyNode]:
        """가장 최근(가장 깊은) 노드 찾기"""
        for lvl in sorted(stack.keys(), reverse=True):
            if stack[lvl] is not None:
                return stack[lvl]
        return None
    
    def _print_stats(self) -> None:
        """통계 출력"""
        print("\n" + "=" * 80)
        print("파싱 통계")
        print("=" * 80)
        
        order = ['편', '장', '절', '관', '조', '항', '항(자동)', '호', '목', '세목', '대시', 'special']
        for key in order:
            if key in self.stats:
                print(f"  {key}: {self.stats[key]}개")
    
    def save(self, output_path: str) -> None:
        """결과 저장"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.root.to_dict(), f, ensure_ascii=False, indent=2)
        
        print(f"\n저장 완료: {output_file}")


# =============================================================================
# 유틸리티
# =============================================================================

def load_document(json_path: str) -> HierarchyNode:
    """저장된 JSON 로드"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return _dict_to_node(data)


def _dict_to_node(data: Dict) -> HierarchyNode:
    """딕셔너리 → 노드 변환"""
    node = HierarchyNode(
        id=data['id'],
        type=data['type'],
        level=data.get('level', 0),
        number=data.get('number'),
        marker=data.get('marker', ''),
        title=data.get('title', ''),
        content=data.get('content', ''),
        page=data.get('page', 0),
        metadata=data.get('metadata', {})
    )
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
) -> Path:
    """
    계층 구조 파싱 실행
    
    Args:
        parsing_results_dir: parsing_results 디렉토리 경로
        output_file: 출력 JSON 파일 경로
        doc_type: 문서 타입 (DOC_TYPE_INSURANCE 또는 DOC_TYPE_LAW)
    
    Returns:
        출력 파일 경로
    """
    parser = InsuranceDocumentParserV3(str(parsing_results_dir), doc_type=doc_type)
    root = parser.parse()
    parser.save(str(output_file))
    return output_file


def example_usage():
    """
    사용 예시
    
    # 로드
    root = load_document("parsed_hierarchy_v3.json")
    
    # 트리 출력
    root.print_tree(max_depth=3)
    
    # 섹션 접근
    section = root.children[0]  # 보통약관
    
    # 조 검색
    jo2 = section.find("제2조")
    
    # 깊은 경로 검색
    # 제2조 → 1호 → 가목
    target = section.find("제2조.1.가")
    
    # 제2조 → 1호 → 라목 → (ⅰ) 세목
    target2 = section.find("제2조.1.라.(ⅰ)")
    
    # 전체 텍스트
    full = jo2.get_full_text()
    
    # 특정 타입 모두 가져오기
    all_jos = section.get_all_by_type('조')
    all_moks = section.get_all_by_type('목')
    """
    pass

