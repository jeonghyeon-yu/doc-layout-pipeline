"""PyMuPDF를 사용한 텍스트 추출 (박스 감지 기능 포함)"""
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json
import re
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

# 개선된 박스 감지 모듈 import
from object_parsing.box_detector import (
    extract_boxes_from_page_improved,
    find_containing_box_improved
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# 박스(사각형) 감지 함수들
# =============================================================================

def extract_boxes_from_page(page: fitz.Page, min_width: float = 50, min_height: float = 30) -> List[Dict]:
    """
    PDF 페이지에서 박스(사각형) 영역 추출
    
    Args:
        page: PyMuPDF 페이지 객체
        min_width: 최소 박스 너비 (포인트)
        min_height: 최소 박스 높이 (포인트)
    
    Returns:
        박스 정보 리스트 [{"id": N, "rect": (x0, y0, x1, y1), "type": "rect"}, ...]
    """
    boxes = []
    box_id = 0
    
    try:
        # get_drawings()로 모든 도형 추출
        drawings = page.get_drawings()
        
        # 모든 선을 수집 (각 drawing이 하나의 선만 가질 수 있음)
        all_lines = []
        
        for drawing in drawings:
            # 사각형 타입인 경우
            if drawing.get("type") == "rect" or "rect" in drawing:
                rect = drawing.get("rect")
                if rect:
                    x0, y0, x1, y1 = rect
                    width = abs(x1 - x0)
                    height = abs(y1 - y0)
                    
                    # 최소 크기 필터링
                    if width >= min_width and height >= min_height:
                        boxes.append({
                            "id": box_id,
                            "rect": (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)),
                            "width": width,
                            "height": height,
                            "type": "rect"
                        })
                        box_id += 1
            
            # 선 수집 (각 drawing에서)
            items = drawing.get("items", [])
            for item in items:
                if item[0] == "l" and len(item) >= 3:  # 선(line)
                    all_lines.append(item)
            
            # 단일 drawing 내에서 4개 이상의 선이 있는 경우 (기존 로직 유지)
            if len(items) >= 4:
                lines = [item for item in items if item[0] == "l"]
                if len(lines) >= 4:
                    rect = _lines_to_rect(lines)
                    if rect:
                        x0, y0, x1, y1 = rect
                        width = x1 - x0
                        height = y1 - y0
                        
                        if width >= min_width and height >= min_height:
                            is_duplicate = False
                            for existing in boxes:
                                if _rects_overlap(existing["rect"], rect, threshold=5):
                                    is_duplicate = True
                                    break
                            
                            if not is_duplicate:
                                boxes.append({
                                    "id": box_id,
                                    "rect": rect,
                                    "width": width,
                                    "height": height,
                                    "type": "lines"
                                })
                                box_id += 1
        
        # 수집된 모든 선으로부터 사각형 찾기 (여러 drawing의 선들이 모여서 사각형을 형성하는 경우)
        if len(all_lines) >= 4:
            rect = _lines_to_rect(all_lines)
            if rect:
                x0, y0, x1, y1 = rect
                width = x1 - x0
                height = y1 - y0
                
                if width >= min_width and height >= min_height:
                    is_duplicate = False
                    for existing in boxes:
                        if _rects_overlap(existing["rect"], rect, threshold=5):
                            is_duplicate = True
                            break
                    
                    if not is_duplicate:
                        boxes.append({
                            "id": box_id,
                            "rect": rect,
                            "width": width,
                            "height": height,
                            "type": "lines_combined"
                        })
                        box_id += 1
        
        # page.rects도 확인 (annotation 기반 사각형)
        for rect in page.rects if hasattr(page, 'rects') else []:
            x0, y0, x1, y1 = rect["x0"], rect["y0"], rect["x1"], rect["y1"]
            width = x1 - x0
            height = y1 - y0
            
            if width >= min_width and height >= min_height:
                # 중복 체크
                is_duplicate = False
                rect_tuple = (x0, y0, x1, y1)
                for existing in boxes:
                    if _rects_overlap(existing["rect"], rect_tuple, threshold=5):
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    boxes.append({
                        "id": box_id,
                        "rect": rect_tuple,
                        "width": width,
                        "height": height,
                        "type": "annotation"
                    })
                    box_id += 1
        
    except Exception as e:
        logger.warning(f"박스 추출 중 오류: {e}")
    
    logger.debug(f"페이지에서 {len(boxes)}개 박스 감지")
    return boxes


