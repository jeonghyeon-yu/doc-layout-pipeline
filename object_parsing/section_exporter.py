"""
섹션별 JSON 분리 및 Neo4j/Embedding 준비

입력: document_hierarchy.json (트리 구조)
출력:
  - output/document_meta.json
  - output/sections/01_보통약관.json
  - output/sections/02_특별약관_xxx.json
  - output/embeddings/01_보통약관_embeddings.json
  - ...
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field


# =============================================================================
# 데이터 클래스
# =============================================================================

@dataclass
class NodeData:
    """Neo4j 노드 데이터"""
    id: str
    label: str
    properties: Dict[str, Any]


@dataclass 
class EdgeData:
    """Neo4j 엣지 데이터"""
    source: str
    target: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbeddingData:
    """임베딩 데이터"""
    id: str
    label: str
    title: str
    section: str
    embedding_text: str
    token_count: int
    page: int


# =============================================================================
# 메인 Exporter 클래스
# =============================================================================

class SectionExporter:
    """섹션별 JSON 분리 및 내보내기"""
    
    # 노드 타입 → Neo4j 라벨 매핑
    LABEL_MAP = {
        'section': 'Section',
        '편': 'Pyeon',
        '장': 'Jang', 
        '절': 'Jeol',
        '관': 'Gwan',
        '조': 'Jo',
        '항': 'Hang',
        '호': 'Ho',
        '목': 'Mok',
        '세목': 'Semok',
        '대시': 'Dash',
        'special': 'Special'
    }
    
    def __init__(self, hierarchy_json_path: str, output_dir: str):
        self.hierarchy_path = Path(hierarchy_json_path)
        self.output_dir = Path(output_dir)
        self.root = None
        
        # 출력 디렉토리 생성
        (self.output_dir / "sections").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "embeddings").mkdir(parents=True, exist_ok=True)
    
    def load(self):
        """트리 JSON 로드"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("=" * 80)
        logger.info("트리 로드")
        logger.info("=" * 80)
        
        with open(self.hierarchy_path, 'r', encoding='utf-8') as f:
            self.root = json.load(f)
        
        section_count = len(self.root.get('children', []))
        logger.info(f"  섹션 수: {section_count}개\n")
    
    def export(self):
        """전체 내보내기 실행"""
        self.load()
        
        # 문서 메타 생성
        doc_meta = self._create_document_meta()
        
        # 섹션별 처리
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("=" * 80)
        logger.info("섹션별 내보내기")
        logger.info("=" * 80)
        
        sections_info = []
        section_relations = []
        
        for idx, section in enumerate(self.root.get('children', []), 1):
            section_id = section.get('id', f'section_{idx}')
            section_name = section.get('title', section_id)
            section_type = self._detect_section_type(section_name)
            
            # 파일명 생성
            safe_name = self._safe_filename(section_name)
            file_prefix = f"{idx:02d}_{safe_name}"
            
            # 섹션 JSON 생성
            section_data = self._process_section(section, section_id)
            section_file = f"sections/{file_prefix}.json"
            
            with open(self.output_dir / section_file, 'w', encoding='utf-8') as f:
                json.dump(section_data, f, ensure_ascii=False, indent=2)
            
            # 임베딩 JSON 생성
            embedding_data = self._prepare_embeddings(section, section_name)
            embedding_file = f"embeddings/{file_prefix}_embeddings.json"
            
            with open(self.output_dir / embedding_file, 'w', encoding='utf-8') as f:
                json.dump(embedding_data, f, ensure_ascii=False, indent=2)
            
            # 섹션 정보 수집
            sections_info.append({
                "index": idx,
                "id": section_id,
                "name": section_name,
                "type": section_type,
                "file": section_file,
                "embedding_file": embedding_file,
                "node_count": len(section_data['nodes']),
                "edge_count": len(section_data['edges']),
                "embedding_count": len(embedding_data)
            })
            
            # EXTENDS 관계 감지 (추가약관 → 보통약관)
            extends_target = self._detect_extends_relation(section)
            if extends_target:
                section_relations.append({
                    "source": section_id,
                    "target": extends_target,
                    "type": "EXTENDS"
                })
            
            logger.info(f"  [{idx:02d}] {section_name[:40]}")
            logger.info(f"       노드: {len(section_data['nodes'])}개, "
                       f"엣지: {len(section_data['edges'])}개, "
                       f"임베딩: {len(embedding_data)}개")
        
        # 문서 메타 저장
        doc_meta['sections'] = sections_info
        doc_meta['section_relations'] = section_relations
        
        with open(self.output_dir / "document_meta.json", 'w', encoding='utf-8') as f:
            json.dump(doc_meta, f, ensure_ascii=False, indent=2)
        
        logger.info("\n" + "=" * 80)
        logger.info("내보내기 완료")
        logger.info("=" * 80)
        logger.info(f"  출력 디렉토리: {self.output_dir}")
        logger.info(f"  섹션 수: {len(sections_info)}개")
        logger.info(f"  총 노드: {sum(s['node_count'] for s in sections_info)}개")
        logger.info(f"  총 엣지: {sum(s['edge_count'] for s in sections_info)}개")
        logger.info(f"  총 임베딩: {sum(s['embedding_count'] for s in sections_info)}개")
    
    def _create_document_meta(self) -> Dict:
        """문서 메타데이터 생성"""
        doc_name = self.root.get('title', 'Unknown Document')
        
        return {
            "document": {
                "id": f"doc_{self._safe_id(doc_name)}",
                "name": doc_name,
                "source_file": str(self.hierarchy_path),
                "total_sections": len(self.root.get('children', []))
            }
        }
    
    def _detect_section_type(self, section_name: str) -> str:
        """섹션 타입 감지"""
        if '보통약관' in section_name:
            return 'base'  # 기본 약관
        elif '특별약관' in section_name:
            return 'special'  # 특별약관
        elif '추가약관' in section_name:
            return 'additional'  # 추가약관
        elif '법규' in section_name or re.match(r'^[가-힣]+법', section_name):
            return 'law_reference'  # 법규정
        elif '민원' in section_name or '분쟁' in section_name or '유의' in section_name:
            return 'dispute'  # 민원/분쟁
        else:
            return 'other'
    
    def _detect_extends_relation(self, section: Dict) -> Optional[str]:
        """EXTENDS 관계 감지 (추가약관/특별약관 → 보통약관)"""
        section_name = section.get('title', '')
        content = self._get_section_full_text(section)
        
        # 추가약관이 보통약관을 확장하는 패턴
        if '추가약관' in section_name or '특별약관' in section_name:
            # "보통약관 제N조를 변경", "보통약관에 불구하고" 등
            if '보통약관' in content:
                # 보통약관 섹션 ID 찾기
                for child in self.root.get('children', []):
                    if '보통약관' in child.get('title', ''):
                        return child.get('id')
        
        return None
    
    def _get_section_full_text(self, section: Dict) -> str:
        """섹션 전체 텍스트 추출"""
        texts = [section.get('content', '')]
        
        def collect_text(node):
            texts.append(node.get('content', ''))
            for child in node.get('children', []):
                collect_text(child)
        
        for child in section.get('children', []):
            collect_text(child)
        
        return '\n'.join(texts)
    
    def _process_section(self, section: Dict, section_id: str) -> Dict:
        """섹션을 Neo4j용 nodes/edges로 변환"""
        nodes = []
        edges = []
        
        # 섹션 노드
        section_node = {
            "id": section_id,
            "label": "Section",
            "properties": {
                "name": section.get('title', ''),
                "type": self._detect_section_type(section.get('title', '')),
                "page": section.get('page', 0)
            }
        }
        nodes.append(section_node)
        
        # 하위 노드 재귀 처리
        self._process_children(
            parent_id=section_id,
            children=section.get('children', []),
            nodes=nodes,
            edges=edges
        )
        
        return {
            "section": {
                "id": section_id,
                "name": section.get('title', ''),
                "type": self._detect_section_type(section.get('title', ''))
            },
            "nodes": nodes,
            "edges": edges
        }
    
    def _process_children(self, parent_id: str, children: List[Dict], 
                          nodes: List[Dict], edges: List[Dict]):
        """하위 노드 재귀 처리"""
        for child in children:
            child_id = child.get('id', '')
            child_type = child.get('type', '')
            label = self.LABEL_MAP.get(child_type, 'Node')
            
            # 노드 생성
            node = {
                "id": child_id,
                "label": label,
                "properties": {
                    "type": child_type,
                    "number": child.get('number'),
                    "branch": child.get('branch'),
                    "marker": child.get('marker', ''),
                    "title": child.get('title', ''),
                    "content": child.get('content', ''),
                    "page": child.get('page', 0)
                }
            }
            nodes.append(node)
            
            # HAS_CHILD 엣지
            edges.append({
                "source": parent_id,
                "target": child_id,
                "type": "HAS_CHILD"
            })
            
            # 참조 엣지 (REFERENCES / CITES_LAW)
            for ref in child.get('references', []):
                if ref.get('ref_type') == 'internal':
                    if ref.get('resolved_id'):
                        edges.append({
                            "source": child_id,
                            "target": ref['resolved_id'],
                            "type": "REFERENCES",
                            "properties": {
                                "raw_text": ref.get('raw_text', ''),
                                "target_jo": ref.get('target_jo'),
                                "target_hang": ref.get('target_hang')
                            }
                        })
                elif ref.get('ref_type') == 'external':
                    # 외부 법률 참조
                    law_id = f"law_{ref.get('target_law', '')}_{ref.get('target_jo', '')}"
                    edges.append({
                        "source": child_id,
                        "target": law_id,
                        "type": "CITES_LAW",
                        "properties": {
                            "law": ref.get('target_law'),
                            "article": ref.get('target_jo'),
                            "raw_text": ref.get('raw_text', '')
                        }
                    })
            
            # 재귀 처리
            self._process_children(
                parent_id=child_id,
                children=child.get('children', []),
                nodes=nodes,
                edges=edges
            )
    
    def _prepare_embeddings(self, section: Dict, section_name: str) -> List[Dict]:
        """조 단위 임베딩 데이터 준비"""
        embeddings = []
        
        def find_jo_nodes(node: Dict, parent_context: str = ""):
            """조 노드 찾아서 임베딩 준비"""
            node_type = node.get('type', '')
            
            if node_type == '조':
                # 조 전체 텍스트 수집
                full_text = self._collect_full_text(node)
                title = node.get('title', '')
                
                # 컨텍스트 추가 (관 이름 등)
                if parent_context:
                    full_text = f"[{parent_context}]\n{full_text}"
                
                embeddings.append({
                    "id": node.get('id', ''),
                    "label": "Jo",
                    "title": title,
                    "section": section_name,
                    "number": node.get('number'),
                    "branch": node.get('branch'),
                    "embedding_text": full_text,
                    "token_count": len(full_text.split()),
                    "page": node.get('page', 0)
                })
            
            elif node_type == 'special':
                # 법규, 설명 등 특수 블록
                marker = node.get('marker', '')
                if '법규' in marker or '설명' in marker:
                    content = node.get('content', '')
                    embeddings.append({
                        "id": node.get('id', ''),
                        "label": "Special",
                        "title": marker,
                        "section": section_name,
                        "number": None,
                        "branch": None,
                        "embedding_text": content,
                        "token_count": len(content.split()),
                        "page": node.get('page', 0)
                    })
            
            # 컨텍스트 업데이트 (관 이름)
            new_context = parent_context
            if node_type == '관':
                new_context = node.get('title', '')
            
            # 자식 재귀
            for child in node.get('children', []):
                find_jo_nodes(child, new_context)
        
        # 섹션의 모든 자식 탐색
        for child in section.get('children', []):
            find_jo_nodes(child)
        
        return embeddings
    
    def _collect_full_text(self, node: Dict) -> str:
        """노드와 모든 하위 노드의 텍스트 수집"""
        texts = []
        
        # 현재 노드
        marker = node.get('marker', '')
        title = node.get('title', '')
        content = node.get('content', '')
        
        if marker and title:
            texts.append(f"{marker} ({title})")
        if content:
            texts.append(content)
        
        # 자식 노드 (마커 + 내용)
        def collect_children(children, depth=0):
            for child in children:
                child_marker = child.get('marker', '')
                child_content = child.get('content', '')
                
                if child_marker:
                    texts.append(f"{child_marker} {child_content}")
                elif child_content:
                    texts.append(child_content)
                
                collect_children(child.get('children', []), depth + 1)
        
        collect_children(node.get('children', []))
        
        return '\n'.join(texts)
    
    def _safe_filename(self, name: str) -> str:
        """파일명에 안전한 문자열로 변환"""
        # 특수문자 제거, 공백 → 언더스코어
        safe = re.sub(r'[\\/*?:"<>|]', '', name)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe[:50]  # 길이 제한
        return safe
    
    def _safe_id(self, name: str) -> str:
        """ID에 안전한 문자열로 변환"""
        safe = re.sub(r'[^가-힣a-zA-Z0-9_]', '_', name)
        return safe


# =============================================================================
# 파이프라인 함수
# =============================================================================

def process_section_export(
    hierarchy_json_path: Path,
    output_dir: Path
) -> Path:
    """
    섹션별 JSON 분리 및 Neo4j/Embedding 준비
    
    Args:
        hierarchy_json_path: document_hierarchy.json 파일 경로
        output_dir: 출력 디렉토리 경로
    
    Returns:
        document_meta.json 파일 경로
    """
    exporter = SectionExporter(str(hierarchy_json_path), str(output_dir))
    exporter.export()
    return output_dir / "document_meta.json"

