"""전체 파이프라인 테스트"""
from pathlib import Path
import logging
import sys
import time
from datetime import timedelta

# 모듈 import
from layout_parsing import process_layout_parsing
from object_parsing.text_extractor import process_all_json_files
from object_parsing.vlm_image_extractor import extract_all_vlm_block_images
from object_parsing.vlm_processor import process_vlm_blocks_from_images
from object_parsing.hierarchy_parser import process_hierarchy_parsing, DOC_TYPE_INSURANCE, DOC_TYPE_LAW
from object_parsing.section_exporter import process_section_export
from config import load_config
from exceptions import (
    LayoutParsingError,
    TextExtractionError,
    VLMProcessingError,
    ConfigError
)

# 설정 로드
try:
    config = load_config()
except Exception as e:
    # 기본 로깅 설정 (config 로드 전)
    logging.basicConfig(
        level=logging.ERROR,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger(__name__)
    logger.error(f"설정 로드 실패: {e}")
    raise ConfigError(f"설정 로드 실패: {e}")

# 로깅 설정
log_level = getattr(logging, config.log_level.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format=config.log_format,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def main():
    """
    전체 파이프라인 실행:
    1. 레이아웃 파싱 (PDF → JSON)
    2. 텍스트 추출 (텍스트 블록의 block_content 채우기)
    3. VLM 이미지 추출 (table, chart, figure 이미지 추출)
    4. VLM 처리 (선택적, 이미지 → VLM 처리 → block_content 채우기)
    5. 계층 구조 파싱 (조항호목 계층 구조 추출)
    6. 섹션별 JSON 분리 및 Neo4j/Embedding 준비
    """
    input_path = Path(config.input_path)
    
    if not input_path.exists():
        error_msg = f"입력 파일을 찾을 수 없습니다: {input_path}"
        logger.error(error_msg)
        raise ConfigError(error_msg)
    
    # 출력 디렉토리 생성
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 전체 시작 시간
    total_start_time = time.time()
    
    logger.info("=" * 80)
    logger.info("전체 파이프라인 시작")
    logger.info("=" * 80)
    
    # 원본 파일명 기준으로 결과 폴더 경로 생성
    base_name = input_path.stem
    layout_parsing_output_dir = out_dir / base_name / "layout_parsing_output"
    parsing_results_dir = layout_parsing_output_dir / "parsing_results"
    pdf_pages_dir = layout_parsing_output_dir / "pdf_pages"
    vlm_images_dir = layout_parsing_output_dir / "vlm_images"
    hierarchy_output_file = out_dir / base_name / config.output_hierarchy_file
    neo4j_export_dir = out_dir / base_name / config.output_neo4j_export_dir
    
    # 문서 타입 결정
    doc_type = DOC_TYPE_INSURANCE if config.doc_type == "insurance" else DOC_TYPE_LAW
    
    # ============================================================
    # 1. 레이아웃 파싱
    # ============================================================
    logger.info("\n" + "=" * 80)
    logger.info("1단계: 레이아웃 파싱")
    logger.info("=" * 80)
    
    step1_start = time.time()
    try:
        parsing_results_dir, layout_parsing_output_dir = process_layout_parsing(
            input_path=input_path,
            out_dir=out_dir,
            max_workers=config.max_workers
        )
        step1_elapsed = time.time() - step1_start
        logger.info("✅ 레이아웃 파싱 완료")
        logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step1_elapsed))} ({step1_elapsed:.2f}초)")
        logger.info(f"  Parsing results (JSON): {parsing_results_dir}")
        logger.info(f"  Layout parsing output: {layout_parsing_output_dir}")
    except Exception as e:
        step1_elapsed = time.time() - step1_start
        error_msg = f"레이아웃 파싱 실패: {e}"
        logger.error(error_msg, exc_info=True)
        raise LayoutParsingError(error_msg, details=str(e))
    
    # ============================================================
    # 2. 텍스트 추출
    # ============================================================
    logger.info("\n" + "=" * 80)
    logger.info("2단계: 텍스트 추출 (paragraph_title, text, figure_title, header, footer)")
    logger.info("=" * 80)
    
    step2_start = time.time()
    try:
        processed_files = process_all_json_files(
            parsing_results_dir=parsing_results_dir,
            pdf_pages_dir=pdf_pages_dir,
            output_dir=None,  # 원본 파일 덮어쓰기
            max_workers=config.max_workers
        )
        step2_elapsed = time.time() - step2_start
        logger.info(f"✅ 텍스트 추출 완료: {len(processed_files)}개 파일")
        logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step2_elapsed))} ({step2_elapsed:.2f}초)")
    except Exception as e:
        step2_elapsed = time.time() - step2_start
        error_msg = f"텍스트 추출 실패: {e}"
        logger.error(error_msg, exc_info=True)
        raise TextExtractionError(error_msg, details=str(e))
    
    # ============================================================
    # 3. VLM 이미지 추출
    # ============================================================
    logger.info("\n" + "=" * 80)
    logger.info("3단계: VLM 이미지 추출 (table, chart, figure)")
    logger.info("=" * 80)
    
    step3_start = time.time()
    try:
        processed_files = extract_all_vlm_block_images(
            parsing_results_dir=parsing_results_dir,
            pdf_pages_dir=pdf_pages_dir,
            vlm_images_dir=vlm_images_dir,
            output_dir=None  # 원본 파일 덮어쓰기
        )
        step3_elapsed = time.time() - step3_start
        logger.info(f"✅ VLM 이미지 추출 완료: {len(processed_files)}개 파일")
        logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step3_elapsed))} ({step3_elapsed:.2f}초)")
        logger.info(f"  이미지 저장 위치: {vlm_images_dir}")
    except Exception as e:
        step3_elapsed = time.time() - step3_start
        error_msg = f"VLM 이미지 추출 실패: {e}"
        logger.error(error_msg, exc_info=True)
        raise VLMProcessingError(error_msg, details=str(e))
    
    # ============================================================
    # 4. VLM 처리
    # ============================================================
    step4_elapsed = 0
    if config.vlm_enabled:
        logger.info("\n" + "=" * 80)
        logger.info("4단계: VLM 처리 (table, chart, figure → block_content 채우기)")
        logger.info("=" * 80)
        
        step4_start = time.time()
        try:
            vlm_prompts = config.vlm_prompts if config.vlm_prompts else None
            processed_files = process_vlm_blocks_from_images(
                parsing_results_dir=parsing_results_dir,
                vlm_images_dir=vlm_images_dir,
                vlm_functions=None,  # None이면 자동으로 클라이언트에서 생성
                vlm_client=None,  # None이면 vlm_api_base로 자동 생성
                vlm_api_base=config.vlm_api_base,
                vlm_api_key=config.vlm_api_key,
                vlm_prompts=vlm_prompts,  # 프롬프트 설정 (None이면 기본값 사용)
                output_dir=None,  # 원본 파일 덮어쓰기
                batch_size=config.vlm_batch_size
            )
            step4_elapsed = time.time() - step4_start
            logger.info(f"✅ VLM 처리 완료: {len(processed_files)}개 파일")
            logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step4_elapsed))} ({step4_elapsed:.2f}초)")
        except Exception as e:
            step4_elapsed = time.time() - step4_start
            error_msg = f"VLM 처리 실패: {e}"
            logger.error(error_msg, exc_info=True)
            logger.warning("VLM 처리를 건너뛰고 계속 진행합니다.")
            # VLM은 선택적이므로 예외를 발생시키지 않고 경고만
    else:
        logger.info("\n" + "=" * 80)
        logger.info("4단계: VLM 처리 (건너뜀)")
        logger.info("=" * 80)
        logger.info("VLM 처리를 활성화하려면 .env 파일에서 ENABLE_VLM_PROCESSING=true로 설정하세요")
        logger.info(f"  VLM 이미지 저장 위치: {vlm_images_dir}")
    
    # ============================================================
    # 5. 계층 구조 파싱
    # ============================================================
    logger.info("\n" + "=" * 80)
    logger.info("5단계: 계층 구조 파싱 (조항호목)")
    logger.info("=" * 80)
    
    step5_start = time.time()
    try:
        hierarchy_main_file, hierarchy_ref_file = process_hierarchy_parsing(
            parsing_results_dir=parsing_results_dir,
            output_file=hierarchy_output_file,
            doc_type=doc_type
        )
        step5_elapsed = time.time() - step5_start
        logger.info("✅ 계층 구조 파싱 완료")
        logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step5_elapsed))} ({step5_elapsed:.2f}초)")
        logger.info(f"  메인 파일: {hierarchy_main_file}")
        logger.info(f"  참조 파일: {hierarchy_ref_file}")
    except Exception as e:
        step5_elapsed = time.time() - step5_start
        error_msg = f"계층 구조 파싱 실패: {e}"
        logger.error(error_msg, exc_info=True)
        logger.warning("계층 구조 파싱을 건너뛰고 계속 진행합니다.")
        hierarchy_main_file = None
        hierarchy_ref_file = None
        # 계층 구조 파싱은 필수이지만, 섹션 내보내기를 위해 경고만
    
    # ============================================================
    # 6. 섹션별 JSON 분리 및 Neo4j/Embedding 준비
    # ============================================================
    step6_elapsed = 0
    section_meta_file = None
    
    if hierarchy_main_file and hierarchy_main_file.exists():
        logger.info("\n" + "=" * 80)
        logger.info("6단계: 섹션별 JSON 분리 및 Neo4j/Embedding 준비")
        logger.info("=" * 80)
        
        step6_start = time.time()
        try:
            section_meta_file = process_section_export(
                hierarchy_json_path=hierarchy_main_file,
                output_dir=neo4j_export_dir
            )
            step6_elapsed = time.time() - step6_start
            logger.info("✅ 섹션별 내보내기 완료")
            logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step6_elapsed))} ({step6_elapsed:.2f}초)")
            logger.info(f"  문서 메타 파일: {section_meta_file}")
            logger.info(f"  출력 디렉토리: {neo4j_export_dir}")
        except Exception as e:
            step6_elapsed = time.time() - step6_start
            error_msg = f"섹션별 내보내기 실패: {e}"
            logger.error(error_msg, exc_info=True)
            logger.warning("섹션별 내보내기를 건너뛰고 계속 진행합니다.")
            # 섹션 내보내기는 선택적이므로 경고만
    else:
        logger.info("\n" + "=" * 80)
        logger.info("6단계: 섹션별 JSON 분리 (건너뜀)")
        logger.info("=" * 80)
        logger.info("계층 구조 파싱 결과가 없어 섹션별 내보내기를 건너뜁니다.")
    
    # ============================================================
    # 완료
    # ============================================================
    total_elapsed = time.time() - total_start_time
    
    logger.info("\n" + "=" * 80)
    logger.info("전체 파이프라인 완료!")
    logger.info("=" * 80)
    logger.info("⏱️  실행 시간 요약:")
    logger.info(f"  1단계 (레이아웃 파싱):     {timedelta(seconds=int(step1_elapsed))} ({step1_elapsed:.2f}초)")
    logger.info(f"  2단계 (텍스트 추출):       {timedelta(seconds=int(step2_elapsed))} ({step2_elapsed:.2f}초)")
    logger.info(f"  3단계 (VLM 이미지 추출):   {timedelta(seconds=int(step3_elapsed))} ({step3_elapsed:.2f}초)")
    if config.vlm_enabled and step4_elapsed > 0:
        logger.info(f"  4단계 (VLM 처리):          {timedelta(seconds=int(step4_elapsed))} ({step4_elapsed:.2f}초)")
    else:
        logger.info("  4단계 (VLM 처리):          건너뜀")
    logger.info(f"  5단계 (계층 구조 파싱):     {timedelta(seconds=int(step5_elapsed))} ({step5_elapsed:.2f}초)")
    if step6_elapsed > 0:
        logger.info(f"  6단계 (섹션별 내보내기):     {timedelta(seconds=int(step6_elapsed))} ({step6_elapsed:.2f}초)")
    else:
        logger.info("  6단계 (섹션별 내보내기):     건너뜀")
    logger.info("  ─────────────────────────────────────────────")
    logger.info(f"  총 소요 시간:               {timedelta(seconds=int(total_elapsed))} ({total_elapsed:.2f}초)")
    logger.info("=" * 80)
    logger.info("결과 위치:")
    logger.info(f"  - 레이아웃 파싱 결과: {parsing_results_dir}")
    logger.info(f"  - PDF 페이지: {pdf_pages_dir}")
    logger.info(f"  - VLM 이미지: {vlm_images_dir}")
    if step5_elapsed > 0:
        logger.info(f"  - 계층 구조 파싱 결과: {hierarchy_main_file}")
        logger.info(f"  - 계층 구조 참조 결과: {hierarchy_ref_file}")
    if step6_elapsed > 0 and section_meta_file:
        logger.info(f"  - 섹션별 내보내기 결과: {section_meta_file}")
        logger.info(f"  - Neo4j Export 디렉토리: {neo4j_export_dir}")
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except (LayoutParsingError, TextExtractionError, VLMProcessingError) as e:
        logger.error(f"파이프라인 중단: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"예상치 못한 오류: {e}", exc_info=True)
        sys.exit(1)
