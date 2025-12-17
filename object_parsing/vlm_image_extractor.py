"""VLM 처리용 이미지 추출 (table, chart, figure)"""
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Optional
import json
from PIL import Image
import io
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


def extract_image_from_pdf_bbox(
    pdf_path: Path,
    pdf_bbox: List[float],
    page_index: int = 0,
    zoom: float = 2.0
) -> Optional[Image.Image]:
    """
    PDF에서 지정된 bbox 영역을 이미지로 추출
    
    Args:
        pdf_path: PDF 파일 경로
        pdf_bbox: PDF 좌표 [x1, y1, x2, y2] (포인트 단위)
        page_index: 페이지 인덱스 (0부터 시작)
        zoom: 이미지 확대 배율 (해상도 향상용, 기본값 2.0)
    
    Returns:
        PIL Image 객체 또는 None
    """
    if len(pdf_bbox) != 4:
        return None
    
    try:
        doc = fitz.open(str(pdf_path))
        if page_index >= len(doc):
            doc.close()
            return None
        
        page = doc[page_index]
        x1, y1, x2, y2 = pdf_bbox
        
        # PyMuPDF는 왼쪽 상단이 원점이므로 그대로 사용
        rect = fitz.Rect(x1, y1, x2, y2)
        
        # 해당 영역을 이미지로 렌더링 (zoom으로 해상도 조절)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=rect)
        
        # PIL Image로 변환
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        
        doc.close()
        return img
    except Exception as e:
        logger.error(f"이미지 추출 실패 ({pdf_path}, page {page_index}): {e}", exc_info=True)
        return None


