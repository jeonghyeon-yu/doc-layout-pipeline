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


def extract_vlm_block_images(
    json_path: Path,
    pdf_pages_dir: Path,
    vlm_images_dir: Path
) -> Dict:
    """
    JSON 파일의 VLM 처리 대상 블록들(table, chart, figure)의 이미지를 추출하여 vlm_images 폴더에 저장
    
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
    
    # PDF 파일 경로 찾기
    pdf_filename = f"page_{page_index+1:04d}.pdf"
    pdf_path = pdf_pages_dir / pdf_filename
    
    if not pdf_path.exists():
        logger.warning(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return data
    
    # VLM 처리 대상 블록 라벨
    vlm_block_labels = ["table", "chart", "figure"]
    
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
