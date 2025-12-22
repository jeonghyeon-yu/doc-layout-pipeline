"""VLM을 사용한 table, chart, figure 처리 (이미 추출된 이미지 사용)"""
from pathlib import Path
from typing import List, Dict, Optional
import json
import logging
import sys
from PIL import Image

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 프로젝트 루트를 경로에 추가 (vlm_server 모듈 import용)
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# VLM 클라이언트 import
try:
    from services.vlm_server.qwen3_vl_client import create_qwen3vl_client, Qwen3VLClient
except ImportError:
    logger.warning("VLM 클라이언트를 import할 수 없습니다. VLM 처리가 비활성화됩니다.")
    Qwen3VLClient = None
    create_qwen3vl_client = None


# 기본 VLM 프롬프트 (사용자가 커스터마이즈 가능)
DEFAULT_VLM_PROMPTS = {
    "table": """이 이미지는 문서의 테이블입니다. 
테이블의 모든 내용을 정확하게 markdown 형식의 테이블로 변환해주세요.
헤더와 모든 행, 열의 데이터를 포함해야 합니다.
순수 markdown 테이블 형식으로만 응답해주세요 (코드 블록 없이).""",
    
    "chart": """이 이미지는 문서의 차트입니다.
차트의 주요 내용, 데이터 트렌드, 중요한 인사이트를 요약해주세요.
한국어로 작성해주세요.""",
    
    "figure": """이 이미지는 문서의 그림 또는 도표입니다.
그림의 주요 내용과 의미를 요약해주세요.
한국어로 작성해주세요.""",
    
    "image": """이 이미지는 문서에 포함된 이미지입니다.
이미지의 주요 내용과 의미를 설명해주세요.
한국어로 작성해주세요.""",
    
    "formula": """이 이미지는 문서의 수식입니다.
수식을 정확하게 LaTeX 형식으로만 변환해주세요.
LaTeX 코드만 반환하고, 설명이나 다른 텍스트는 포함하지 마세요.
예: $E = mc^2$ 또는 \\[\\int_{0}^{\\infty} e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}\\]
응답은 LaTeX 수식 코드만 포함해야 합니다."""
}


def collect_all_vlm_images(
    vlm_images_dir: Path,
    block_label: Optional[str] = None
) -> List[Dict[str, any]]:
    """
    vlm_images 폴더의 타입별 하위 폴더(vlm_images/table/, vlm_images/chart/, vlm_images/figure/, vlm_images/image/, vlm_images/formula/)에서 
    모든 VLM 이미지 파일을 수집 (배치 처리 시 사용)
    
    Args:
        vlm_images_dir: vlm_images 디렉토리 경로 (vlm_images/table/, vlm_images/chart/, vlm_images/figure/, vlm_images/image/, vlm_images/formula/ 포함)
        block_label: 특정 타입만 수집 (None이면 모든 타입)
    
    Returns:
        [{"block_label": "table", "block_id": "page_0001_0_res_block_0", 
          "img_path": Path, "json_stem": "page_0001_0_res", "block_idx": 0}, ...]
        block_label는 "table", "chart", "figure", "image", "formula" 중 하나
    """
    vlm_block_labels = ["table", "chart", "figure", "image", "formula"] if block_label is None else [block_label]
    collected_images = []
    
    for label in vlm_block_labels:
        type_dir = vlm_images_dir / label  # vlm_images/table, vlm_images/chart, vlm_images/figure
        if not type_dir.exists():
            logger.debug(f"이미지 디렉토리 없음: {type_dir}")
            continue
        
        logger.debug(f"이미지 디렉토리 확인: {type_dir}")
        # 해당 폴더의 모든 PNG 파일 찾기
        png_files = list(sorted(type_dir.glob("*.png")))
        logger.info(f"  {label} 폴더에서 {len(png_files)}개 이미지 발견")
        for img_path in png_files:
            # block_id 추출: 파일명에서 확장자 제거
            block_id = img_path.stem  # 예: "page_0001_0_res_block_0"
            
            # JSON 파일명과 block_idx 추출
            if "_block_" in block_id:
                json_stem = "_".join(block_id.split("_block_")[:-1])  # "page_0001_0_res"
                block_idx_str = block_id.split("_block_")[-1]  # "0"
                try:
                    block_idx = int(block_idx_str)
                except ValueError:
                    block_idx = -1
            else:
                json_stem = block_id
                block_idx = -1
            
            collected_images.append({
                "block_label": label,
                "block_id": block_id,
                "img_path": img_path,
                "json_stem": json_stem,
                "block_idx": block_idx
            })
    
    return collected_images