def _lines_to_rect(lines: List) -> Optional[Tuple[float, float, float, float]]:
    """
    4개의 선으로부터 사각형 좌표 추출 시도
    
    Args:
        lines: 선 정보 리스트 [("l", p1, p2), ...]
    
    Returns:
        사각형 좌표 (x0, y0, x1, y1) 또는 None
    """
    try:
        # 모든 점 수집
        points = []
        for line in lines:
            if len(line) >= 3:
                p1, p2 = line[1], line[2]
                points.append((p1.x, p1.y))
                points.append((p2.x, p2.y))
        
        if len(points) < 4:
            return None
        
        # 바운딩 박스 계산
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        
        # 너무 작은 영역은 무시
        if (x1 - x0) < 10 or (y1 - y0) < 10:
            return None
        
        return (x0, y0, x1, y1)
    
    except Exception:
        return None


def _rects_overlap(rect1: Tuple, rect2: Tuple, threshold: float = 5) -> bool:
    """
    두 사각형이 거의 같은 영역인지 확인
    """
    x0_diff = abs(rect1[0] - rect2[0])
    y0_diff = abs(rect1[1] - rect2[1])
    x1_diff = abs(rect1[2] - rect2[2])
    y1_diff = abs(rect1[3] - rect2[3])
    
    return (x0_diff < threshold and y0_diff < threshold and 
            x1_diff < threshold and y1_diff < threshold)


def is_point_inside_box(bbox: List[float], box_rect: Tuple[float, float, float, float], 
                        margin: float = 2.0) -> bool:
    """
    텍스트 bbox가 박스 안에 있는지 확인
    
    Args:
        bbox: 텍스트 영역 [x0, y0, x1, y1]
        box_rect: 박스 영역 (x0, y0, x1, y1)
        margin: 허용 오차 (포인트)
    
    Returns:
        박스 안에 있으면 True
    """
    if len(bbox) != 4:
        return False
    
    tx0, ty0, tx1, ty1 = bbox
    bx0, by0, bx1, by1 = box_rect
    
    # 텍스트의 시작점이 박스 안에 있는지 확인 (margin 허용)
    inside_x = (bx0 - margin) <= tx0 <= (bx1 + margin)
    inside_y = (by0 - margin) <= ty0 <= (by1 + margin)
    
    return inside_x and inside_y


def find_containing_box(bbox: List[float], boxes: List[Dict], margin: float = 2.0) -> Optional[int]:
    """
    텍스트 bbox를 포함하는 박스 ID 찾기
    
    Args:
        bbox: 텍스트 영역 [x0, y0, x1, y1]
        boxes: 박스 정보 리스트
        margin: 허용 오차 (포인트)
    
    Returns:
        박스 ID 또는 None
    """
    for box in boxes:
        if is_point_inside_box(bbox, box["rect"], margin):
            return box["id"]
    return None


# =============================================================================
# 기존 텍스트 추출 함수들 (수정 없음)
# =============================================================================

def _remove_duplicate_chars(chars: List[Dict]) -> List[Dict]:
    """
    중복 문자 제거 (overprint/중복 렌더링 대응)
    """
    if not chars:
        return []
    
    y_tolerance = 3.0
    y_groups = {}
    for char in chars:
        y_rounded = round(char["y0"] / y_tolerance) * y_tolerance
        if y_rounded not in y_groups:
            y_groups[y_rounded] = []
        y_groups[y_rounded].append(char)
    
    result = []
    for y_key, line_chars in y_groups.items():
        line_chars.sort(key=lambda c: c["x0"])
        
        filtered = []
        for char in line_chars:
            is_duplicate = False
            for existing in filtered:
                dist = ((char["center_x"] - existing["center_x"]) ** 2 + 
                       (char["center_y"] - existing["center_y"]) ** 2) ** 0.5
                
                if dist < 2.0 and char["char"] == existing["char"]:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                filtered.append(char)
        
        result.extend(filtered)
    
    return result


