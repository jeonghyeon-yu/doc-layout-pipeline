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
        
        # dict 형식으로 텍스트 블록 추출 (좌표 정보 포함)
        text_dict = page.get_text("dict", clip=rect)
        
        doc.close()
        
        # 문자(char) 단위로 추출
        chars = []
        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    bbox = span.get("bbox", [0, 0, 0, 0])
                    if len(bbox) < 4 or not text:
                        continue
                    
                    span_x0, span_y0, span_x1, span_y1 = bbox[0], bbox[1], bbox[2], bbox[3]
                    span_width = span_x1 - span_x0
                    
                    # span의 텍스트를 문자 단위로 분해
                    # 각 문자의 위치를 span 내에서 추정
                    char_width = span_width / len(text) if len(text) > 0 else 0
                    
                    for i, char in enumerate(text):
                        # 각 문자의 x 좌표 추정 (span 내에서 균등 분배)
                        char_x0 = span_x0 + (i * char_width)
                        char_x1 = span_x0 + ((i + 1) * char_width)
                        char_y0 = span_y0
                        char_y1 = span_y1
                        
                        chars.append({
                            "char": char,
                            "x0": char_x0,
                            "y0": char_y0,
                            "x1": char_x1,
                            "y1": char_y1,
                            "center_x": (char_x0 + char_x1) / 2,
                            "center_y": (char_y0 + char_y1) / 2
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
                    
                    # 거리가 일정 이상이면 공백 추가
                    if gap > 2.0:
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
    text_block_labels = ["doc_title", "paragraph_title", "text", "figure_title", "header", "footer", 'vision_footnote', 'number']
    
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