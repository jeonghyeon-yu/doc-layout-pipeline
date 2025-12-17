"""PyMuPDF를 사용한 텍스트 추출"""
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Any
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


def _remove_duplicate_chars(chars: List[Dict]) -> List[Dict]:
    """
    중복 문자 제거 (overprint/중복 렌더링 대응)
    
    같은 줄에서 거의 같은 위치에 같은 문자가 있으면 하나만 남기기
    """
    if not chars:
        return []
    
    # y 좌표로 그룹화 (같은 줄)
    y_tolerance = 3.0
    y_groups = {}
    for char in chars:
        y_rounded = round(char["y0"] / y_tolerance) * y_tolerance
        if y_rounded not in y_groups:
            y_groups[y_rounded] = []
        y_groups[y_rounded].append(char)
    
    # 각 줄에서 중복 제거
    result = []
    for y_key, line_chars in y_groups.items():
        # x 좌표로 정렬
        line_chars.sort(key=lambda c: c["x0"])
        
        # 중복 제거: 거리가 1~2 포인트 이내이고 같은 문자면 하나만 남기기
        filtered = []
        for char in line_chars:
            is_duplicate = False
            for existing in filtered:
                # 중심점 거리 계산
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
    """
    문자 유형 분류
    
    Returns:
        "korean": 한글
        "hanja": 한자
        "number": 숫자
        "english": 영문
        "punctuation": 구두점
        "other": 기타
    """
    if re.match(r'[가-힣]', char):
        return "korean"
    elif re.match(r'[\u4e00-\u9fff]', char):  # 한자
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
    """
    구두점/괄호 붙임 규칙 적용
    
    - 여는 괄호 ( 는 뒤 단어에 붙이기: 조( → 조(
    - 닫는 괄호 ) 는 앞 단어에 붙이기: 손해 ) → 손해)
    - 쉼표, 마침표도 앞 단어에 붙이기
    """
    # 공백 제거 후 다시 붙이기
    # 여는 괄호: 앞 공백 제거
    text = re.sub(r'\s+\(', '(', text)
    # 닫는 괄호: 뒤 공백 제거
    text = re.sub(r'\)\s+', ')', text)
    # 쉼표, 마침표: 앞 공백 제거
    text = re.sub(r'\s+([,\.])', r'\1', text)
    
    return text


