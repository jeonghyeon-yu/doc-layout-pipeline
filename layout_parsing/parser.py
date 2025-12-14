"""레이아웃 파싱 로직"""
from pathlib import Path
import fitz  # PyMuPDF
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import logging
import sys

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def split_pdf_to_single_pages(pdf_path: str, out_dir: Path) -> tuple[list[str], int]:
    """
    PDF를 1페이지짜리 PDF 파일들로 분할하고 경로 리스트와 전체 페이지 수 반환
    
    Args:
        pdf_path: 원본 PDF 파일 경로
        out_dir: 출력 디렉토리
    
    Returns:
        (페이지 파일 경로 리스트, 전체 페이지 수) 튜플
    """
    logger.info(f"PDF 분할 시작: {pdf_path} -> {out_dir}")
    
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        src = fitz.open(pdf_path)
        total_pages = len(src)
        
        logger.info(f"PDF 총 페이지 수: {total_pages}")

        page_paths = []
        for i in range(total_pages):
            try:
                dst = fitz.open()
                dst.insert_pdf(src, from_page=i, to_page=i)
                out_path = out_dir / f"page_{i+1:04d}.pdf"
                dst.save(str(out_path))
                dst.close()
                page_paths.append(str(out_path))
                logger.debug(f"페이지 {i+1}/{total_pages} 분할 완료: {out_path.name}")
            except Exception as e:
                logger.error(f"페이지 {i+1}/{total_pages} 분할 실패: {e}", exc_info=True)
                raise

        src.close()
        logger.info(f"PDF 분할 완료: {len(page_paths)}개 파일 생성")
        return page_paths, total_pages
    except Exception as e:
        logger.error(f"PDF 분할 중 오류 발생: {e}", exc_info=True)
        raise


def convert_image_bbox_to_pdf_bbox(image_bbox: list, image_width: int, image_height: int, pdf_width: float, pdf_height: float) -> list:
    """
    이미지 좌표를 PDF 좌표로 변환
    
    Args:
        image_bbox: 이미지 좌표 [x1, y1, x2, y2] (픽셀)
        image_width: 이미지 너비 (픽셀)
        image_height: 이미지 높이 (픽셀)
        pdf_width: PDF 페이지 너비 (포인트)
        pdf_height: PDF 페이지 높이 (포인트)
    
    Returns:
        PDF 좌표 [x1, y1, x2, y2] (포인트)
    """
    if len(image_bbox) != 4:
        return []
    
    x1, y1, x2, y2 = image_bbox
    
    # 스케일 팩터 계산
    scale_x = pdf_width / image_width
    scale_y = pdf_height / image_height
    
    # 좌표 변환 (PyMuPDF는 왼쪽 상단이 원점이므로 Y 좌표 변환 불필요)
    pdf_x1 = x1 * scale_x
    pdf_y1 = y1 * scale_y
    pdf_x2 = x2 * scale_x
    pdf_y2 = y2 * scale_y
    
    return [round(pdf_x1, 2), round(pdf_y1, 2), round(pdf_x2, 2), round(pdf_y2, 2)]


