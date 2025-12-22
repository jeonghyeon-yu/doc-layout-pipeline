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
from object_parsing.vlm_processor import process_vlm_blocks_from_images
from layout_parsing.html_generator import generate_html_from_json_files

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
        max_workers: int = 10,
        vlm_images_dir: Path = None,
        vlm_api_base: str = None,
        vlm_api_key: str = None,
        vlm_batch_size: int = 10
    ):
        self.parsing_results_dir = parsing_results_dir
        self.pdf_pages_dir = pdf_pages_dir
        self.hierarchy_output_file = hierarchy_output_file
        self.neo4j_export_dir = neo4j_export_dir
        self.doc_type = doc_type
        self.max_workers = max_workers
        self.vlm_images_dir = vlm_images_dir
        self.vlm_api_base = vlm_api_base
        self.vlm_api_key = vlm_api_key
        self.vlm_batch_size = vlm_batch_size
    
    def run_step3_vlm_processing(self) -> List[Path]:
        """
        3단계: VLM 처리 (table, chart, figure → block_content 채우기)
        
        Returns:
            처리된 파일 경로 리스트
        """
        logger.info("\n" + "=" * 80)
        logger.info("3단계: VLM 처리 (table, chart, figure → block_content 채우기)")
        logger.info("=" * 80)
        
        if not self.vlm_images_dir or not self.vlm_images_dir.exists():
            raise FileNotFoundError(
                f"VLM 이미지 디렉토리가 없습니다: {self.vlm_images_dir}\n"
                "먼저 VLM 이미지 추출을 완료하세요."
            )
        
        step_start = time.time()
        try:
            processed_files = process_vlm_blocks_from_images(
                parsing_results_dir=self.parsing_results_dir,
                vlm_images_dir=self.vlm_images_dir,
                vlm_functions=None,  # None이면 자동으로 클라이언트에서 생성
                vlm_client=None,  # None이면 vlm_api_base로 자동 생성
                vlm_api_base=self.vlm_api_base,
                vlm_api_key=self.vlm_api_key,
                vlm_prompts=None,  # None이면 기본값 사용
                output_dir=None,  # 원본 파일 덮어쓰기
                batch_size=self.vlm_batch_size
            )
            step_elapsed = time.time() - step_start
            logger.info("✅ VLM 처리 완료")
            logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step_elapsed))} ({step_elapsed:.2f}초)")
            logger.info(f"  처리된 파일 수: {len(processed_files)}개")
            return processed_files
        except Exception as e:
            step_elapsed = time.time() - step_start
            logger.error(f"VLM 처리 실패: {e}", exc_info=True)
            raise
    
    def run_step4_html_generation(self) -> int:
        """
        4단계: HTML 생성 (JSON → HTML 변환)
        
        Returns:
            생성된 HTML 파일 수
        """
        logger.info("\n" + "=" * 80)
        logger.info("4단계: HTML 생성 (JSON → HTML 변환)")
        logger.info("=" * 80)
        
        step_start = time.time()
        try:
            html_count = generate_html_from_json_files(
                parsing_results_dir=self.parsing_results_dir
            )
            step_elapsed = time.time() - step_start
            logger.info("✅ HTML 생성 완료")
            logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step_elapsed))} ({step_elapsed:.2f}초)")
            logger.info(f"  생성된 HTML 파일 수: {html_count}개")
            logger.info(f"  HTML 저장 위치: {self.parsing_results_dir}")
            return html_count
        except Exception as e:
            step_elapsed = time.time() - step_start
            logger.error(f"HTML 생성 실패: {e}", exc_info=True)
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
        
        # 3단계: VLM 처리
        if 3 in steps:
            processed_files = self.run_step3_vlm_processing()
            results[3] = {
                'processed_files': processed_files,
                'count': len(processed_files)
            }
        
        # 4단계: HTML 생성
        if 4 in steps:
            html_count = self.run_step4_html_generation()
            results[4] = {
                'html_count': html_count
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
  # 3단계만 실행 (VLM 처리)
  python test.py --steps 3
  
  # 4단계만 실행 (HTML 생성)
  python test.py --steps 4
  
  # 5단계만 실행 (계층 구조 파싱)
  python test.py --steps 5
  
  # 6단계만 실행 (섹션별 내보내기)
  python test.py --steps 6
  
  # 3, 4, 5, 6단계 모두 실행
  python test.py --steps 3,4,5,6
  
  # 3-6단계 실행 (3, 4, 5, 6)
  python test.py --steps 3-6
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
        default='3,4,5,6',
        help="실행할 단계 (예: '3', '4', '5', '6', '3,4,5,6', '3-6'). 가능한 단계: 3(VLM 처리), 4(HTML 생성), 5(계층 파싱), 6(섹션 내보내기)"
    )
    parser.add_argument(
        '--vlm-images',
        type=str,
        default=None,
        help="VLM 이미지 디렉토리 경로 (Step 3에서 필요)"
    )
    parser.add_argument(
        '--vlm-api-base',
        type=str,
        default=None,
        help="VLM API 베이스 URL (Step 3에서 필요)"
    )
    parser.add_argument(
        '--vlm-api-key',
        type=str,
        default=None,
        help="VLM API 키 (Step 3에서 필요)"
    )
    parser.add_argument(
        '--vlm-batch-size',
        type=int,
        default=10,
        help="VLM 배치 크기 (Step 3에서 사용)"
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
    valid_steps = {3, 4, 5, 6}
    invalid_steps = selected_steps - valid_steps
    if invalid_steps:
        logger.error(f"유효하지 않은 단계: {invalid_steps}. 가능한 단계: {valid_steps}")
        return
    
    # VLM 관련 경로 설정
    vlm_images_dir = Path(args.vlm_images) if args.vlm_images else None
    
    # Runner 생성
    runner = PipelineTestRunner(
        parsing_results_dir=parsing_results_dir,
        pdf_pages_dir=pdf_pages_dir,
        hierarchy_output_file=hierarchy_output_file,
        neo4j_export_dir=neo4j_export_dir,
        doc_type=doc_type,
        max_workers=args.max_workers,
        vlm_images_dir=vlm_images_dir,
        vlm_api_base=args.vlm_api_base,
        vlm_api_key=args.vlm_api_key,
        vlm_batch_size=args.vlm_batch_size
    )
    
    # 실행
    runner.run_steps(selected_steps)


if __name__ == "__main__":
    main()
