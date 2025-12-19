"""
조항호목 계층 구조 확인 스크립트
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
import sys

LEVEL_SECTION = 0
LEVEL_JO = 5      # 조
LEVEL_HANG = 6    # 항
LEVEL_HO = 7      # 호
LEVEL_MOK = 8     # 목


def find_jo(data: Dict, jo_number: Optional[int] = None, jo_title: Optional[str] = None, 
            section_title: Optional[str] = None) -> Optional[Dict]:
    """
    특정 조 찾기
    
    Args:
        data: JSON 데이터
        jo_number: 조 번호 (예: 2)
        jo_title: 조 제목 (예: "제2조")
        section_title: 섹션 제목 (예: "KB주택화재보험 보통약관")
    
    Returns:
        찾은 조 노드 (없으면 None)
    """
    def _find_in_node(node: Dict, target_section: Optional[str] = None) -> Optional[Dict]:
        # 섹션 찾기
        if node.get('level') == LEVEL_SECTION:
            if target_section and target_section not in node.get('title', ''):
                return None
        
        # 조 찾기
        if node.get('level') == LEVEL_JO and node.get('type') == '조':
            if jo_number and node.get('number') == jo_number:
                return node
            if jo_title and jo_title in node.get('title', ''):
                return node
        
        # 자식 노드에서 재귀 검색
        for child in node.get('children', []):
            result = _find_in_node(child, target_section)
            if result:
                return result
        
        return None
    
    return _find_in_node(data, section_title)


def print_hierarchy(node: Dict, indent: int = 0, max_depth: int = 10):
    """
    계층 구조를 트리 형태로 출력
    
    Args:
        node: 노드 딕셔너리
        indent: 들여쓰기 레벨
        max_depth: 최대 깊이
    """
    if indent > max_depth:
        return
    
    prefix = "│   " * indent
    level = node.get('level', -1)
    node_type = node.get('type', 'unknown')
    number = node.get('number')
    marker = node.get('marker', '')
    title = node.get('title', '')
    content = node.get('content', '')
    
    # 레벨별 표시
    level_markers = {
        LEVEL_SECTION: '[섹션]',
        LEVEL_JO: '[조]',
        LEVEL_HANG: '[항]',
        LEVEL_HO: '[호]',
        LEVEL_MOK: '[목]'
    }
    level_marker = level_markers.get(level, f'[L{level}]')
    
    # 번호/마커 표시
    if number is not None:
        num_str = f"#{number}"
    elif marker:
        num_str = f"'{marker}'"
    else:
        num_str = ""
    
    # 제목/내용 표시
    if title:
        display = title[:50] + "..." if len(title) > 50 else title
    elif content:
        display = content[:50] + "..." if len(content) > 50 else content
    else:
        display = "(내용 없음)"
    
    print(f"{prefix}├── {level_marker} {num_str} {display}")
    
    # 자식 노드 출력
    for child in node.get('children', []):
        print_hierarchy(child, indent + 1, max_depth)


def analyze_hierarchy(node: Dict) -> Dict:
    """
    계층 구조 통계 분석
    
    Returns:
        통계 딕셔너리
    """
    stats = {
        '조': 0,
        '항': 0,
        '호': 0,
        '목': 0,
        '기타': 0
    }
    
    def _count_recursive(n: Dict):
        node_type = n.get('type', '')
        level = n.get('level', -1)
        
        if level == LEVEL_JO and node_type == '조':
            stats['조'] += 1
        elif level == LEVEL_HANG and node_type == '항':
            stats['항'] += 1
        elif level == LEVEL_HO and node_type == '호':
            stats['호'] += 1
        elif level == LEVEL_MOK and node_type == '목':
            stats['목'] += 1
        else:
            stats['기타'] += 1
        
        for child in n.get('children', []):
            _count_recursive(child)
    
    _count_recursive(node)
    return stats


def check_hierarchy_structure(node: Dict) -> List[str]:
    """
    계층 구조의 문제점 체크
    
    Returns:
        문제점 리스트
    """
    issues = []
    
    def _check_recursive(n: Dict, parent_level: int = -1):
        current_level = n.get('level', -1)
        node_type = n.get('type', '')
        
        # 레벨 순서 체크
        if parent_level >= 0 and current_level <= parent_level:
            if node_type not in ['section', 'special']:  # 섹션과 특수 블록은 예외
                issues.append(
                    f"레벨 순서 문제: 부모 레벨 {parent_level} >= 자식 레벨 {current_level} "
                    f"({n.get('title', '제목 없음')[:30]})"
                )
        
        # 조 → 항 → 호 → 목 순서 체크
        expected_types = {
            LEVEL_JO: ['항', '호'],  # 조 다음은 항 또는 호
            LEVEL_HANG: ['호', '목'],  # 항 다음은 호 또는 목
            LEVEL_HO: ['목'],  # 호 다음은 목
            LEVEL_MOK: []  # 목 다음은 없음 (또는 세목)
        }
        
        if current_level in expected_types:
            for child in n.get('children', []):
                child_type = child.get('type', '')
                if child_type not in expected_types[current_level] and child_type not in ['special', '세목', '대시']:
                    # 경고만 (에러 아님)
                    pass
        
        for child in n.get('children', []):
            _check_recursive(child, current_level)
    
    _check_recursive(node)
    return issues


def list_all_sections(data: Dict) -> List[Dict]:
    """모든 섹션 목록 반환"""
    sections = []
    
    def _find_sections(node: Dict):
        if node.get('level') == LEVEL_SECTION:
            # 해당 섹션의 조 개수 세기
            jo_count = 0
            def _count_jos(n: Dict):
                nonlocal jo_count
                if n.get('level') == LEVEL_JO and n.get('type') == '조':
                    jo_count += 1
                for child in n.get('children', []):
                    _count_jos(child)
            _count_jos(node)
            
            sections.append({
                'title': node.get('title', '제목 없음'),
                'page': node.get('page', 0),
                'jo_count': jo_count
            })
        
        for child in node.get('children', []):
            _find_sections(child)
    
    _find_sections(data)
    return sections


def list_jos_in_section(data: Dict, section_title: Optional[str] = None) -> List[Dict]:
    """특정 섹션 내의 모든 조 목록 반환"""
    jos = []
    
    def _find_in_node(node: Dict, in_target_section: bool = False):
        # 섹션 체크
        if node.get('level') == LEVEL_SECTION:
            if section_title is None or section_title in node.get('title', ''):
                in_target_section = True
            else:
                in_target_section = False
        
        # 조 찾기
        if in_target_section and node.get('level') == LEVEL_JO and node.get('type') == '조':
            jos.append({
                'number': node.get('number'),
                'title': node.get('title', ''),
                'page': node.get('page', 0)
            })
        
        for child in node.get('children', []):
            _find_in_node(child, in_target_section)
    
    _find_in_node(data)
    return jos


def main():
    # 입력 파일 (기본값, 필요시 수정)
    # 상대 경로로 변경: 프로젝트 루트 기준
    if len(sys.argv) > 1:
        input_file = Path(sys.argv[1])
    else:
        input_file = Path(__file__).parent.parent / "output" / "test_full" / "parsed_hierarchy_v3.json"
    
    if not input_file.exists():
        print(f"❌ 파일을 찾을 수 없습니다: {input_file}")
        print(f"\n사용법: python {Path(__file__).name} [파일경로]")
        print(f"예시: python {Path(__file__).name} output/test_full/parsed_hierarchy_v3.json")
        return
    
    print("=" * 80)
    print("조항호목 계층 구조 확인")
    print("=" * 80)
    print(f"입력: {input_file}")
    
    # 1. JSON 파일 로드
    print("\n[1/5] JSON 파일 로드 중...")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"  → 로드 완료")
    
    # 2. 섹션 목록 출력
    print("\n[2/5] 섹션 목록")
    print("-" * 80)
    sections = list_all_sections(data)
    for i, section in enumerate(sections, 1):
        print(f"  [{i}] {section['title']}")
        print(f"      페이지: {section['page']}, 조 개수: {section['jo_count']}개")
    
    # 3. 조 검색
    print("\n[3/5] 조 검색")
    print("-" * 80)
    
    # 사용자 입력 또는 기본값
    jo_number = 15  # 기본값: 제7조
    section_title = "어린이놀이시설배상책임 특별약관"  # None이면 모든 섹션에서 검색
    
    # 특정 섹션 지정 예시 (주석 해제하여 사용)
    # section_title = "KB주택화재보험 보통약관"
    
    if section_title:
        print(f"  섹션: {section_title}")
        # 해당 섹션의 조 목록 출력
        section_jos = list_jos_in_section(data, section_title)
        print(f"  해당 섹션의 조 목록 ({len(section_jos)}개):")
        for jo_info in section_jos[:10]:
            print(f"    - 제{jo_info['number']}조: {jo_info['title'][:50]}")
        if len(section_jos) > 10:
            print(f"    ... 외 {len(section_jos) - 10}개 더")
    
    jo = find_jo(data, jo_number=jo_number, section_title=section_title)
    
    if not jo:
        print(f"  ❌ 제{jo_number}조를 찾을 수 없습니다.")
        print("\n사용 가능한 조 목록:")
        
        # 모든 조 찾기
        all_jos = []
        def _find_all_jos(node: Dict):
            if node.get('level') == LEVEL_JO and node.get('type') == '조':
                all_jos.append({
                    'number': node.get('number'),
                    'title': node.get('title', ''),
                    'section': ''
                })
            for child in node.get('children', []):
                _find_all_jos(child)
        
        _find_all_jos(data)
        
        for jo_info in sorted(all_jos, key=lambda x: x['number'] or 0)[:20]:
            print(f"    제{jo_info['number']}조: {jo_info['title'][:50]}")
        
        if len(all_jos) > 20:
            print(f"    ... 외 {len(all_jos) - 20}개 더")
        
        return
    
    print(f"  ✓ 제{jo_number}조 찾음: {jo.get('title', '제목 없음')}")
    
    # 4. 계층 구조 출력
    print("\n[4/5] 계층 구조")
    print("-" * 80)
    print_hierarchy(jo, max_depth=5)
    
    # 5. 통계 분석
    print("\n[5/5] 구조 통계")
    print("-" * 80)
    stats = analyze_hierarchy(jo)
    print(f"  조: {stats['조']}개")
    print(f"  항: {stats['항']}개")
    print(f"  호: {stats['호']}개")
    print(f"  목: {stats['목']}개")
    print(f"  기타: {stats['기타']}개")
    
    # 6. 문제점 체크
    print("\n[6/6] 구조 검증")
    print("-" * 80)
    issues = check_hierarchy_structure(jo)
    if issues:
        print(f"  ⚠️  {len(issues)}개 문제 발견:")
        for issue in issues[:10]:
            print(f"    - {issue}")
        if len(issues) > 10:
            print(f"    ... 외 {len(issues) - 10}개 더")
    else:
        print("  ✓ 구조 검증 통과")
    
    print("\n" + "=" * 80)
    print("완료!")
    print("=" * 80)
    
    # 추가 옵션
    print("\n" + "=" * 80)
    print("사용 방법")
    print("=" * 80)
    print("1. 다른 조를 확인하려면 스크립트의 jo_number 값을 변경하세요.")
    print("2. 특정 섹션에서 조를 찾으려면 section_title 변수를 설정하세요.")
    print("   예: section_title = 'KB주택화재보험 보통약관'")
    print("3. 섹션 목록은 위의 [2/5] 섹션 목록에서 확인할 수 있습니다.")


if __name__ == "__main__":
    main()