def create_vlm_functions_from_client(
    vlm_client: Qwen3VLClient,
    prompts: Optional[Dict[str, str]] = None
) -> Dict[str, callable]:
    """
    VLM 클라이언트로부터 블록 타입별 처리 함수 생성
    
    Args:
        vlm_client: Qwen3VLClient 인스턴스
        prompts: 블록 타입별 프롬프트 딕셔너리 (선택사항)
            예: {"table": "테이블 프롬프트", "chart": "차트 프롬프트", "figure": "그림 프롬프트", "image": "이미지 프롬프트", "formula": "수식 프롬프트"}
            None이면 클라이언트의 기본 프롬프트 사용
    
    Returns:
        {"table": table_func, "chart": chart_func, "figure": figure_func, "image": image_func, "formula": formula_func} 딕셔너리
    """
    if vlm_client is None:
        logger.warning("VLM 클라이언트가 None입니다. 더미 함수를 반환합니다.")
        def dummy_func(img: Image.Image) -> str:
            return "[VLM 클라이언트 없음]"
        return {
            "table": dummy_func,
            "chart": dummy_func,
            "figure": dummy_func,
            "image": dummy_func,
            "formula": dummy_func
        }
    
    # 프롬프트가 제공되면 사용, 없으면 None (클라이언트 기본값 사용)
    table_prompt = prompts.get("table") if prompts and "table" in prompts else None
    chart_prompt = prompts.get("chart") if prompts and "chart" in prompts else None
    figure_prompt = prompts.get("figure") if prompts and "figure" in prompts else None
    image_prompt = prompts.get("image") if prompts and "image" in prompts else None
    formula_prompt = prompts.get("formula") if prompts and "formula" in prompts else None
    
    return {
        "table": lambda img: vlm_client.process_table(img, prompt=table_prompt),
        "chart": lambda img: vlm_client.process_chart(img, prompt=chart_prompt),
        "figure": lambda img: vlm_client.process_figure(img, prompt=figure_prompt),
        "image": lambda img: vlm_client.process_image(img, prompt=image_prompt),
        "formula": lambda img: vlm_client.process_formula(img, prompt=formula_prompt)
    }