def save_block_image(
    img: Image.Image,
    vlm_images_dir: Path,
    block_id: str,
    block_label: str
) -> Optional[Path]:
    """
    블록 이미지를 vlm_images 폴더의 타입별 하위 폴더에 저장
    
    Args:
        img: PIL Image 객체
        vlm_images_dir: vlm_images 디렉토리 경로 (예: output/test/layout_parsing_output/vlm_images)
        block_id: 블록 식별자 (예: "page_0001_0_res_block_3")
        block_label: 블록 라벨 (예: "table", "chart", "figure")
    
    Returns:
        저장된 파일 경로 또는 None
    """
    try:
        # vlm_images/{block_label}/ 폴더 생성
        type_dir = vlm_images_dir / block_label  # vlm_images/table, vlm_images/chart, vlm_images/figure
        type_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{block_id}.png"
        filepath = type_dir / filename
        img.save(filepath, "PNG")
        logger.debug(f"이미지 저장 완료: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"이미지 저장 실패 ({block_id}): {e}", exc_info=True)
        return None


def estimate_block_order_for_null_blocks(parsing_res_list: List[Dict]) -> List[Dict]:
    """
    같은 페이지 내에서 block_order가 null인 모든 블록의 block_order를 추정
    block_label에 관계없이 block_order가 null인 모든 블록을 처리
    block_order가 있는 블록들 사이에 여러 null 블록이 있으면 y 좌표 순서대로 균등하게 배치
    
    Args:
        parsing_res_list: 블록 리스트
    
    Returns:
        block_order가 추정된 블록 리스트
    """
    # 같은 페이지 내에서 pdf_bbox y 좌표로 정렬
    sorted_blocks = sorted(
        parsing_res_list,
        key=lambda b: (
            b.get('pdf_bbox', [0, 999999])[1] if len(b.get('pdf_bbox', [])) >= 2 else 999999
        )
    )
    
    # block_order가 있는 블록들 찾기
    ordered_blocks = [
        (i, block) for i, block in enumerate(sorted_blocks)
        if block.get('block_order') is not None
    ]
    
    updated_list = parsing_res_list.copy()
    block_to_index = {id(block): i for i, block in enumerate(parsing_res_list)}
    
    # block_order가 있는 블록이 없는 경우: block_id 순서대로 1, 2, 3... 으로 배치
    if not ordered_blocks:
        logger.debug("block_order가 있는 블록이 없습니다. block_id 순서대로 추정합니다.")
        null_blocks = [
            (i, block) for i, block in enumerate(sorted_blocks)
            if block.get('block_order') is None
        ]
        
        if null_blocks:
            # block_id 순서대로 정렬
            null_blocks.sort(key=lambda x: x[1].get('block_id', 0))
            
            for k, (j, null_block) in enumerate(null_blocks):
                estimated_order = k + 1  # 1부터 시작
                original_idx = block_to_index.get(id(null_block))
                if original_idx is not None:
                    updated_list[original_idx]['block_order'] = estimated_order
                    logger.debug(f"block_order 추정 (ordered 블록 없음): {null_block.get('block_label')} "
                               f"(block_id={null_block.get('block_id')}, block_idx={original_idx}) -> {estimated_order}")
        
        return updated_list
    
    
    # ordered 블록들 사이의 구간을 찾아서 null 블록들을 배치
    for i in range(len(ordered_blocks) - 1):
        prev_idx, prev_block = ordered_blocks[i]
        next_idx, next_block = ordered_blocks[i + 1]
        
        prev_order = prev_block.get('block_order')
        next_order = next_block.get('block_order')
        prev_y = prev_block.get('pdf_bbox', [0, 0])[1] if len(prev_block.get('pdf_bbox', [])) >= 2 else 0
        next_y = next_block.get('pdf_bbox', [0, 0])[1] if len(next_block.get('pdf_bbox', [])) >= 2 else 0
        
        # 두 ordered 블록 사이에 있는 null 블록들 찾기 (block_label 무관)
        null_blocks_in_range = []
        for j in range(prev_idx + 1, next_idx):
            block = sorted_blocks[j]
            
            # block_order가 null인 모든 블록 처리 (block_label 체크 제거)
            if block.get('block_order') is None:
                block_y = block.get('pdf_bbox', [0, 0])[1] if len(block.get('pdf_bbox', [])) >= 2 else 0
                if prev_y < block_y < next_y:
                    null_blocks_in_range.append((j, block, block_y))
        
        # y 좌표 순서대로 정렬
        null_blocks_in_range.sort(key=lambda x: x[2])
        
        # null 블록들을 균등하게 배치
        if null_blocks_in_range:
            # 구간 길이 계산
            order_range = next_order - prev_order
            # null 블록 개수 + 1로 나눠서 간격 계산
            step = order_range / (len(null_blocks_in_range) + 1)
            
            for k, (j, null_block, _) in enumerate(null_blocks_in_range):
                estimated_order = prev_order + step * (k + 1)
                
                # 원본 리스트에서 인덱스 찾기
                original_idx = block_to_index.get(id(null_block))
                if original_idx is not None:
                    updated_list[original_idx]['block_order'] = estimated_order
                    logger.debug(f"block_order 추정: {null_block.get('block_label')} "
                               f"(block_idx={original_idx}) -> {estimated_order:.2f} "
                               f"(구간: {prev_order} ~ {next_order}, {len(null_blocks_in_range)}개 블록)")
    
    # 첫 번째 ordered 블록보다 위에 있는 null 블록들 처리
    first_idx, first_block = ordered_blocks[0]
    first_order = first_block.get('block_order')
    first_y = first_block.get('pdf_bbox', [0, 0])[1] if len(first_block.get('pdf_bbox', [])) >= 2 else 0
    
    null_blocks_before = []
    for j in range(first_idx):
        block = sorted_blocks[j]
        # block_order가 null인 모든 블록 처리 (block_label 체크 제거)
        if block.get('block_order') is None:
            block_y = block.get('pdf_bbox', [0, 0])[1] if len(block.get('pdf_bbox', [])) >= 2 else 0
            if block_y < first_y:
                null_blocks_before.append((j, block, block_y))
    
    null_blocks_before.sort(key=lambda x: x[2])
    if null_blocks_before:
        step = 0.1  # 첫 번째 블록보다 위면 0.1 간격으로 배치
        for k, (j, null_block, _) in enumerate(null_blocks_before):
            estimated_order = first_order - step * (len(null_blocks_before) - k)
            original_idx = block_to_index.get(id(null_block))
            if original_idx is not None:
                updated_list[original_idx]['block_order'] = estimated_order
                logger.debug(f"block_order 추정 (첫 블록 위): {null_block.get('block_label')} "
                           f"(block_idx={original_idx}) -> {estimated_order:.2f}")
    
    # 마지막 ordered 블록보다 아래에 있는 null 블록들 처리
    last_idx, last_block = ordered_blocks[-1]
    last_order = last_block.get('block_order')
    last_y = last_block.get('pdf_bbox', [0, 0])[1] if len(last_block.get('pdf_bbox', [])) >= 2 else 0
    
    null_blocks_after = []
    for j in range(last_idx + 1, len(sorted_blocks)):
        block = sorted_blocks[j]
        # block_order가 null인 모든 블록 처리 (block_label 체크 제거)
        if block.get('block_order') is None:
            block_y = block.get('pdf_bbox', [0, 0])[1] if len(block.get('pdf_bbox', [])) >= 2 else 0
            if block_y > last_y:
                null_blocks_after.append((j, block, block_y))
    
    null_blocks_after.sort(key=lambda x: x[2])
    if null_blocks_after:
        step = 0.1  # 마지막 블록보다 아래면 0.1 간격으로 배치
        for k, (j, null_block, _) in enumerate(null_blocks_after):
            estimated_order = last_order + step * (k + 1)
            original_idx = block_to_index.get(id(null_block))
            if original_idx is not None:
                updated_list[original_idx]['block_order'] = estimated_order
                logger.debug(f"block_order 추정 (마지막 블록 아래): {null_block.get('block_label')} "
                           f"(block_idx={original_idx}) -> {estimated_order:.2f}")
    
    # 처리되지 않은 null 블록들 확인 (fallback: block_id 순서대로 배치)
    remaining_null_blocks = []
    for i, block in enumerate(updated_list):
        if block.get('block_order') is None:
            remaining_null_blocks.append((i, block))
    
    if remaining_null_blocks:
        logger.debug(f"처리되지 않은 null 블록 {len(remaining_null_blocks)}개 발견. block_id 순서대로 배치합니다.")
        # block_id 순서대로 정렬
        remaining_null_blocks.sort(key=lambda x: x[1].get('block_id', 0))
        
        # 가장 큰 block_order 찾기 (또는 0)
        max_order = max(
            (b.get('block_order') for b in updated_list if b.get('block_order') is not None),
            default=0
        )
        
        for k, (original_idx, null_block) in enumerate(remaining_null_blocks):
            estimated_order = max_order + k + 1
            updated_list[original_idx]['block_order'] = estimated_order
            logger.debug(f"block_order 추정 (fallback): {null_block.get('block_label')} "
                       f"(block_id={null_block.get('block_id')}, block_idx={original_idx}) -> {estimated_order}")
    
    return updated_list


def extract_vlm_block_images(
    json_path: Path,
    pdf_pages_dir: Path,
    vlm_images_dir: Path
) -> Dict:
    """
    JSON 파일의 VLM 처리 대상 블록들(table, chart, figure)의 이미지를 추출하여 vlm_images 폴더에 저장
    block_order가 null인 VLM 블록의 block_order를 추정하여 채움
    
    Args:
        json_path: 레이아웃 파싱 결과 JSON 파일 경로
        pdf_pages_dir: PDF 분할 파일들이 있는 디렉토리
        vlm_images_dir: vlm_images 디렉토리 경로 (vlm_images/table/, vlm_images/chart/, vlm_images/figure/ 생성됨)
    
    Returns:
        업데이트된 데이터 딕셔너리
    """
    # JSON 파일 읽기
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    page_index = data.get("page_index", 0)
    parsing_res_list = data.get("parsing_res_list", [])
    
    # block_order 추정 (block_order가 null인 모든 블록 처리)
    parsing_res_list = estimate_block_order_for_null_blocks(parsing_res_list)
    data["parsing_res_list"] = parsing_res_list
    
    # PDF 파일 경로 찾기
    pdf_filename = f"page_{page_index+1:04d}.pdf"
    pdf_path = pdf_pages_dir / pdf_filename
    
    if not pdf_path.exists():
        logger.warning(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return data
    
    # VLM 처리 대상 블록 라벨
    vlm_block_labels = ["table", "chart", "figure", "image"]
    
    # VLM 처리 대상 블록 처리
    processed_count = 0
    for block_idx, block in enumerate(parsing_res_list):
        block_label = block.get("block_label", "")
        
        # VLM 처리 대상 블록만 처리
        if block_label in vlm_block_labels:
            pdf_bbox = block.get("pdf_bbox", [])
            if pdf_bbox and len(pdf_bbox) == 4:
                # PDF에서 해당 영역을 이미지로 추출
                img = extract_image_from_pdf_bbox(pdf_path, pdf_bbox, page_index=0)
                
                if img:
                    # 블록 식별자 생성
                    json_stem = Path(json_path).stem  # page_0001_0_res
                    block_id = f"{json_stem}_block_{block_idx}"
                    
                    # 이미지 저장 (vlm_images/{block_label}/ 폴더에 저장)
                    img_path = save_block_image(img, vlm_images_dir, block_id, block_label)
                    
                    if img_path:
                        # block_content는 비워둠 (VLM 처리 단계에서 채워짐)
                        # block_content는 VLM 처리 후 채워지므로 여기서는 업데이트하지 않음
                        processed_count += 1
                        logger.debug(f"이미지 추출 완료: {block_label} ({block_id}) -> {img_path.name}")
                    else:
                        logger.error(f"이미지 저장 실패: {block_id}")
    
    logger.info(f"이미지 추출 완료: {processed_count}개 블록 ({json_path.name})")
    
    return data


def extract_all_vlm_block_images(
    parsing_results_dir: Path,
    pdf_pages_dir: Path,
    vlm_images_dir: Path,
    output_dir: Path = None
) -> List[Path]:
    """
    parsing_results 디렉토리의 모든 JSON 파일에서 VLM 처리 대상 블록의 이미지를 추출
    (vlm_images/{block_label}/ 폴더에 이미지 저장)
    
    Args:
        parsing_results_dir: 레이아웃 파싱 결과 JSON 파일들이 있는 디렉토리
        pdf_pages_dir: PDF 분할 파일들이 있는 디렉토리
        vlm_images_dir: vlm_images 디렉토리 경로 (vlm_images/table/, vlm_images/chart/, vlm_images/figure/ 생성됨)
        output_dir: JSON 출력 디렉토리 (None이면 원본 파일 덮어쓰기)
    
    Returns:
        처리된 JSON 파일 경로 리스트
    """
    # JSON 파일들 찾기
    json_files = sorted(parsing_results_dir.glob("*_res.json"))
    
    if not json_files:
        logger.warning(f"JSON 파일을 찾을 수 없습니다: {parsing_results_dir}")
        return []
    
    logger.info(f"이미지 추출 시작: {len(json_files)}개 JSON 파일")
    logger.info(f"이미지 저장 위치: {vlm_images_dir}")
    
    processed_files = []
    
    for json_file in json_files:
        logger.debug(f"처리 중: {json_file.name}")
        
        # 이미지 추출
        updated_data = extract_vlm_block_images(
            json_file, pdf_pages_dir, vlm_images_dir
        )
        
        # 결과 저장
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / json_file.name
        else:
            output_file = json_file
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(updated_data, f, ensure_ascii=False, indent=2)
        
        processed_files.append(output_file)
        logger.debug(f"저장 완료: {output_file.name}")
    
    logger.info(f"이미지 추출 완료: {len(processed_files)}개 파일 처리")
    logger.info("이미지 저장 위치:")
    logger.info(f"  - {vlm_images_dir / 'table'}")
    logger.info(f"  - {vlm_images_dir / 'chart'}")
    logger.info(f"  - {vlm_images_dir / 'figure'}")
    
    return processed_files