def _get_char_type(char: str) -> str:
    """문자 유형 분류"""
    if re.match(r'[가-힣]', char):
        return "korean"
    elif re.match(r'[\u4e00-\u9fff]', char):
        return "hanja"
    elif char.isdigit():
        return "number"
    elif char.isalpha():
        return "english"
    elif char in '(),.，。':
        return "punctuation"
    else:
        return "other"


def _apply_punctuation_rules(text: str) -> str:
    """구두점/괄호 붙임 규칙 적용"""
    text = re.sub(r'\s+\(', '(', text)
    text = re.sub(r'\)\s+', ')', text)
    text = re.sub(r'\s+([,\.])', r'\1', text)
    return text


def extract_text_with_font_info_from_pdf_bbox(
    pdf_path: Path, 
    pdf_bbox: List[float], 
    page_index: int = 0
) -> Dict[str, Any]:
    """
    PDF에서 지정된 bbox 영역의 텍스트와 폰트 정보를 추출
    """
    if len(pdf_bbox) != 4:
        return {"text": "", "text_length": 0, "font_size": None, "is_bold": None, "font_name": None}
    
    try:
        doc = fitz.open(str(pdf_path))
        if page_index >= len(doc):
            doc.close()
            return {"text": "", "text_length": 0, "font_size": None, "is_bold": None, "font_name": None}
        
        page = doc[page_index]
        x1, y1, x2, y2 = pdf_bbox
        rect = fitz.Rect(x1, y1, x2, y2)
        
        try:
            text_dict = page.get_text("rawdict", clip=rect)
        except Exception:
            text_dict = page.get_text("dict", clip=rect)
        
        doc.close()
        
        font_sizes = []
        bold_flags = []
        font_names = []
        chars = []
        
        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    span_size = span.get("size", None)
                    span_flags = span.get("flags", 0)
                    span_font = span.get("font", None)
                    
                    if span_size is not None:
                        font_sizes.append(span_size)
                    is_span_bold = bool(span_flags & 16) if span_flags else False
                    bold_flags.append(is_span_bold)
                    if span_font:
                        font_names.append(span_font)
                    
                    span_chars = span.get("chars", [])
                    
                    if span_chars:
                        for char_info in span_chars:
                            char_text = char_info.get("c", "")
                            char_bbox = char_info.get("bbox", [0, 0, 0, 0])
                            
                            if len(char_bbox) >= 4 and char_text:
                                chars.append({
                                    "char": char_text,
                                    "x0": char_bbox[0],
                                    "y0": char_bbox[1],
                                    "x1": char_bbox[2],
                                    "y1": char_bbox[3],
                                    "center_x": (char_bbox[0] + char_bbox[2]) / 2,
                                    "center_y": (char_bbox[1] + char_bbox[3]) / 2,
                                    "span_origin": span.get("bbox", [0, 0, 0, 0])[0] if len(span.get("bbox", [])) >= 1 else 0,
                                    "span_end": span.get("bbox", [0, 0, 0, 0])[2] if len(span.get("bbox", [])) >= 3 else 0
                                })
                    else:
                        text = span.get("text", "")
                        bbox = span.get("bbox", [0, 0, 0, 0])
                        if len(bbox) < 4 or not text:
                            continue
                        
                        span_x0, span_y0, span_x1, span_y1 = bbox[0], bbox[1], bbox[2], bbox[3]
                        span_width = span_x1 - span_x0
                        char_width = span_width / len(text) if len(text) > 0 else 0
                        
                        for i, char in enumerate(text):
                            char_x0 = span_x0 + (i * char_width)
                            char_x1 = span_x0 + ((i + 1) * char_width)
                            
                            chars.append({
                                "char": char,
                                "x0": char_x0,
                                "y0": span_y0,
                                "x1": char_x1,
                                "y1": span_y1,
                                "center_x": (char_x0 + char_x1) / 2,
                                "center_y": (span_y0 + span_y1) / 2,
                                "span_origin": span_x0,
                                "span_end": span_x1
                            })
        
        if not chars:
            return {"text": "", "text_length": 0, "font_size": None, "is_bold": None, "font_name": None}
        
        chars = _remove_duplicate_chars(chars)
        
        line_tolerance = 3.0
        lines = []
        for char in chars:
            y0 = char["y0"]
            found_line = False
            for line in lines:
                line_avg_y = line["avg_y"]
                if abs(line_avg_y - y0) <= line_tolerance:
                    line["chars"].append(char)
                    line["avg_y"] = sum(c["y0"] for c in line["chars"]) / len(line["chars"])
                    found_line = True
                    break
            
            if not found_line:
                lines.append({"avg_y": y0, "chars": [char]})
        
        for line in lines:
            line["chars"].sort(key=lambda c: c["x0"])
        lines.sort(key=lambda line: line["avg_y"])
        
        line_texts = []
        for line in lines:
            line_chars = line["chars"]
            if not line_chars:
                continue
            
            line_parts = []
            for i, char in enumerate(line_chars):
                line_parts.append(char["char"])
                
                if i < len(line_chars) - 1:
                    next_char = line_chars[i + 1]
                    gap = next_char["x0"] - char["x1"]
                    estimated_gap = char.get("estimated_next_gap", 0)
                    if estimated_gap > 0:
                        gap = max(gap, estimated_gap)
                    
                    char_height = char["y1"] - char["y0"]
                    same_span = (char.get("span_origin") == next_char.get("span_origin") and
                                char.get("span_end") == next_char.get("span_end"))
                    
                    char_type = _get_char_type(char["char"])
                    next_char_type = _get_char_type(next_char["char"])
                    
                    is_word_boundary = False
                    if char_type == "korean" and next_char_type == "korean":
                        if gap > char_height * 0.4:
                            is_word_boundary = True
                    elif char_type in ["korean", "hanja"] and next_char_type in ["korean", "hanja"]:
                        if gap > char_height * 0.35:
                            is_word_boundary = True
                    
                    if same_span:
                        if estimated_gap > 0:
                            gap_threshold = max(1.5, char_height * 0.2)
                        elif is_word_boundary:
                            gap_threshold = max(2.0, char_height * 0.25)
                        else:
                            gap_threshold = max(2.0, char_height * 0.4)
                    else:
                        gap_threshold = max(1.5, char_height * 0.2)
                    
                    if gap > gap_threshold:
                        line_parts.append(" ")
            
            line_text = "".join(line_parts)
            line_texts.append(line_text)
        
        text = " ".join(line_texts)
        text = _apply_punctuation_rules(text)
        text = text.replace('\n', ' ').strip()
        text = text.replace('\\"', '')
        text = re.sub(r'\s+', ' ', text)
        
        avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else None
        is_bold = True if bold_flags and sum(bold_flags) > len(bold_flags) * 0.5 else False if bold_flags else None
        font_name = max(set(font_names), key=font_names.count) if font_names else None
        text_length = len(text)
        
        return {
            "text": text,
            "text_length": text_length,
            "font_size": round(avg_font_size, 2) if avg_font_size else None,
            "is_bold": is_bold,
            "font_name": font_name
        }
    except Exception as e:
        logger.error(f"텍스트 추출 실패 ({pdf_path}, page {page_index}): {e}", exc_info=True)
        return {"text": "", "text_length": 0, "font_size": None, "is_bold": None, "font_name": None}


