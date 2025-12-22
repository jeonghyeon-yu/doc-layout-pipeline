"""
JSON 파싱 결과를 HTML로 변환하는 모듈
text_extractor와 vlm_image_extractor 이후에 실행되어 block_content가 채워진 JSON을 HTML로 변환
"""
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


def save_json_to_html(data: dict, html_path: Path) -> None:
    """
    JSON 데이터를 HTML 형식으로 저장
    
    Args:
        data: JSON 데이터 딕셔너리
        html_path: 저장할 HTML 파일 경로
    """
    try:
        page_index = data.get("page_index", 0)
        page_count = data.get("page_count", 0)
        parsing_res_list = data.get("parsing_res_list", [])
        
        # block_order 기준으로 정렬
        def get_sort_key(block):
            block_order = block.get("block_order")
            if block_order is not None:
                return (0, block_order)  # block_order가 있으면 우선순위 0
            # block_order가 없으면 block_id로 정렬
            return (1, block.get("block_id", 0))
        
        # 정렬된 블록 리스트
        sorted_blocks = sorted(parsing_res_list, key=get_sort_key)
        
        # HTML 이스케이프 함수
        def escape_html(text):
            if text is None:
                return ""
            return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
        
        # HTML 헤더
        html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>레이아웃 파싱 결과 - 페이지 {page_index + 1}/{page_count}</title>
    <style>
        body {{
            font-family: 'Malgun Gothic', '맑은 고딕', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .page-container {{
            max-width: 800px;
            margin: 0 auto;
            background-color: white;
            padding: 40px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .page-header {{
            font-size: 12px;
            color: #666;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #ddd;
        }}
        .block {{
            margin-bottom: 20px;
            padding: 10px;
            border-left: 3px solid transparent;
            position: relative;
        }}
        .block:hover {{
            background-color: #f9f9f9;
            border-left-color: #2196F3;
        }}
        .block-label {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-weight: bold;
            font-size: 10px;
            margin-right: 8px;
            vertical-align: middle;
        }}
        .block-label.text {{ background-color: #2196F3; color: white; }}
        .block-label.paragraph_title {{ background-color: #FF9800; color: white; }}
        .block-label.doc_title {{ background-color: #9C27B0; color: white; }}
        .block-label.figure_title {{ background-color: #00BCD4; color: white; }}
        .block-label.header {{ background-color: #607D8B; color: white; }}
        .block-label.footer {{ background-color: #795548; color: white; }}
        .block-label.table {{ background-color: #4CAF50; color: white; }}
        .block-label.chart {{ background-color: #8BC34A; color: white; }}
        .block-label.figure {{ background-color: #CDDC39; color: #333; }}
        .block-label.image {{ background-color: #FFC107; color: #333; }}
        .block-label.formula {{ background-color: #FF5722; color: white; }}
        .block-label.number {{ background-color: #9E9E9E; color: white; }}
        .block-label.footnote {{ background-color: #E91E63; color: white; }}
        .block-label.vision_footnote {{ background-color: #E91E63; color: white; }}
        .block-content {{
            margin-top: 8px;
            white-space: pre-wrap;
            word-wrap: break-word;
            line-height: 1.6;
        }}
        .paragraph_title .block-content {{
            font-weight: bold;
            font-size: 1.2em;
            margin-top: 4px;
        }}
        .text .block-content {{
            text-align: justify;
        }}
        .footnote .block-content {{
            font-size: 0.9em;
            color: #666;
            font-style: italic;
        }}
    </style>
</head>
<body>
    <div class="page-container">
        <div class="page-header">페이지 {page_index + 1} / {page_count} | 블록 수: {len(parsing_res_list)}개</div>
"""
        
        # 블록별 HTML 생성 (block_order 순서대로)
        for idx, block in enumerate(sorted_blocks):
            block_label = block.get("block_label", "unknown")
            block_content = block.get("block_content", "")
            block_id = block.get("block_id", idx)
            block_order = block.get("block_order")
            
            # 블록 내용이 없으면 스킵하지 않고 표시
            if not block_content and block_label not in ["number", "footnote"]:
                block_content = "(내용 없음)"
            
            html_content += f"""
        <div class="block {block_label}">
            <div>
                <span class="block-label {block_label}">{escape_html(block_label)}</span>
                {f'<span style="color: #999; font-size: 11px;">(Order: {block_order}, ID: {block_id})</span>' if block_order is not None else f'<span style="color: #999; font-size: 11px;">(ID: {block_id})</span>'}
            </div>
            <div class="block-content">{escape_html(block_content)}</div>
        </div>
"""
        
        # HTML 푸터
        html_content += """
    </div>
</body>
</html>"""
        
        # HTML 파일 저장
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.debug(f"HTML 파일 생성: {html_path.name}")
    except Exception as e:
        logger.warning(f"HTML 파일 생성 실패 ({html_path}): {e}")


def generate_html_from_json_files(parsing_results_dir: Path) -> int:
    """
    parsing_results_dir 내의 모든 JSON 파일을 HTML로 변환
    
    Args:
        parsing_results_dir: JSON 파일들이 있는 디렉토리
        
    Returns:
        생성된 HTML 파일 수
    """
    if not parsing_results_dir.exists():
        logger.warning(f"디렉토리가 존재하지 않습니다: {parsing_results_dir}")
        return 0
    
    json_files = sorted(parsing_results_dir.glob("*_res.json"))
    
    if not json_files:
        logger.warning(f"JSON 파일을 찾을 수 없습니다: {parsing_results_dir}")
        return 0
    
    logger.info(f"HTML 생성 시작: {len(json_files)}개 JSON 파일 처리")
    
    generated_count = 0
    for json_file in json_files:
        try:
            # JSON 파일 읽기
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # HTML 파일 경로 생성
            html_path = json_file.with_suffix('.html')
            
            # HTML 생성
            save_json_to_html(data, html_path)
            generated_count += 1
            
        except Exception as e:
            logger.error(f"HTML 생성 실패 ({json_file.name}): {e}")
    
    logger.info(f"✅ HTML 생성 완료: {generated_count}개 파일 생성")
    return generated_count