def extract_essential_fields(json_path: Path, pdf_path: Path, page_index: int, total_pages: int) -> dict:
    """
    JSON에서 필요한 필드만 추출하고 block_content를 공란으로 설정
    page_index와 page_count를 올바르게 설정
    image_bbox와 pdf_bbox를 모두 저장
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # PDF 페이지 크기 가져오기
    pdf_width = 0.0
    pdf_height = 0.0
    if pdf_path.exists():
        try:
            doc = fitz.open(pdf_path)
            if len(doc) > 0:
                page = doc[0]
                rect = page.rect
                pdf_width = rect.width
                pdf_height = rect.height
            doc.close()
        except Exception as e:
            logger.warning(f"PDF 크기를 가져올 수 없습니다 ({pdf_path}): {e}")
    
    # 필요한 필드만 추출
    image_width = data.get("width", 0)
    image_height = data.get("height", 0)
    
    essential_data = {
        "input_path": data.get("input_path"),
        "page_index": page_index,  # 올바른 페이지 인덱스 설정
        "page_count": total_pages,  # 전체 페이지 수 설정
        "image_width": image_width,  # 이미지 크기
        "image_height": image_height,
        "pdf_width": pdf_width,  # PDF 크기
        "pdf_height": pdf_height,
        "parsing_res_list": []
    }
    
    # parsing_res_list에서 필요한 필드만 추출 (block_content는 공란)
    parsing_list = data.get("parsing_res_list", [])
    
    logger.debug(f"필수 필드 추출 시작: {len(parsing_list)}개 블록")
    
    for item in parsing_list:
        image_bbox = item.get("block_bbox", [])
        
        # PDF 좌표로 변환
        pdf_bbox = []
        if len(image_bbox) == 4 and image_width > 0 and image_height > 0 and pdf_width > 0 and pdf_height > 0:
            pdf_bbox = convert_image_bbox_to_pdf_bbox(
                image_bbox, image_width, image_height, pdf_width, pdf_height
            )
        else:
            logger.warning(f"PDF 좌표 변환 실패: bbox={image_bbox}, sizes=({image_width}, {image_height}, {pdf_width}, {pdf_height})")
        
        essential_item = {
            "block_label": item.get("block_label", ""),
            "block_content": "",  # 공란으로 설정
            "image_bbox": image_bbox,  # 이미지 좌표 (픽셀)
            "pdf_bbox": pdf_bbox,  # PDF 좌표 (포인트)
            "block_id": item.get("block_id"),
            "block_order": item.get("block_order"),  # table, figure 등은 null일 수 있음
        }
        essential_data["parsing_res_list"].append(essential_item)
    
    logger.debug(f"필수 필드 추출 완료: {len(essential_data['parsing_res_list'])}개 블록")
    
    # 원본 파일 덮어쓰기
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(essential_data, f, ensure_ascii=False, indent=2)
    
    return essential_data


def run_ppstructure_on_one_page(input_path: str, temp_save_dir: Path, parsing_results_dir: Path, page_index: int = None, total_pages: int = None) -> tuple[str, str]:
    """
    워커 프로세스에서 PDF 파일을 PPStructureV3로 처리.
    JSON은 parsing_results 폴더에, 이미지는 temp_save_dir에 저장.
    
    Args:
        input_path: 처리할 PDF 파일 경로
        temp_save_dir: 임시 저장 디렉토리 (이미지 파일용)
        parsing_results_dir: 레이아웃 파싱 결과 JSON 저장 디렉토리
        page_index: 페이지 인덱스 (0부터 시작)
        total_pages: 전체 페이지 수
    
    Returns:
        (처리된 파일 경로, 저장 디렉토리) 튜플
    """
    # 프로세스별 로거 생성 (프로세스 간 공유되지 않음)
    worker_logger = logging.getLogger(f"{__name__}.worker_{page_index}")
    
    try:
        worker_logger.info(f"페이지 처리 시작: {Path(input_path).name} (page {page_index+1}/{total_pages})")
        
        # 프로세스 내부에서 import/모델 생성 (프로세스 간 공유 X)
        from paddleocr import PPStructureV3

        pipeline = PPStructureV3(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
        )

        worker_logger.debug("PPStructureV3 모델 로드 완료, 레이아웃 파싱 시작")
        out = pipeline.predict(input=input_path)
        worker_logger.debug(f"레이아웃 파싱 완료: {len(out)}개 결과")

        # 입력 파일명 기반으로 생성될 JSON 파일명 예측
        input_file = Path(input_path)
        input_stem = input_file.stem  # page_0001
        
        # out은 보통 list 형태
        # 이미지는 임시 디렉토리에 저장
        for res in out:
            res.save_to_json(save_path=str(temp_save_dir))
            res.save_to_img(save_path=str(temp_save_dir))
        
        # 입력 파일명에 해당하는 JSON 파일만 찾기 (병렬 처리 중 다른 파일과 혼동 방지)
        # save_to_json이 생성하는 파일명 패턴: {input_stem}_0_res.json
        temp_json_file = temp_save_dir / f"{input_stem}_0_res.json"
        
        # PDF 파일 경로 찾기 (PDF 좌표 변환용)
        pdf_file_path = Path(input_path)
        
        if temp_json_file.exists():
            worker_logger.debug(f"JSON 파일 찾음: {temp_json_file.name}")
            # 필수 필드만 추출하고 block_content를 공란으로 설정 (파일 직접 수정)
            extract_essential_fields(temp_json_file, pdf_file_path, page_index, total_pages)
            
            # parsing_results 폴더로 JSON 파일 이동
            parsing_results_dir.mkdir(parents=True, exist_ok=True)
            final_json_file = parsing_results_dir / f"{input_stem}_0_res.json"
            temp_json_file.rename(final_json_file)
            worker_logger.info(f"페이지 처리 완료: {final_json_file.name}")
        else:
            # 파일명 패턴이 다를 수 있으므로 fallback: 가장 최근에 생성된 파일 찾기
            json_files = sorted(temp_save_dir.glob(f"{input_stem}*_res.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if json_files:
                temp_json_file = json_files[0]
                worker_logger.debug(f"JSON 파일 찾음 (fallback): {temp_json_file.name}")
                # 필수 필드만 추출하고 block_content를 공란으로 설정 (파일 직접 수정)
                extract_essential_fields(temp_json_file, pdf_file_path, page_index, total_pages)
                
                # parsing_results 폴더로 JSON 파일 이동
                parsing_results_dir.mkdir(parents=True, exist_ok=True)
                final_json_file = parsing_results_dir / temp_json_file.name
                temp_json_file.rename(final_json_file)
                worker_logger.info(f"페이지 처리 완료: {final_json_file.name}")
            else:
                worker_logger.error(f"JSON 파일을 찾을 수 없습니다: {input_stem}")
                raise FileNotFoundError(f"JSON 파일을 찾을 수 없습니다: {input_stem}")

        return input_path, str(parsing_results_dir)
    except Exception as e:
        worker_logger.error(f"페이지 처리 실패 ({input_path}, page {page_index+1}/{total_pages}): {e}", exc_info=True)
        raise


def process_layout_parsing(
    input_path: Path,
    out_dir: Path,
    max_workers: int = 10
) -> tuple[Path, Path]:
    """
    레이아웃 파싱 처리 메인 함수 (PDF 파일만 지원)
    
    Args:
        input_path: 입력 PDF 파일 경로
        out_dir: 출력 디렉토리
        max_workers: 병렬 처리 워커 수
    
    Returns:
        (parsing_results_dir, layout_parsing_output_dir) 튜플
    
    Raises:
        FileNotFoundError: 입력 파일이 존재하지 않는 경우
        ValueError: PDF 파일이 아닌 경우
    """
    logger.info(f"레이아웃 파싱 시작: {input_path}")
    logger.info(f"병렬 처리 워커 수: {max_workers}")
    
    if not input_path.exists():
        logger.error(f"입력 파일을 찾을 수 없습니다: {input_path}")
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {input_path}")
    
    # PDF 파일만 지원
    file_ext = input_path.suffix.lower()
    if file_ext != '.pdf':
        logger.error(f"지원하지 않는 파일 형식: {file_ext} (PDF 파일만 지원)")
        raise ValueError(f"지원하지 않는 파일 형식입니다: {file_ext}. PDF 파일(.pdf)만 지원합니다.")
    
    # 원본 파일명 기준으로 결과 폴더 생성
    base_name = input_path.stem
    
    # 폴더 구조:
    # output/{base_name}/layout_parsing_output/
    #   - pdf_pages/: PDF 분할 파일들
    #   - parsing_results/: 레이아웃 파싱 결과 JSON 파일들
    #   - *.png: 시각화 이미지 파일들 (임시 저장)
    layout_parsing_output_dir = out_dir / base_name / "layout_parsing_output"
    layout_parsing_output_dir.mkdir(parents=True, exist_ok=True)
    
    pdf_pages_dir = layout_parsing_output_dir / "pdf_pages"
    parsing_results_dir = layout_parsing_output_dir / "parsing_results"
    
    # 임시 저장 디렉토리 (이미지 파일용)
    temp_save_dir = layout_parsing_output_dir
    
    logger.info(f"출력 디렉토리: {layout_parsing_output_dir}")
    logger.info(f"PDF 페이지 디렉토리: {pdf_pages_dir}")
    logger.info(f"파싱 결과 디렉토리: {parsing_results_dir}")

    try:
        # PDF 파일인 경우: 분할 후 처리
        page_files, total_pages = split_pdf_to_single_pages(str(input_path), pdf_pages_dir)
        logger.info(f"PDF 분할 완료: {total_pages}개 페이지 -> {pdf_pages_dir}")
        
        # 병렬 처리 (페이지 인덱스와 전체 페이지 수 전달)
        logger.info(f"병렬 처리 시작: {max_workers}개 워커")
        futures = []
        completed_count = 0
        failed_count = 0
        
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            for idx, page_file in enumerate(page_files):
                futures.append(ex.submit(
                    run_ppstructure_on_one_page, 
                    page_file, 
                    temp_save_dir,  # 임시 저장 디렉토리 (이미지 파일용)
                    parsing_results_dir,  # JSON 저장 디렉토리
                    page_index=idx,  # 0부터 시작
                    total_pages=total_pages
                ))

            for f in as_completed(futures):
                try:
                    processed_file, saved = f.result()
                    completed_count += 1
                    logger.info(f"[{completed_count}/{total_pages}] 처리 완료: {Path(processed_file).name} -> {saved}")
                except Exception as e:
                    failed_count += 1
                    logger.error(f"페이지 처리 실패: {e}", exc_info=True)
        
        logger.info(f"병렬 처리 완료: 성공 {completed_count}개, 실패 {failed_count}개")
        
        if failed_count > 0:
            logger.warning(f"{failed_count}개 페이지 처리 실패")
        
    except Exception as e:
        logger.error(f"레이아웃 파싱 중 오류 발생: {e}", exc_info=True)
        raise

    logger.info("레이아웃 파싱 완료")
    logger.info(f"  Layout parsing output: {layout_parsing_output_dir}")
    logger.info(f"  Parsing results (JSON): {parsing_results_dir}")
    logger.info(f"  PDF pages: {pdf_pages_dir}")
    
    return parsing_results_dir, layout_parsing_output_dir