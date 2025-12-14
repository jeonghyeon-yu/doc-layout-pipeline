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

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 설정
INPUT_PATH = "work.pdf"  # PDF 파일 경로
OUT_DIR = Path("output")
OUT_DIR.mkdir(exist_ok=True)

MAX_WORKERS = 5  # CPU면 6~12 정도 / GPU면 1~2 권장

# VLM 처리 설정
ENABLE_VLM_PROCESSING = True  # True로 설정하면 VLM 처리 수행
VLM_API_BASE = "http://localhost:8888/v1"  # Qwen3-VL API 서버 주소
VLM_API_KEY = "optional-api-key-here"  # VLM API 키 (docker-compose.yml의 --api-key와 일치해야 함)
VLM_BATCH_SIZE = 10  # VLM 배치 처리 크기

# VLM 프롬프트 설정 (None이면 기본 프롬프트 사용, 각 타입별로 커스터마이즈 가능)
VLM_PROMPTS = {
    # "table": "커스텀 테이블 프롬프트",
    # "chart": "커스텀 차트 프롬프트",
    # "figure": "커스텀 그림 프롬프트"
}
# 기본 프롬프트를 사용하려면 VLM_PROMPTS = None 또는 빈 딕셔너리 {}


def main():
    """
    전체 파이프라인 실행:
    1. 레이아웃 파싱 (PDF → JSON)
    2. 텍스트 추출 (텍스트 블록의 block_content 채우기)
    3. VLM 이미지 추출 (table, chart, figure 이미지 추출)
    4. VLM 처리 (선택적, 이미지 → VLM 처리 → block_content 채우기)
    """
    input_path = Path(INPUT_PATH)
    
    if not input_path.exists():
        logger.error(f"입력 파일을 찾을 수 없습니다: {input_path}")
        return
    
    # 전체 시작 시간
    total_start_time = time.time()
    
    logger.info("=" * 80)
    logger.info("전체 파이프라인 시작")
    logger.info("=" * 80)
    
    # 원본 파일명 기준으로 결과 폴더 경로 생성
    base_name = input_path.stem
    layout_parsing_output_dir = OUT_DIR / base_name / "layout_parsing_output"
    parsing_results_dir = layout_parsing_output_dir / "parsing_results"
    pdf_pages_dir = layout_parsing_output_dir / "pdf_pages"
    vlm_images_dir = layout_parsing_output_dir / "vlm_images"
    
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
            out_dir=OUT_DIR,
            max_workers=MAX_WORKERS
        )
        step1_elapsed = time.time() - step1_start
        logger.info("✅ 레이아웃 파싱 완료")
        logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step1_elapsed))} ({step1_elapsed:.2f}초)")
        logger.info(f"  Parsing results (JSON): {parsing_results_dir}")
        logger.info(f"  Layout parsing output: {layout_parsing_output_dir}")
    except Exception as e:
        logger.error(f"레이아웃 파싱 실패: {e}", exc_info=True)
        return
    
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
            max_workers=MAX_WORKERS
        )
        step2_elapsed = time.time() - step2_start
        logger.info(f"✅ 텍스트 추출 완료: {len(processed_files)}개 파일")
        logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step2_elapsed))} ({step2_elapsed:.2f}초)")
    except Exception as e:
        logger.error(f"텍스트 추출 실패: {e}", exc_info=True)
        return
    
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
        logger.error(f"VLM 이미지 추출 실패: {e}", exc_info=True)
        return
    
    # ============================================================
    # 4. VLM 처리
    # ============================================================
    step4_elapsed = 0
    if ENABLE_VLM_PROCESSING:
        logger.info("\n" + "=" * 80)
        logger.info("4단계: VLM 처리 (table, chart, figure → block_content 채우기)")
        logger.info("=" * 80)
        
        step4_start = time.time()
        try:
            processed_files = process_vlm_blocks_from_images(
                parsing_results_dir=parsing_results_dir,
                vlm_images_dir=vlm_images_dir,
                vlm_functions=None,  # None이면 자동으로 클라이언트에서 생성
                vlm_client=None,  # None이면 vlm_api_base로 자동 생성
                vlm_api_base=VLM_API_BASE,
                vlm_api_key=VLM_API_KEY,
                vlm_prompts=VLM_PROMPTS if VLM_PROMPTS else None,  # 프롬프트 설정 (None이면 기본값 사용)
                output_dir=None,  # 원본 파일 덮어쓰기
                batch_size=VLM_BATCH_SIZE
            )
            step4_elapsed = time.time() - step4_start
            logger.info(f"✅ VLM 처리 완료: {len(processed_files)}개 파일")
            logger.info(f"  ⏱️  소요 시간: {timedelta(seconds=int(step4_elapsed))} ({step4_elapsed:.2f}초)")
        except Exception as e:
            logger.error(f"VLM 처리 실패: {e}", exc_info=True)
            logger.warning("VLM 처리를 건너뛰고 계속 진행합니다.")
    else:
        logger.info("\n" + "=" * 80)
        logger.info("4단계: VLM 처리 (건너뜀)")
        logger.info("=" * 80)
        logger.info("VLM 처리를 활성화하려면 main.py에서 ENABLE_VLM_PROCESSING = True로 설정하세요")
        logger.info(f"  VLM 이미지 저장 위치: {vlm_images_dir}")
    
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
    if ENABLE_VLM_PROCESSING:
        logger.info(f"  4단계 (VLM 처리):          {timedelta(seconds=int(step4_elapsed))} ({step4_elapsed:.2f}초)")
    else:
        logger.info("  4단계 (VLM 처리):          건너뜀")
    logger.info("  ─────────────────────────────────────────────")
    logger.info(f"  총 소요 시간:               {timedelta(seconds=int(total_elapsed))} ({total_elapsed:.2f}초)")
    logger.info("=" * 80)
    logger.info("결과 위치:")
    logger.info(f"  - 레이아웃 파싱 결과: {parsing_results_dir}")
    logger.info(f"  - PDF 페이지: {pdf_pages_dir}")
    logger.info(f"  - VLM 이미지: {vlm_images_dir}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