def extract_text_with_font_info_from_pdf_bbox(
    pdf_path: Path, 
    pdf_bbox: List[float], 
    page_index: int = 0
) -> Dict[str, Any]:
    """
    PDF에서 지정된 bbox 영역의 텍스트와 폰트 정보를 추출
    
    Args:
        pdf_path: PDF 파일 경로
        pdf_bbox: PDF 좌표 [x1, y1, x2, y2] (포인트 단위)
        page_index: 페이지 인덱스 (0부터 시작)
    
    Returns:
        {
            "text": 추출된 텍스트,
            "font_size": 폰트 크기 (평균값, None일 수 있음),
            "is_bold": 볼드 여부 (True/False, None일 수 있음),
            "font_name": 폰트 이름 (None일 수 있음)
        }
    """
    if len(pdf_bbox) != 4:
        return {"text": "", "font_size": None, "is_bold": None, "font_name": None}
    
    try:
        doc = fitz.open(str(pdf_path))
        if page_index >= len(doc):
            doc.close()
            return {"text": "", "font_size": None, "is_bold": None, "font_name": None}
        
        page = doc[page_index]
        x1, y1, x2, y2 = pdf_bbox
        
        # PyMuPDF는 왼쪽 상단이 원점이므로 그대로 사용
        rect = fitz.Rect(x1, y1, x2, y2)
        
        # rawdict 형식으로 텍스트 블록 추출 (char 단위 bbox 포함)
        try:
            text_dict = page.get_text("rawdict", clip=rect)
        except Exception:
            # rawdict를 지원하지 않으면 dict 사용
            text_dict = page.get_text("dict", clip=rect)
        
        doc.close()
        
        # 폰트 정보 수집
        font_sizes = []
        bold_flags = []
        font_names = []
        
        # 문자(char) 단위로 추출 - 실제 char bbox 사용
        chars = []
        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    # span에서 폰트 정보 추출
                    span_size = span.get("size", None)
                    span_flags = span.get("flags", 0)
                    span_font = span.get("font", None)
                    
                    if span_size is not None:
                        font_sizes.append(span_size)
                    # flags에서 볼드 여부 확인 (비트 4 = 16 = TEXT_FONT_BOLD)
                    is_span_bold = bool(span_flags & 16) if span_flags else False
                    bold_flags.append(is_span_bold)
                    if span_font:
                        font_names.append(span_font)
                    
                    # span에 chars 속성이 있으면 실제 char bbox 사용
                    span_chars = span.get("chars", [])
                    
                    if span_chars:
                        # 실제 char 단위 bbox가 있는 경우
                        for char_info in span_chars:
                            char_text = char_info.get("c", "")  # 문자
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
                        # chars 속성이 없으면 fallback: span.text를 사용하되 실제 bbox는 span의 것
                        text = span.get("text", "")
                        bbox = span.get("bbox", [0, 0, 0, 0])
                        if len(bbox) < 4 or not text:
                            continue
                        
                        # fallback: span bbox를 사용하되, 문자 단위로 분해
                        span_x0, span_y0, span_x1, span_y1 = bbox[0], bbox[1], bbox[2], bbox[3]
                        span_width = span_x1 - span_x0
                        
                        # 균등 분배 (fallback)
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
            return {"text": "", "font_size": None, "is_bold": None, "font_name": None}
        
        # 중복 문자 제거 (overprint 대응)
        chars = _remove_duplicate_chars(chars)
        
        # y 좌표로 줄 클러스터링
        line_tolerance = 3.0  # 3 포인트 이내면 같은 줄
        lines = []
        for char in chars:
            y0 = char["y0"]
            found_line = False
            for line in lines:
                line_avg_y = line["avg_y"]
                if abs(line_avg_y - y0) <= line_tolerance:
                    line["chars"].append(char)
                    # 평균 y 좌표 업데이트
                    line["avg_y"] = sum(c["y0"] for c in line["chars"]) / len(line["chars"])
                    found_line = True
                    break
            
            if not found_line:
                lines.append({
                    "avg_y": y0,
                    "chars": [char]
                })
        
        # 각 줄 내에서 x 좌표로 정렬
        for line in lines:
            line["chars"].sort(key=lambda c: c["x0"])
        
        # 줄을 y 좌표 순으로 정렬
        lines.sort(key=lambda line: line["avg_y"])
        
        # 줄별로 텍스트 합치기
        line_texts = []
        for line in lines:
            line_chars = line["chars"]
            if not line_chars:
                continue
            
            # 문자들을 합치되, 거리를 고려하여 공백 추가
            line_parts = []
            for i, char in enumerate(line_chars):
                line_parts.append(char["char"])
                
                # 다음 문자가 있으면 거리 계산
                if i < len(line_chars) - 1:
                    next_char = line_chars[i + 1]
                    gap = next_char["x0"] - char["x1"]
                    
                    # span 내부 추정 간격 고려
                    estimated_gap = char.get("estimated_next_gap", 0)
                    if estimated_gap > 0:
                        gap = max(gap, estimated_gap)
                    
                    char_height = char["y1"] - char["y0"]
                    
                    # 같은 span 내 문자인지 확인
                    same_span = (char.get("span_origin") == next_char.get("span_origin") and
                                char.get("span_end") == next_char.get("span_end"))
                    
                    # 문자 유형 기반 단어 경계 감지
                    char_type = _get_char_type(char["char"])
                    next_char_type = _get_char_type(next_char["char"])
                    
                    # 단어 경계 패턴 감지
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
        
        # 줄들을 공백으로 합치기
        text = " ".join(line_texts)
        
        # 구두점/괄호 붙임 규칙 적용
        text = _apply_punctuation_rules(text)
        
        # 줄바꿈 문자를 공백으로 치환 후 앞뒤 공백 제거
        text = text.replace('\n', ' ').strip()
        
        # 이스케이프된 따옴표 제거
        text = text.replace('\\"', '')
        
        # 연속된 공백을 하나로 정리
        text = re.sub(r'\s+', ' ', text)
        
        # 폰트 정보 계산
        avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else None
        # 대부분이 볼드이면 볼드로 간주
        is_bold = True if bold_flags and sum(bold_flags) > len(bold_flags) * 0.5 else False if bold_flags else None
        # 가장 많이 사용된 폰트 이름
        font_name = max(set(font_names), key=font_names.count) if font_names else None
        
        return {
            "text": text,
            "font_size": round(avg_font_size, 2) if avg_font_size else None,
            "is_bold": is_bold,
            "font_name": font_name
        }
    except Exception as e:
        logger.error(f"텍스트 추출 실패 ({pdf_path}, page {page_index}): {e}", exc_info=True)
        return {"text": "", "font_size": None, "is_bold": None, "font_name": None}


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
        
        # rawdict 형식으로 텍스트 블록 추출 (char 단위 bbox 포함)
        # rawdict는 더 세밀한 정보를 제공하지만, 없으면 dict로 fallback
        try:
            text_dict = page.get_text("rawdict", clip=rect)
        except Exception:
            # rawdict를 지원하지 않으면 dict 사용
            text_dict = page.get_text("dict", clip=rect)
        
        doc.close()
        
        # 문자(char) 단위로 추출 - 실제 char bbox 사용
        chars = []
        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    # span에 chars 속성이 있으면 실제 char bbox 사용
                    span_chars = span.get("chars", [])
                    
                    if span_chars:
                        # 실제 char 단위 bbox가 있는 경우
                        for char_info in span_chars:
                            char_text = char_info.get("c", "")  # 문자
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
                        # chars 속성이 없으면 fallback: span.text를 사용하되 실제 bbox는 span의 것
                        text = span.get("text", "")
                        bbox = span.get("bbox", [0, 0, 0, 0])
                        if len(bbox) < 4 or not text:
                            continue
                        
                        # fallback: span bbox를 사용하되, 문자 단위로 분해
                        span_x0, span_y0, span_x1, span_y1 = bbox[0], bbox[1], bbox[2], bbox[3]
                        span_width = span_x1 - span_x0
                        
                        # 균등 분배 (fallback)
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
            return ""
        
        # 중복 문자 제거 (overprint 대응)
        # 같은 줄에서 거의 같은 위치에 같은 문자가 있으면 하나만 남기기
        chars = _remove_duplicate_chars(chars)
        
        # y 좌표로 줄 클러스터링
        line_tolerance = 3.0  # 3 포인트 이내면 같은 줄
        lines = []
        for char in chars:
            y0 = char["y0"]
            found_line = False
            for line in lines:
                line_avg_y = line["avg_y"]
                if abs(line_avg_y - y0) <= line_tolerance:
                    line["chars"].append(char)
                    # 평균 y 좌표 업데이트
                    line["avg_y"] = sum(c["y0"] for c in line["chars"]) / len(line["chars"])
                    found_line = True
                    break
            
            if not found_line:
                lines.append({
                    "avg_y": y0,
                    "chars": [char]
                })
        
        # 각 줄 내에서 x 좌표로 정렬
        for line in lines:
            line["chars"].sort(key=lambda c: c["x0"])
        
        # 줄을 y 좌표 순으로 정렬
        lines.sort(key=lambda line: line["avg_y"])
        
        # 줄별로 텍스트 합치기
        line_texts = []
        for line in lines:
            line_chars = line["chars"]
            if not line_chars:
                continue
            
            # 문자들을 합치되, 거리를 고려하여 공백 추가
            line_parts = []
            for i, char in enumerate(line_chars):
                line_parts.append(char["char"])
                
                # 다음 문자가 있으면 거리 계산
                if i < len(line_chars) - 1:
                    next_char = line_chars[i + 1]
                    gap = next_char["x0"] - char["x1"]
                    
                    # span 내부 추정 간격 고려
                    estimated_gap = char.get("estimated_next_gap", 0)
                    if estimated_gap > 0:
                        # span 내부 간격이 추정되면, 실제 gap에 더해줌
                        gap = max(gap, estimated_gap)
                    
                    # 거리 계산 개선:
                    # 1. 같은 span 내 문자 vs 다른 span 문자 구분
                    # 2. span 간 거리가 더 크면 공백 추가
                    # 3. 문자 유형 기반 단어 경계 감지
                    char_height = char["y1"] - char["y0"]
                    
                    # 같은 span 내 문자인지 확인
                    same_span = (char.get("span_origin") == next_char.get("span_origin") and
                                char.get("span_end") == next_char.get("span_end"))
                    
                    # 문자 유형 기반 단어 경계 감지
                    # 예: "조" (한글) 다음에 "자" (한글)가 오는데 거리가 있으면 단어 경계일 수 있음
                    char_type = _get_char_type(char["char"])
                    next_char_type = _get_char_type(next_char["char"])
                    
                    # 단어 경계 패턴 감지 (한글+숫자+한글, 한글+한글 등)
                    is_word_boundary = False
                    if char_type == "korean" and next_char_type == "korean":
                        # 한글-한글: 거리가 폰트 크기의 40% 이상이면 단어 경계 가능
                        if gap > char_height * 0.4:
                            is_word_boundary = True
                    elif char_type in ["korean", "hanja"] and next_char_type in ["korean", "hanja"]:
                        # 한글/한자-한글/한자: 거리가 폰트 크기의 35% 이상이면 단어 경계 가능
                        if gap > char_height * 0.35:
                            is_word_boundary = True
                    
                    if same_span:
                        # 같은 span 내: 
                        # - span 내부 간격이 추정되면 더 관대하게 (폰트 크기의 20% 이상)
                        # - 단어 경계가 감지되면 폰트 크기의 25% 이상이면 공백
                        # - 아니면 폰트 크기의 40% 이상이면 공백
                        if estimated_gap > 0:
                            gap_threshold = max(1.5, char_height * 0.2)
                        elif is_word_boundary:
                            gap_threshold = max(2.0, char_height * 0.25)
                        else:
                            gap_threshold = max(2.0, char_height * 0.4)
                    else:
                        # 다른 span: 폰트 크기의 20% 이상이면 공백 (더 관대)
                        gap_threshold = max(1.5, char_height * 0.2)
                    
                    if gap > gap_threshold:
                        line_parts.append(" ")
            
            line_text = "".join(line_parts)
            line_texts.append(line_text)
        
        # 줄들을 공백으로 합치기
        text = " ".join(line_texts)
        
        # 구두점/괄호 붙임 규칙 적용
        text = _apply_punctuation_rules(text)
        
        # 줄바꿈 문자를 공백으로 치환 후 앞뒤 공백 제거
        text = text.replace('\n', ' ').strip()
        
        # 이스케이프된 따옴표 제거
        text = text.replace('\\"', '')
        
        # 연속된 공백을 하나로 정리
        text = re.sub(r'\s+', ' ', text)
        
        return text
    except Exception as e:
        logger.error(f"텍스트 추출 실패 ({pdf_path}, page {page_index}): {e}", exc_info=True)
        return ""


