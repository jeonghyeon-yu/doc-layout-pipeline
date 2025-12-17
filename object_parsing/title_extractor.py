import json
from pathlib import Path
from typing import List, Dict, Any
import re


def get_rank(value: float, sorted_values: List[float], threshold: float = 5) -> int:
    """
    값의 순위 계산 (1부터 시작)
    비슷한 값(±threshold)은 같은 순위
    """
    rank = 1
    prev_val = None
    
    for val in sorted_values:
        if prev_val is not None and val - prev_val > threshold:
            rank += 1
        if abs(value - val) <= threshold:
            return rank
        prev_val = val
    
    return rank


def extract_titles_from_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    단일 JSON 파일에서 doc_title, paragraph_title, figure_title만 추출
    """
    titles = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        page_index = data.get('page_index', -1)
        pdf_width = data.get('pdf_width', None)
        pdf_height = data.get('pdf_height', None)
        parsing_res_list = data.get('parsing_res_list', [])
        
        for block in parsing_res_list:
            block_label = block.get('block_label', '')
            block_content = block.get('block_content', '').strip()
            block_order = block.get('block_order', 0)
            pdf_bbox = block.get('pdf_bbox', None)
            
            if block_label in ['doc_title', 'paragraph_title', 'figure_title']:
                if block_content:
                    title_info = {
                        'page_index': page_index,
                        'block_order': block_order,
                        'block_label': block_label,
                        'block_content': block_content,
                        'file_name': file_path.name,
                        'pdf_bbox': pdf_bbox
                    }
                    
                    if pdf_width is not None:
                        title_info['pdf_width'] = pdf_width
                    if pdf_height is not None:
                        title_info['pdf_height'] = pdf_height
                    
                    titles.append(title_info)
                    
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        
    return titles


def extract_all_blocks_from_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    단일 JSON 파일에서 모든 블록의 좌표 정보 추출 (레이아웃 분석용)
    """
    blocks = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        page_index = data.get('page_index', -1)
        
        for block in data.get('parsing_res_list', []):
            if block.get('pdf_bbox'):
                blocks.append({
                    'block_label': block.get('block_label'),
                    'pdf_bbox': block.get('pdf_bbox'),
                    'page_index': page_index
                })
                
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
    
    return blocks


def get_sorted_files(directory: Path) -> List[Path]:
    """
    디렉토리에서 page_*.json 파일들을 페이지 순서대로 정렬
    """
    files = []
    pattern = re.compile(r'page_(\d+)_\d+_res\.json')
    
    for file_path in directory.glob('page_*_res.json'):
        match = pattern.match(file_path.name)
        if match:
            page_num = int(match.group(1))
            files.append((page_num, file_path))
    
    files.sort(key=lambda x: x[0])
    return [file_path for _, file_path in files]


def process_directory(directory_path: str) -> tuple[List[Dict[str, Any]], Dict[int, Dict]]:
    """
    디렉토리 처리 - 타이틀 추출 + 페이지별 전체 블록 좌표 수집
    
    Returns:
        (타이틀 리스트, 페이지별 블록 좌표 딕셔너리)
    """
    directory = Path(directory_path)
    
    if not directory.exists():
        raise ValueError(f"Directory does not exist: {directory_path}")
    
    all_titles = []
    page_blocks = {}  # {page_index: [blocks]}
    
    sorted_files = get_sorted_files(directory)
    print(f"Found {len(sorted_files)} files to process...")
    
    for file_path in sorted_files:
        # 타이틀 추출
        titles = extract_titles_from_file(file_path)
        all_titles.extend(titles)
        
        # 전체 블록 좌표 추출 (페이지별)
        blocks = extract_all_blocks_from_file(file_path)
        for block in blocks:
            page_idx = block['page_index']
            if page_idx not in page_blocks:
                page_blocks[page_idx] = []
            page_blocks[page_idx].append(block)
    
    all_titles.sort(key=lambda x: (x['page_index'], x['block_order']))
    
    return all_titles, page_blocks


