"""PyMuPDF를 사용한 텍스트 추출"""
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict
import json
import re
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def extract_text_from_pdf_bbox(pdf_path: Path, pdf_bbox: List[float], page_index: int = 0) -> str:
    """
    PDF에서 지정된 bbox 영역의 텍스트를 추출
    
    Args:
        pdf_path: PDF 파일 경로
        pdf_bbox: PDF 좌표 [x1, y1, x2, y2] (포인트 단위)
        page_index: 페이지 인덱스 (0부터 시작)
    
    Returns:
        추출된 텍스트
    """
    if len(pdf_bbox) != 4:
        return ""
    
    try:
        doc = fitz.open(str(pdf_path))
        if page_index >= len(doc):
            doc.close()
            return ""
        
        page = doc[page_index]
        x1, y1, x2, y2 = pdf_bbox
        
        # PyMuPDF는 왼쪽 상단이 원점이므로 그대로 사용
        rect = fitz.Rect(x1, y1, x2, y2)
        
        # 해당 영역의 텍스트 추출
        text = page.get_text("text", clip=rect)
        
        doc.close()
        
        # 줄바꿈 문자를 공백으로 치환 후 앞뒤 공백 제거
        text = text.replace('\n', ' ').strip()
        
        # 연속된 공백을 하나로 정리
        text = re.sub(r'\s+', ' ', text)
        
        return text
    except Exception as e:
        logger.error(f"텍스트 추출 실패 ({pdf_path}, page {page_index}): {e}", exc_info=True)
        return ""


def extract_texts_from_pdf_bboxes(
    pdf_path: Path,
    pdf_bboxes: List[List[float]],
    page_index: int = 0
) -> List[str]:
    """
    PDF에서 여러 bbox 영역의 텍스트를 한번에 추출 (PDF 파일을 한 번만 열기)
    
    Args:
        pdf_path: PDF 파일 경로
        pdf_bboxes: PDF 좌표 리스트 [[x1, y1, x2, y2], ...]
        page_index: 페이지 인덱스 (0부터 시작)
    
    Returns:
        추출된 텍스트 리스트
    """
    if not pdf_bboxes:
        return []
    
    try:
        doc = fitz.open(str(pdf_path))
        if page_index >= len(doc):
            doc.close()
            return [""] * len(pdf_bboxes)
        
        page = doc[page_index]
        texts = []
        
        for pdf_bbox in pdf_bboxes:
            if len(pdf_bbox) != 4:
                texts.append("")
                continue
            
            x1, y1, x2, y2 = pdf_bbox
            rect = fitz.Rect(x1, y1, x2, y2)
            text = page.get_text("text", clip=rect)
            
            # 줄바꿈 문자를 공백으로 치환 후 앞뒤 공백 제거
            text = text.replace('\n', ' ').strip()
            # 연속된 공백을 하나로 정리
            text = re.sub(r'\s+', ' ', text)
            texts.append(text)
        
        doc.close()
        return texts
    except Exception as e:
        logger.error(f"텍스트 추출 실패 ({pdf_path}, page {page_index}): {e}", exc_info=True)
        return [""] * len(pdf_bboxes)