def extract_texts_with_font_info_from_pdf_bboxes(
    pdf_path: Path,
    pdf_bboxes: List[List[float]],
    page_index: int = 0
) -> List[Dict[str, Any]]:
    """
    PDF에서 여러 bbox 영역의 텍스트와 폰트 정보를 한번에 추출 (PDF 파일을 한 번만 열기)
    
    Args:
        pdf_path: PDF 파일 경로
        pdf_bboxes: PDF 좌표 리스트 [[x1, y1, x2, y2], ...]
        page_index: 페이지 인덱스 (0부터 시작)
    
    Returns:
        추출된 텍스트와 폰트 정보 리스트 (각 항목은 {"text", "font_size", "is_bold", "font_name"} 포함)
    """
    if not pdf_bboxes:
        return []
    
    try:
        results = []
        
        for pdf_bbox in pdf_bboxes:
            if len(pdf_bbox) != 4:
                results.append({"text": "", "font_size": None, "is_bold": None, "font_name": None})
                continue
            
            # extract_text_with_font_info_from_pdf_bbox를 재사용
            result = extract_text_with_font_info_from_pdf_bbox(pdf_path, pdf_bbox, page_index)
            results.append(result)
        return results
    except Exception as e:
        logger.error(f"텍스트 추출 실패 ({pdf_path}, page {page_index}): {e}", exc_info=True)
        return [{"text": "", "font_size": None, "is_bold": None, "font_name": None}] * len(pdf_bboxes)


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
        texts = []
        
        for pdf_bbox in pdf_bboxes:
            if len(pdf_bbox) != 4:
                texts.append("")
                continue
            
            # extract_text_from_pdf_bbox를 재사용 (코드 중복 방지)
            text = extract_text_from_pdf_bbox(pdf_path, pdf_bbox, page_index)
            texts.append(text)
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
    text_block_labels = ["doc_title", "paragraph_title", "text", "figure_title", "header", 'vision_footnote']
    
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
    
    # 한번에 모든 텍스트 및 폰트 정보 추출 (PDF 파일을 한 번만 열기)
    if text_block_bboxes:
        text_font_infos = extract_texts_with_font_info_from_pdf_bboxes(pdf_path, text_block_bboxes, page_index=0)
        
        # 추출된 텍스트와 폰트 정보를 블록에 할당
        for idx, info in zip(text_block_indices, text_font_infos):
            parsing_res_list[idx]["block_content"] = info.get("text", "")
            # 폰트 정보 추가
            if info.get("font_size") is not None:
                parsing_res_list[idx]["font_size"] = info["font_size"]
            if info.get("is_bold") is not None:
                parsing_res_list[idx]["is_bold"] = info["is_bold"]
            if info.get("font_name"):
                parsing_res_list[idx]["font_name"] = info["font_name"]
    
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