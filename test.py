"""
hierarchy_parser와 section_exporter 테스트 스크립트

main.py의 실행 단계를 선택해서 실행할 수 있습니다.
원하는 단계만 선택해서 실행 가능합니다.
"""
import sys
from pathlib import Path
from typing import List, Set
import logging
import time
from datetime import timedelta

from object_parsing.hierarchy_parser import (
    process_hierarchy_parsing,
    DOC_TYPE_INSURANCE,
    DOC_TYPE_LAW
)
from object_parsing.section_exporter import process_section_export
from object_parsing.text_extractor import process_all_json_files

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class PipelineTestRunner:
    """파이프라인 테스트 실행기 (main.py 단계별 실행)"""
    
    def __init__(
        self,
        parsing_results_dir: Path,
        pdf_pages_dir: Path,
        hierarchy_output_file: Path,
        neo4j_export_dir: Path,
        doc_type: str = DOC_TYPE_INSURANCE,
        max_workers: int = 10
    ):
        self.parsing_results_dir = parsing_results_dir
        self.pdf_pages_dir = pdf_pages_dir
        self.hierarchy_output_file = hierarchy_output_file
        self.neo4j_export_dir = neo4j_export_dir
        self.doc_type = doc_type
        self.max_workers = max_workers
    
    def run_step4_text_extraction(self) -> List[Path]:
        """
        4단계: 텍스트 추출 (텍스트 블록의 block_content 채우기 및 박스 감지)
        
        Returns:
            처리된 파일 경로 리스트
        """
        logger.info("\n" + "=" * 80)
        logger.info("4단계: 텍스트 추출 (텍스트 블록 처리 및 박스 감지)")
        logger.info("=" * 80)
        
        step_start = time.time()
        try:
            processed_files = process_all_json_files(
                parsing_results_dir=self.parsing_results_dir,
                pdf_pages_dir=self.pdf_pages_dir,
                output_dir=None,  # 원본 파일에 덮어쓰기
                max_workers=self.max_workers
            )
            step_elapsed = time.time() - step_start
            logger.info("✅ 텍스트 추출 완료")
            logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step_elapsed))} ({step_elapsed:.2f}초)")
            logger.info(f"  처리된 파일 수: {len(processed_files)}개")
            return processed_files
        except Exception as e:
            step_elapsed = time.time() - step_start
            logger.error(f"텍스트 추출 실패: {e}", exc_info=True)
            raise
    
    def run_step5_hierarchy_parsing(self) -> tuple[Path, Path]:
        """
        5단계: 계층 구조 파싱 (조항호목)
        
        Returns:
            (메인 파일 경로, 참조 파일 경로) 튜플
        """
        logger.info("\n" + "=" * 80)
        logger.info("5단계: 계층 구조 파싱 (조항호목)")
        logger.info("=" * 80)
        
        step_start = time.time()
        try:
            hierarchy_main_file, hierarchy_ref_file = process_hierarchy_parsing(
                parsing_results_dir=self.parsing_results_dir,
                output_file=self.hierarchy_output_file,
                doc_type=self.doc_type
            )
            step_elapsed = time.time() - step_start
            logger.info("✅ 계층 구조 파싱 완료")
            logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step_elapsed))} ({step_elapsed:.2f}초)")
            logger.info(f"  메인 파일: {hierarchy_main_file}")
            logger.info(f"  참조 파일: {hierarchy_ref_file}")
            return hierarchy_main_file, hierarchy_ref_file
        except Exception as e:
            step_elapsed = time.time() - step_start
            logger.error(f"계층 구조 파싱 실패: {e}", exc_info=True)
            raise
    
    def run_step6_section_export(self) -> Path:
        """
        6단계: 섹션별 JSON 분리 및 Neo4j/Embedding 준비
        
        Returns:
            document_meta.json 파일 경로
        """
        logger.info("\n" + "=" * 80)
        logger.info("6단계: 섹션별 JSON 분리 및 Neo4j/Embedding 준비")
        logger.info("=" * 80)
        
        if not self.hierarchy_output_file.exists():
            raise FileNotFoundError(
                f"계층 구조 파일이 없습니다: {self.hierarchy_output_file}\n"
                "먼저 5단계(계층 구조 파싱)를 실행하세요."
            )
        
        step_start = time.time()
        try:
            section_meta_file = process_section_export(
                hierarchy_json_path=self.hierarchy_output_file,
                output_dir=self.neo4j_export_dir
            )
            step_elapsed = time.time() - step_start
            logger.info("✅ 섹션별 내보내기 완료")
            logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step_elapsed))} ({step_elapsed:.2f}초)")
            logger.info(f"  문서 메타 파일: {section_meta_file}")
            logger.info(f"  출력 디렉토리: {self.neo4j_export_dir}")
            return section_meta_file
        except Exception as e:
            step_elapsed = time.time() - step_start
            logger.error(f"섹션별 내보내기 실패: {e}", exc_info=True)
            raise
    
    def run_steps(self, steps: Set[int]):
        """
        선택한 단계들 실행
        
        Args:
            steps: 실행할 단계 번호 집합 (예: {5, 6})
        """
        total_start = time.time()
        
        logger.info("=" * 80)
        logger.info("파이프라인 테스트 시작")
        logger.info("=" * 80)
        logger.info(f"실행할 단계: {sorted(steps)}")
        
        results = {}
        
        # 4단계: 텍스트 추출
        if 4 in steps:
            processed_files = self.run_step4_text_extraction()
            results[4] = {
                'processed_files': processed_files,
                'count': len(processed_files)
            }
        
        # 5단계: 계층 구조 파싱
        if 5 in steps:
            hierarchy_main_file, hierarchy_ref_file = self.run_step5_hierarchy_parsing()
            results[5] = {
                'main_file': hierarchy_main_file,
                'ref_file': hierarchy_ref_file
            }
        
        # 6단계: 섹션별 내보내기
        if 6 in steps:
            section_meta_file = self.run_step6_section_export()
            results[6] = {
                'meta_file': section_meta_file
            }
        
        total_elapsed = time.time() - total_start
        
        logger.info("\n" + "=" * 80)
        logger.info("파이프라인 테스트 완료!")
        logger.info("=" * 80)
        logger.info(f"  총 소요 시간: {timedelta(seconds=int(total_elapsed))} ({total_elapsed:.2f}초)")
        logger.info("=" * 80)
        
        return results