def process_text_blocks_in_json(
    json_path: Path,
    pdf_pages_dir: Path
) -> Dict:
    """
    JSON 파일의 텍스트 블록들을 처리하여 block_content를 채움
    (최적화: 같은 페이지의 여러 블록을 한번에 처리)
    
    Args:
        json_path: 레이아웃 파싱 결과 JSON 파일 경로
        pdf_pages_dir: PDF 분할 파일들이 있는 디렉토리
    
    Returns:
        업데이트된 데이터 딕셔너리
    """
    # JSON 파일 읽기
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    page_index = data.get("page_index", 0)
    parsing_res_list = data.get("parsing_res_list", [])
    
    # PDF 파일 경로 찾기
    pdf_filename = f"page_{page_index+1:04d}.pdf"
    pdf_path = pdf_pages_dir / pdf_filename
    
    if not pdf_path.exists():
        logger.warning(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return data
    
    # 텍스트 블록 라벨
    text_block_labels = ["paragraph_title", "text", "figure_title", "header", "footer"]
    
    # 텍스트 블록만 필터링 및 인덱스 저장
    text_block_indices = []
    text_block_bboxes = []
    
    for idx, block in enumerate(parsing_res_list):
        block_label = block.get("block_label", "")
        if block_label in text_block_labels:
            pdf_bbox = block.get("pdf_bbox", [])
            if pdf_bbox and len(pdf_bbox) == 4:
                text_block_indices.append(idx)
                text_block_bboxes.append(pdf_bbox)
    
    # 한번에 모든 텍스트 추출 (PDF 파일을 한 번만 열기)
    if text_block_bboxes:
        texts = extract_texts_from_pdf_bboxes(pdf_path, text_block_bboxes, page_index=0)
        
        # 추출된 텍스트를 블록에 할당
        for idx, text in zip(text_block_indices, texts):
            parsing_res_list[idx]["block_content"] = text
    
    processed_count = len(text_block_indices)
    logger.info(f"텍스트 블록 처리 완료: {processed_count}개 블록 ({json_path.name})")
    
    return data


def _process_single_json_file(
    json_file: Path,
    pdf_pages_dir: Path,
    output_dir: Path = None
) -> tuple[Path, bool]:
    """
    단일 JSON 파일을 처리 (병렬 처리용 워커 함수)
    
    Args:
        json_file: 처리할 JSON 파일 경로
        pdf_pages_dir: PDF 분할 파일들이 있는 디렉토리
        output_dir: 출력 디렉토리 (None이면 원본 파일 덮어쓰기)
    
    Returns:
        (처리된 파일 경로, 성공 여부) 튜플
    """
    worker_logger = logging.getLogger(f"{__name__}.worker")
    
    try:
        worker_logger.debug(f"JSON 파일 처리 시작: {json_file.name}")
        
        # 텍스트 블록 처리
        updated_data = process_text_blocks_in_json(json_file, pdf_pages_dir)
        
        # 결과 저장
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / json_file.name
        else:
            output_file = json_file
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(updated_data, f, ensure_ascii=False, indent=2)
        
        worker_logger.debug(f"JSON 파일 처리 완료: {output_file.name}")
        return output_file, True
    except Exception as e:
        worker_logger.error(f"JSON 파일 처리 실패 ({json_file.name}): {e}", exc_info=True)
        return json_file, False


def process_all_json_files(
    parsing_results_dir: Path,
    pdf_pages_dir: Path,
    output_dir: Path = None,
    max_workers: int = 10
) -> List[Path]:
    """
    parsing_results 디렉토리의 모든 JSON 파일을 처리 (병렬 처리 지원)
    
    Args:
        parsing_results_dir: 레이아웃 파싱 결과 JSON 파일들이 있는 디렉토리
        pdf_pages_dir: PDF 분할 파일들이 있는 디렉토리
        output_dir: 출력 디렉토리 (None이면 원본 파일 덮어쓰기)
        max_workers: 병렬 처리 워커 수 (1이면 순차 처리)
    
    Returns:
        처리된 JSON 파일 경로 리스트
    """
    # JSON 파일들 찾기
    json_files = sorted(parsing_results_dir.glob("*_res.json"))
    
    if not json_files:
        logger.warning(f"JSON 파일을 찾을 수 없습니다: {parsing_results_dir}")
        return []
    
    logger.info(f"텍스트 추출 시작: {len(json_files)}개 JSON 파일")
    logger.info(f"병렬 처리 워커 수: {max_workers}")
    
    processed_files = []
    
    # 병렬 처리
    if max_workers > 1 and len(json_files) > 1:
        futures = []
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            for json_file in json_files:
                futures.append(ex.submit(
                    _process_single_json_file,
                    json_file,
                    pdf_pages_dir,
                    output_dir
                ))
            
            for future in as_completed(futures):
                try:
                    output_file, success = future.result()
                    if success:
                        processed_files.append(output_file)
                        logger.debug(f"처리 완료: {output_file.name}")
                    else:
                        logger.warning(f"처리 실패: {output_file.name}")
                except Exception as e:
                    logger.error(f"처리 중 오류: {e}", exc_info=True)
    else:
        # 순차 처리 (max_workers=1 또는 파일이 1개인 경우)
        for json_file in json_files:
            logger.debug(f"처리 중: {json_file.name}")
            output_file, success = _process_single_json_file(
                json_file, pdf_pages_dir, output_dir
            )
            if success:
                processed_files.append(output_file)
                logger.debug(f"저장 완료: {output_file.name}")
    
    logger.info(f"텍스트 추출 완료: {len(processed_files)}개 파일 처리")
    
    return processed_files


if __name__ == "__main__":
    # 테스트 실행 - 전체 파일 처리
    from pathlib import Path
    
    # 테스트 경로 설정
    base_dir = Path("output/test/layout_parsing_output")
    parsing_results_dir = base_dir / "parsing_results"
    pdf_pages_dir = base_dir / "pdf_pages"
    
    # 모든 JSON 파일 찾기
    json_files = sorted(parsing_results_dir.glob("*_res.json"))
    
    if not json_files:
        print(f"[ERROR] JSON 파일을 찾을 수 없습니다: {parsing_results_dir}")
    else:
        print(f"[TEST] 전체 {len(json_files)}개 JSON 파일 처리 시작...")
        print("=" * 60)
        
        total_processed_blocks = 0
        total_text_blocks = 0
        
        for file_idx, json_file in enumerate(json_files, 1):
            print(f"\n[{file_idx}/{len(json_files)}] Processing {json_file.name}...")
            print("-" * 60)
            
            # JSON 파일 읽기
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            page_index = data.get("page_index", 0)
            parsing_res_list = data.get("parsing_res_list", [])
            
            # PDF 파일 경로
            pdf_filename = f"page_{page_index+1:04d}.pdf"
            pdf_path = pdf_pages_dir / pdf_filename
            
            if not pdf_path.exists():
                print(f"  [SKIP] PDF 파일을 찾을 수 없습니다: {pdf_path}")
                continue
            
            # 텍스트 블록만 필터링
            text_block_labels = ["paragraph_title", "text", "figure_title", "header", "footer"]
            text_blocks = [b for b in parsing_res_list if b.get("block_label") in text_block_labels]
            
            print(f"  Page Index: {page_index}")
            print(f"  Total Blocks: {len(parsing_res_list)}")
            print(f"  Text Blocks: {len(text_blocks)}")
            
            # 모든 텍스트 블록 처리
            processed_count = 0
            for i, block in enumerate(text_blocks, 1):
                block_label = block.get("block_label", "")
                pdf_bbox = block.get("pdf_bbox", [])
                block_order = block.get("block_order", 0)
                
                if pdf_bbox and len(pdf_bbox) == 4:
                    # 분할된 PDF는 각각 1페이지이므로 항상 0번 페이지를 읽어야 함
                    text = extract_text_from_pdf_bbox(pdf_path, pdf_bbox, page_index=0)
                    block["block_content"] = text  # 실제로 업데이트
                    processed_count += 1
                    
                    # 처음 3개 블록만 상세 출력
                    if i <= 3:
                        if text:
                            display_text = text[:100] if len(text) > 100 else text
                            print(f"    [{i}] {block_label} (order:{block_order}): {repr(display_text)}")
                            if len(text) > 100:
                                print(f"        ... (total {len(text)} chars)")
                        else:
                            print(f"    [{i}] {block_label} (order:{block_order}): [EMPTY]")
            
            total_processed_blocks += processed_count
            total_text_blocks += len(text_blocks)
            
            print(f"  Processed: {processed_count}/{len(text_blocks)} blocks")
            
            # 결과를 JSON 파일에 저장
            output_data = {
                "input_path": data.get("input_path"),
                "page_index": page_index,
                "page_count": data.get("page_count"),
                "image_width": data.get("image_width"),
                "image_height": data.get("image_height"),
                "pdf_width": data.get("pdf_width"),
                "pdf_height": data.get("pdf_height"),
                "parsing_res_list": parsing_res_list  # 업데이트된 block_content 포함
            }
            
            # 결과 저장
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            
            print(f"  Saved: {json_file.name}")
        
        print("\n" + "=" * 60)
        print("\n[전체 처리 완료]")
        print(f"  총 파일 수: {len(json_files)}")
        print(f"  총 텍스트 블록: {total_text_blocks}")
        print(f"  처리된 블록: {total_processed_blocks}")
        print("=" * 60)