def process_vlm_blocks_from_images(
    parsing_results_dir: Path,
    vlm_images_dir: Path,
    vlm_functions: Dict[str, callable] = None,
    vlm_client: Qwen3VLClient = None,
    vlm_api_base: str = "http://localhost:8888/v1",
    vlm_api_key: Optional[str] = "optional-api-key-here",
    vlm_prompts: Optional[Dict[str, str]] = None,
    output_dir: Path = None,
    batch_size: int = 1
) -> List[Path]:
    """
    이미 추출된 이미지 파일들을 읽어서 VLM 처리하고 JSON 업데이트
    (vlm_images/{block_label}/ 폴더에서 이미지 읽기)
    
    Args:
        parsing_results_dir: 레이아웃 파싱 결과 JSON 파일들이 있는 디렉토리
        vlm_images_dir: vlm_images 디렉토리 경로 (vlm_images/table/, vlm_images/chart/, vlm_images/figure/, vlm_images/image/, vlm_images/formula/ 포함)
        vlm_functions: 블록 타입별 VLM 처리 함수 딕셔너리 (선택사항)
            예: {"table": table_vlm_func, "chart": chart_vlm_func, "figure": figure_vlm_func, "image": image_vlm_func, "formula": formula_vlm_func}
        vlm_client: Qwen3VLClient 인스턴스 (vlm_functions가 None일 때 사용)
        vlm_api_base: VLM API 베이스 URL (vlm_client가 None일 때 자동 생성)
        vlm_api_key: VLM API 키 (기본값: "optional-api-key-here", docker-compose.yml의 --api-key와 일치해야 함)
        vlm_prompts: 블록 타입별 프롬프트 딕셔너리 (선택사항)
            예: {"table": "테이블 프롬프트", "chart": "차트 프롬프트", "figure": "그림 프롬프트"}
            None이면 클라이언트의 기본 프롬프트 사용
        output_dir: 출력 디렉토리 (None이면 원본 파일 덮어쓰기)
        batch_size: 배치 처리 크기 (1이면 개별 처리, >1이면 배치 처리)
    
    Returns:
        처리된 JSON 파일 경로 리스트
    """
    # VLM 함수가 제공되지 않았으면 클라이언트로부터 생성
    if vlm_functions is None:
        if vlm_client is None:
            if Qwen3VLClient is None:
                logger.error("VLM 클라이언트를 사용할 수 없습니다. VLM 처리를 건너뜁니다.")
                return []
            logger.info(f"VLM 클라이언트 생성: {vlm_api_base} (API 키: {'설정됨' if vlm_api_key else '없음'})")
            vlm_client = create_qwen3vl_client(api_base=vlm_api_base, api_key=vlm_api_key)
        
        # 프롬프트가 제공되지 않았으면 기본 프롬프트 사용
        if vlm_prompts is None:
            vlm_prompts = DEFAULT_VLM_PROMPTS
            logger.info("기본 VLM 프롬프트 사용")
        else:
            # 제공된 프롬프트와 기본 프롬프트 병합 (제공된 것이 우선)
            merged_prompts = DEFAULT_VLM_PROMPTS.copy()
            merged_prompts.update(vlm_prompts)
            vlm_prompts = merged_prompts
            logger.info("커스텀 VLM 프롬프트 사용")
        
        vlm_functions = create_vlm_functions_from_client(vlm_client, prompts=vlm_prompts)
        logger.info("VLM 함수 생성 완료")
    # JSON 파일들 찾기
    json_files = sorted(parsing_results_dir.glob("*_res.json"))
    
    if not json_files:
        logger.warning(f"JSON 파일을 찾을 수 없습니다: {parsing_results_dir}")
        return []
    
    if not vlm_functions:
        logger.warning("VLM 함수가 제공되지 않았습니다. 이미지만 확인합니다.")
    
    logger.info(f"VLM 처리 시작: {len(json_files)}개 JSON 파일")
    logger.info(f"이미지 디렉토리: {vlm_images_dir}")
    logger.info(f"배치 크기: {batch_size} (1이면 개별 처리, >1이면 배치 처리)")
    
    # 배치 처리 모드: 모든 이미지를 먼저 수집
    if batch_size > 1:
        logger.info("배치 처리 모드: 모든 이미지 수집 중...")
        logger.info(f"이미지 디렉토리 확인: {vlm_images_dir}")
        if not vlm_images_dir.exists():
            logger.error(f"VLM 이미지 디렉토리가 존재하지 않습니다: {vlm_images_dir}")
            return []
        all_images = collect_all_vlm_images(vlm_images_dir)
        logger.info(f"이미지 수집 완료: {len(all_images)}개 (vlm_images/{{table,chart,figure,image,formula}}/ 폴더에서)")
        if len(all_images) == 0:
            logger.warning("처리할 VLM 이미지가 없습니다. 이미지 추출 단계를 먼저 실행하세요.")
            return []
        
        # JSON 파일들을 먼저 모두 로드 (중복 읽기 방지)
        json_data_cache = {}
        for json_file in json_files:
            with open(json_file, 'r', encoding='utf-8') as f:
                json_data_cache[json_file.stem] = json.load(f)
        
        # 배치 단위로 처리
        for i in range(0, len(all_images), batch_size):
            batch = all_images[i:i+batch_size]
            logger.info(f"배치 {i//batch_size + 1}/{(len(all_images) + batch_size - 1)//batch_size} 처리 중... ({len(batch)}개 이미지)")
            
            for img_info in batch:
                block_label = img_info["block_label"]
                block_id = img_info["block_id"]
                img_path = img_info["img_path"]
                json_stem = img_info["json_stem"]
                block_idx = img_info["block_idx"]
                
                # JSON 파일 찾기 (json_stem이 이미 page_0001_0_res 형식이므로 .json만 추가)
                json_file = parsing_results_dir / f"{json_stem}.json"
                if not json_file.exists():
                    # 다른 패턴 시도 (기존 패턴: {json_stem}_0_res.json도 확인)
                    json_file_alt = parsing_results_dir / f"{json_stem}_0_res.json"
                    if json_file_alt.exists():
                        json_file = json_file_alt
                        logger.debug(f"JSON 파일 찾음 (대체 패턴): {json_file.name}")
                    else:
                        # glob으로 패턴 매칭 시도
                        json_files_matching = list(parsing_results_dir.glob(f"{json_stem}*_res.json"))
                        if json_files_matching:
                            json_file = json_files_matching[0]
                            logger.debug(f"JSON 파일 찾음 (glob 패턴): {json_file.name}")
                        else:
                            logger.warning(f"JSON 파일을 찾을 수 없습니다: {json_stem}")
                            logger.debug(f"  검색 디렉토리: {parsing_results_dir}")
                            available_files = list(parsing_results_dir.glob("*_res.json"))
                            logger.debug(f"  사용 가능한 JSON 파일 ({len(available_files)}개): {[f.name for f in available_files[:10]]}")
                            continue
                else:
                    logger.debug(f"JSON 파일 찾음: {json_file.name}")
                
                # 캐시에서 JSON 데이터 가져오기
                json_key = json_file.stem
                if json_key not in json_data_cache:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        json_data_cache[json_key] = json.load(f)
                
                data = json_data_cache[json_key]
                parsing_res_list = data.get("parsing_res_list", [])
                
                # block_idx로 블록 찾기
                if 0 <= block_idx < len(parsing_res_list):
                    block = parsing_res_list[block_idx]
                    if block.get("block_label") == block_label:
                        try:
                            img = Image.open(img_path)
                            logger.debug(f"이미지 로드 완료: {img_path.name} ({img.size})")
                            
                            vlm_function = vlm_functions.get(block_label) if vlm_functions else None
                            if vlm_function:
                                logger.info(f"VLM 처리 시작: {block_label} ({block_id})")
                                content = vlm_function(img)
                                block["block_content"] = content
                                logger.info(f"VLM 처리 완료: {block_label} ({block_id}) - {len(content)} chars")
                                # 처음 100자만 로그에 출력
                                preview = content[:100] + "..." if len(content) > 100 else content
                                logger.debug(f"  내용 미리보기: {preview}")
                            else:
                                logger.warning(f"VLM 함수 없음: {block_label} ({block_id})")
                                block["block_content"] = "[VLM 함수 없음]"
                        except Exception as e:
                            logger.error(f"VLM 처리 실패 ({block_id}): {e}", exc_info=True)
                            block["block_content"] = f"[VLM 처리 실패: {e}]"
                    else:
                        logger.warning(f"블록 라벨 불일치: 예상={block_label}, 실제={block.get('block_label')} ({block_id})")
                else:
                    logger.warning(f"블록 인덱스 범위 초과: block_idx={block_idx}, 리스트 길이={len(parsing_res_list)} ({block_id})")
        
        # 모든 JSON 파일 저장
        for json_file_stem, data in json_data_cache.items():
            # json_file_stem이 이미 page_0001_0_res 형식이므로 .json만 추가
            json_file_path = parsing_results_dir / f"{json_file_stem}.json"
            if not json_file_path.exists():
                # 다른 패턴 시도 (기존 패턴: {json_file_stem}_0_res.json도 확인)
                json_file_path_alt = parsing_results_dir / f"{json_file_stem}_0_res.json"
                if json_file_path_alt.exists():
                    json_file_path = json_file_path_alt
                    logger.debug(f"저장할 JSON 파일 찾음 (대체 패턴): {json_file_path.name}")
                else:
                    # glob으로 패턴 매칭 시도
                    json_files_matching = list(parsing_results_dir.glob(f"{json_file_stem}*_res.json"))
                    if json_files_matching:
                        json_file_path = json_files_matching[0]
                        logger.debug(f"저장할 JSON 파일 찾음 (glob 패턴): {json_file_path.name}")
                    else:
                        logger.warning(f"저장할 JSON 파일을 찾을 수 없습니다: {json_file_stem}")
                        continue
            
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                output_file = output_dir / json_file_path.name
            else:
                output_file = json_file_path
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 처리된 파일 리스트 반환
        processed_files = list(parsing_results_dir.glob("*_res.json"))
        logger.info(f"배치 처리 완료: {len(processed_files)}개 파일")
        return processed_files
    
    # 개별 처리 모드 (기존 로직)
    logger.info("개별 처리 모드: JSON 파일별로 순차 처리")
    if not vlm_images_dir.exists():
        logger.error(f"VLM 이미지 디렉토리가 존재하지 않습니다: {vlm_images_dir}")
        return []
    
    processed_files = []
    
    for json_file in json_files:
        logger.info(f"처리 중: {json_file.name}")
        
        # JSON 파일 읽기
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        parsing_res_list = data.get("parsing_res_list", [])
        json_stem = Path(json_file).stem  # page_0001_0_res
        
        # VLM 처리 대상 블록 라벨
        vlm_block_labels = ["table", "chart", "figure", "image", "formula"]
        
        processed_count = 0
        vlm_block_count = 0
        for block_idx, block in enumerate(parsing_res_list):
            block_label = block.get("block_label", "")
            
            # VLM 처리 대상 블록만 처리
            if block_label in vlm_block_labels:
                vlm_block_count += 1
                # 이미지 파일 경로 생성 (vlm_images/{block_label}/ 폴더에서 찾기)
                block_id = f"{json_stem}_block_{block_idx}"
                type_dir = vlm_images_dir / block_label  # vlm_images/table, vlm_images/chart, vlm_images/figure
                img_filename = f"{block_id}.png"
                img_path = type_dir / img_filename
                
                logger.debug(f"  VLM 블록 발견: {block_label} (block_idx={block_idx})")
                logger.debug(f"  이미지 경로 확인: {img_path}")
                
                if img_path.exists():
                    try:
                        # 이미지 파일 읽기
                        img = Image.open(img_path)
                        logger.debug(f"이미지 로드 완료: {img_path.name} ({img.size})")
                        
                        # VLM 처리 (해당 블록 타입의 함수가 제공된 경우)
                        vlm_function = vlm_functions.get(block_label) if vlm_functions else None
                        if vlm_function:
                            logger.info(f"VLM 처리 시작: {block_label} ({block_id})")
                            content = vlm_function(img)
                            block["block_content"] = content
                            processed_count += 1
                            logger.info(f"VLM 처리 완료: {block_label} ({block_id}) - {len(content)} chars")
                            # 처음 100자만 로그에 출력
                            preview = content[:100] + "..." if len(content) > 100 else content
                            logger.debug(f"  내용 미리보기: {preview}")
                        else:
                            logger.warning(f"VLM 함수 없음, 건너뜀: {block_label} ({block_id})")
                            block["block_content"] = "[VLM 함수 없음]"
                    except Exception as e:
                        logger.error(f"VLM 처리 실패 ({block_id}): {e}", exc_info=True)
                        block["block_content"] = f"[VLM 처리 실패: {e}]"
                else:
                    logger.warning(f"이미지 파일을 찾을 수 없습니다: {img_path}")
                    block["block_content"] = f"[이미지 파일 없음: {img_path.name}]"
        
        logger.info(f"VLM 처리 완료: {processed_count}/{vlm_block_count}개 블록 처리됨 ({json_file.name})")
        if vlm_block_count > 0 and processed_count == 0:
            logger.warning(f"  ⚠️ VLM 블록이 {vlm_block_count}개 있지만 처리된 블록이 없습니다. 이미지 파일이 없거나 VLM 함수가 없을 수 있습니다.")
        
        # 결과 저장
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / json_file.name
        else:
            output_file = json_file
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        processed_files.append(output_file)
        logger.debug(f"저장 완료: {output_file.name}")
    
    logger.info(f"VLM 처리 완료: {len(processed_files)}개 파일")
    
    return processed_files


# 예시 VLM 함수 (실제 VLM API 호출로 교체 필요)
def example_vlm_function(img: Image.Image) -> str:
    """
    예시 VLM 함수 - 실제 VLM API로 교체 필요
    
    Args:
        img: PIL Image 객체
    
    Returns:
        Markdown 형식의 변환 결과
    """
    # TODO: 실제 VLM API 호출
    # 예: OpenAI GPT-4V, Claude, Gemini 등
    return f"[VLM 처리 결과 - 이미지 크기: {img.size}]"