def parse_step_selection(selection_str: str) -> Set[int]:
    """
    단계 선택 문자열 파싱
    
    예:
    - "5,6" -> {5, 6}
    - "5-6" -> {5, 6}
    - "5" -> {5}
    """
    if not selection_str:
        return set()
    
    selected = set()
    parts = selection_str.split(',')
    
    for part in parts:
        part = part.strip()
        if '-' in part:
            # 범위 처리
            start, end = part.split('-', 1)
            start = int(start.strip())
            end = int(end.strip())
            selected.update(range(start, end + 1))
        else:
            # 단일 번호
            selected.add(int(part.strip()))
    
    return selected


def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="hierarchy_parser와 section_exporter 테스트 스크립트 (main.py 단계별 실행)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 4단계만 실행 (텍스트 추출)
  python test.py --steps 4
  
  # 5단계만 실행 (계층 구조 파싱)
  python test.py --steps 5
  
  # 6단계만 실행 (섹션별 내보내기)
  python test.py --steps 6
  
  # 4, 5, 6단계 모두 실행
  python test.py --steps 4,5,6
  
  # 4-6단계 실행 (4, 5, 6)
  python test.py --steps 4-6
        """
    )
    parser.add_argument(
        '--parsing-results',
        type=str,
        default="output/test_2/layout_parsing_output/parsing_results",
        help="parsing_results 디렉토리 경로"
    )
    parser.add_argument(
        '--pdf-pages',
        type=str,
        default="output/test_2/layout_parsing_output/pdf_pages",
        help="PDF 페이지 디렉토리 경로"
    )
    parser.add_argument(
        '--hierarchy-output',
        type=str,
        default="output/test_2/document_hierarchy.json",
        help="계층 구조 출력 파일 경로"
    )
    parser.add_argument(
        '--max-workers',
        type=int,
        default=10,
        help="병렬 처리 워커 수 (텍스트 추출 단계에서 사용)"
    )
    parser.add_argument(
        '--neo4j-export',
        type=str,
        default="output/test_2/neo4j_export",
        help="Neo4j export 출력 디렉토리"
    )
    parser.add_argument(
        '--doc-type',
        type=str,
        choices=['insurance', 'law'],
        default='insurance',
        help="문서 타입"
    )
    parser.add_argument(
        '--steps',
        type=str,
        default='4,5,6',
        help="실행할 단계 (예: '4', '5', '6', '4,5,6', '4-6'). 가능한 단계: 4(텍스트 추출), 5(계층 파싱), 6(섹션 내보내기)"
    )
    
    args = parser.parse_args()
    
    # 경로 변환
    parsing_results_dir = Path(args.parsing_results)
    pdf_pages_dir = Path(args.pdf_pages)
    hierarchy_output_file = Path(args.hierarchy_output)
    neo4j_export_dir = Path(args.neo4j_export)
    doc_type = DOC_TYPE_INSURANCE if args.doc_type == 'insurance' else DOC_TYPE_LAW
    
    # 단계 선택 파싱
    selected_steps = parse_step_selection(args.steps)
    
    if not selected_steps:
        logger.error("실행할 단계를 지정해주세요. (예: --steps 5,6)")
        return
    
    # 유효한 단계 확인
    valid_steps = {4, 5, 6}
    invalid_steps = selected_steps - valid_steps
    if invalid_steps:
        logger.error(f"유효하지 않은 단계: {invalid_steps}. 가능한 단계: {valid_steps}")
        return
    
    # Runner 생성
    runner = PipelineTestRunner(
        parsing_results_dir=parsing_results_dir,
        pdf_pages_dir=pdf_pages_dir,
        hierarchy_output_file=hierarchy_output_file,
        neo4j_export_dir=neo4j_export_dir,
        doc_type=doc_type,
        max_workers=args.max_workers
    )
    
    # 실행
    runner.run_steps(selected_steps)


if __name__ == "__main__":
    main()