def extract_texts_with_font_info_from_pdf_bboxes(
    pdf_path: Path,
    pdf_bboxes: List[List[float]],
    page_index: int = 0
) -> List[Dict[str, Any]]:
    """PDF에서 여러 bbox 영역의 텍스트와 폰트 정보를 한번에 추출"""
    if not pdf_bboxes:
        return []
    
    try:
        results = []
        for pdf_bbox in pdf_bboxes:
            if len(pdf_bbox) != 4:
                results.append({"text": "", "text_length": 0, "font_size": None, "is_bold": None, "font_name": None})
                continue
            result = extract_text_with_font_info_from_pdf_bbox(pdf_path, pdf_bbox, page_index)
            results.append(result)
        return results
    except Exception as e:
        logger.error(f"텍스트 추출 실패 ({pdf_path}, page {page_index}): {e}", exc_info=True)
        return [{"text": "", "text_length": 0, "font_size": None, "is_bold": None, "font_name": None}] * len(pdf_bboxes)


# =============================================================================
# Private Glyph 감지 및 Formula 재라벨링
# =============================================================================

def has_private_glyphs(text: str) -> bool:
    """
    텍스트에 Private Use Area 문자(U+E000 ~ U+F8FF)가 포함되어 있는지 확인
    
    Args:
        text: 확인할 텍스트
    
    Returns:
        Private Use Area 문자가 포함되어 있으면 True
    """
    if not text:
        return False
    
    # Private Use Area 범위 체크
    for char in text:
        code_point = ord(char)
        # U+E000 ~ U+F8FF: Private Use Area (가장 흔한 범위)
        if 0xE000 <= code_point <= 0xF8FF:
            return True
    
    return False