def analyze_page_layout(blocks: List[Dict[str, Any]]) -> Dict[str, List[float]]:
    """
    단일 페이지의 레이아웃 분석 - x, y 좌표 정렬 리스트 반환
    """
    x_positions = []
    y_positions = []
    
    for block in blocks:
        if block.get('pdf_bbox'):
            x_positions.append(block['pdf_bbox'][0])
            y_positions.append(block['pdf_bbox'][1])
    
    return {
        'x_sorted': sorted(x_positions),
        'y_sorted': sorted(y_positions)
    }


def add_depths_to_titles(titles: List[Dict[str, Any]], page_blocks: Dict[int, List]) -> List[Dict[str, Any]]:
    """
    각 타이틀에 페이지별 x_depth, y_depth 추가 (순위 기반, 1부터 시작)
    """
    # 페이지별 레이아웃 분석 캐시
    page_layouts = {}
    
    for title in titles:
        page_idx = title['page_index']
        
        # 해당 페이지 레이아웃 분석 (캐시)
        if page_idx not in page_layouts:
            blocks = page_blocks.get(page_idx, [])
            page_layouts[page_idx] = analyze_page_layout(blocks)
        
        layout = page_layouts[page_idx]
        
        if title.get('pdf_bbox'):
            x0 = title['pdf_bbox'][0]
            y0 = title['pdf_bbox'][1]
            
            title['x_depth'] = get_rank(x0, layout['x_sorted'])
            title['y_depth'] = get_rank(y0, layout['y_sorted'])
        else:
            title['x_depth'] = 0
            title['y_depth'] = 0
    
    return titles


def save_to_json(data: Any, output_path: str):
    """JSON 파일로 저장"""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"Saved to {output_path}")


def print_titles_summary(titles: List[Dict[str, Any]]):
    """추출된 타이틀들의 요약 정보 출력"""
    print("\n=== 타이틀 추출 요약 ===")
    print(f"총 추출된 타이틀 수: {len(titles)}")
    
    # 타입별 개수
    type_counts = {}
    for title in titles:
        label = title['block_label']
        type_counts[label] = type_counts.get(label, 0) + 1
    
    print("\n타입별 개수:")
    for label, count in sorted(type_counts.items()):
        print(f"  {label}: {count}개")
    
    # 페이지별 샘플 출력
    print("\n=== 페이지별 타이틀 (depth = 페이지 내 순위) ===")
    
    current_page = None
    count = 0
    max_display = 30
    
    for title in titles:
        if count >= max_display:
            break
            
        page = title['page_index']
        if page != current_page:
            current_page = page
            print(f"\n[페이지 {page}]")
        
        x_d = title.get('x_depth', '?')
        y_d = title.get('y_depth', '?')
        label = title['block_label'][:3]  # doc, par, fig
        content = title['block_content'][:40]
        
        print(f"  [x:{x_d:2}, y:{y_d:2}] ({label}) {content}")
        count += 1
    
    if len(titles) > max_display:
        print(f"\n... 외 {len(titles) - max_display}개 더")


def main():
    """메인 함수"""
    # 입력 디렉토리
    input_directory = r"C:\Users\bigda\Desktop\graph_rag\output\work\layout_parsing_output\parsing_results"
    
    # 출력 파일
    output_titles = r"C:\Users\bigda\Desktop\graph_rag\output\work\extracted_titles.json"
    
    print("=" * 60)
    print("문서 타이틀 추출 (페이지별 depth 순위)")
    print("=" * 60)
    print(f"입력: {input_directory}")
    
    # 1. 타이틀 + 페이지별 블록 추출
    print("\n[1/2] 데이터 추출 중...")
    titles, page_blocks = process_directory(input_directory)
    print(f"  → 타이틀: {len(titles)}개")
    print(f"  → 페이지: {len(page_blocks)}개")
    
    # 2. 페이지별 depth 계산
    print("\n[2/2] 페이지별 depth 계산 중...")
    titles = add_depths_to_titles(titles, page_blocks)
    
    # 요약 출력
    print_titles_summary(titles)
    
    # 저장
    save_to_json(titles, output_titles)
    
    print("\n" + "=" * 60)
    print("완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()