def detect_and_relabel_formula_blocks(parsing_res_list: List[Dict]) -> int:
    """
    텍스트 블록 중 private glyph가 포함된 블록을 formula로 재라벨링
    
    Args:
        parsing_res_list: 블록 리스트
    
    Returns:
        재라벨링된 블록 수
    """
    text_block_labels = ["doc_title", "paragraph_title", "text", "figure_title", "header", 'vision_footnote']
    relabeled_count = 0
    
    for block in parsing_res_list:
        block_label = block.get("block_label", "")
        block_content = block.get("block_content", "")
        
        # 텍스트 블록이고, private glyph가 포함되어 있으면 formula로 변경
        # (이미 formula인 블록은 변경하지 않음)
        if block_label in text_block_labels and has_private_glyphs(block_content):
            logger.debug(f"블록 라벨 변경: {block_label} -> formula (block_id={block.get('block_id')}, "
                        f"content_preview={block_content[:50]}...)")
            block["block_label"] = "formula"
            relabeled_count += 1
    
    if relabeled_count > 0:
        logger.info(f"Private glyph 감지: {relabeled_count}개 블록을 formula로 재라벨링")
    
    return relabeled_count


# =============================================================================
# 메인 처리 함수 (박스 감지 추가)
# =============================================================================

def process_text_blocks_in_json(
    json_path: Path,
    pdf_pages_dir: Path
) -> Dict:
    """
    JSON 파일의 텍스트 블록들을 처리하여 block_content를 채우고 박스 정보 추가
    
    Args:
        json_path: 레이아웃 파싱 결과 JSON 파일 경로
        pdf_pages_dir: PDF 분할 파일들이 있는 디렉토리
    
    Returns:
        업데이트된 데이터 딕셔너리
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    page_index = data.get("page_index", 0)
    parsing_res_list = data.get("parsing_res_list", [])
    
    pdf_filename = f"page_{page_index+1:04d}.pdf"
    pdf_path = pdf_pages_dir / pdf_filename
    
    if not pdf_path.exists():
        logger.warning(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return data
    
    # =========================================================================
    # 1. PDF에서 박스(사각형) 추출 (개선된 방식 사용)
    # =========================================================================
    boxes = []
    try:
        doc = fitz.open(str(pdf_path))
        if len(doc) > 0:
            page = doc[0]
            # 개선된 박스 감지 방식 사용
            boxes = extract_boxes_from_page_improved(page, min_width=100, min_height=50)
            logger.info(f"페이지 {page_index}: {len(boxes)}개 박스 감지")
        doc.close()
    except Exception as e:
        logger.warning(f"박스 추출 실패 ({pdf_path}): {e}")
    
    # 박스 정보를 데이터에 추가
    data["detected_boxes"] = boxes
    
    # =========================================================================
    # 2. 텍스트 블록 처리
    # =========================================================================
    text_block_labels = ["doc_title", "paragraph_title", "text", "figure_title", "header", 'vision_footnote']
    
    text_block_indices = []
    text_block_bboxes = []
    
    for idx, block in enumerate(parsing_res_list):
        block_label = block.get("block_label", "")
        if block_label in text_block_labels:
            pdf_bbox = block.get("pdf_bbox", [])
            if pdf_bbox and len(pdf_bbox) == 4:
                text_block_indices.append(idx)
                text_block_bboxes.append(pdf_bbox)
    
    # 텍스트 및 폰트 정보 추출
    if text_block_bboxes:
        text_font_infos = extract_texts_with_font_info_from_pdf_bboxes(pdf_path, text_block_bboxes, page_index=0)
        
        for idx, info in zip(text_block_indices, text_font_infos):
            parsing_res_list[idx]["block_content"] = info.get("text", "")
            parsing_res_list[idx]["text_length"] = info.get("text_length", 0)
            if info.get("font_size") is not None:
                parsing_res_list[idx]["font_size"] = info["font_size"]
            if info.get("is_bold") is not None:
                parsing_res_list[idx]["is_bold"] = info["is_bold"]
            if info.get("font_name"):
                parsing_res_list[idx]["font_name"] = info["font_name"]
    
    # =========================================================================
    # 2.5. Private glyph가 포함된 텍스트 블록을 formula로 재라벨링
    # =========================================================================
    detect_and_relabel_formula_blocks(parsing_res_list)
    
    # =========================================================================
    # 3. 각 블록이 박스 안에 있는지 확인 (개선된 방식 사용)
    # =========================================================================
    for block in parsing_res_list:
        pdf_bbox = block.get("pdf_bbox", [])
        if pdf_bbox and len(pdf_bbox) == 4 and boxes:
            # 개선된 박스 찾기 방식 사용
            box_id = find_containing_box_improved(pdf_bbox, boxes, margin=5.0)
            block["inside_box"] = box_id is not None
            block["box_id"] = box_id
        else:
            block["inside_box"] = False
            block["box_id"] = None
    
    processed_count = len(text_block_indices)
    box_count = sum(1 for b in parsing_res_list if b.get("inside_box"))
    logger.info(f"텍스트 블록 처리 완료: {processed_count}개 블록, {box_count}개가 박스 안 ({json_path.name})")
    
    return data


def _process_single_json_file(
    json_file: Path,
    pdf_pages_dir: Path,
    output_dir: Path = None
) -> tuple[Path, bool]:
    """단일 JSON 파일 처리 (병렬 처리용)"""
    worker_logger = logging.getLogger(f"{__name__}.worker")
    
    try:
        worker_logger.debug(f"JSON 파일 처리 시작: {json_file.name}")
        updated_data = process_text_blocks_in_json(json_file, pdf_pages_dir)
        
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
    """parsing_results 디렉토리의 모든 JSON 파일을 처리 (병렬 처리 지원)"""
    json_files = sorted(parsing_results_dir.glob("*_res.json"))
    
    if not json_files:
        logger.warning(f"JSON 파일을 찾을 수 없습니다: {parsing_results_dir}")
        return []
    
    logger.info(f"텍스트 추출 시작: {len(json_files)}개 JSON 파일")
    logger.info(f"병렬 처리 워커 수: {max_workers}")
    
    processed_files = []
    
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


# =============================================================================
# 테스트용 함수
# =============================================================================

def test_box_detection(pdf_path: Path, page_index: int = 0):
    """박스 감지 테스트"""
    doc = fitz.open(str(pdf_path))
    if page_index >= len(doc):
        print(f"페이지 {page_index}가 없습니다.")
        doc.close()
        return
    
    page = doc[page_index]
    boxes = extract_boxes_from_page(page, min_width=100, min_height=50)
    
    print(f"=== 페이지 {page_index}: {len(boxes)}개 박스 감지 ===")
    for box in boxes:
        print(f"  Box {box['id']}: {box['rect']} (type: {box['type']}, size: {box['width']:.1f}x{box['height']:.1f})")
    
    doc.close()
    return boxes


if __name__ == "__main__":
    # 테스트
    import sys
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
        page_idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        test_box_detection(pdf_path, page_idx)