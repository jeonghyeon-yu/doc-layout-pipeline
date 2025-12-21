"""개선된 박스 감지 모듈"""
import fitz  # PyMuPDF
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def points_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """두 점 사이의 거리 계산"""
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


def find_connected_components(lines: List, eps: float = 5.0) -> List[List]:
    """
    연결된 선들끼리 그룹화 (connected components)
    
    Args:
        lines: 선 정보 리스트 [("l", p1, p2), ...]
        eps: 두 점이 같은 점으로 간주되는 최대 거리
    
    Returns:
        연결된 선들의 그룹 리스트
    """
    if not lines:
        return []
    
    # 각 선의 끝점 추출
    line_endpoints = []
    for line in lines:
        if len(line) >= 3:
            try:
                p1, p2 = line[1], line[2]
                line_endpoints.append({
                    "line": line,
                    "p1": (p1.x, p1.y),
                    "p2": (p2.x, p2.y)
                })
            except Exception:
                continue
    
    if not line_endpoints:
        return []
    
    # Union-Find로 연결된 컴포넌트 찾기
    parent = list(range(len(line_endpoints)))
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    
    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py
    
    # 두 선의 끝점이 가까우면 같은 컴포넌트로 묶기
    for i in range(len(line_endpoints)):
        for j in range(i + 1, len(line_endpoints)):
            le1 = line_endpoints[i]
            le2 = line_endpoints[j]
            
            # 두 선의 끝점들 간 거리 확인
            dists = [
                points_distance(le1["p1"], le2["p1"]),
                points_distance(le1["p1"], le2["p2"]),
                points_distance(le1["p2"], le2["p1"]),
                points_distance(le1["p2"], le2["p2"])
            ]
            
            # 최소 거리가 eps 이내이면 연결됨
            if min(dists) < eps:
                union(i, j)
    
    # 컴포넌트별로 그룹화
    components = {}
    for i in range(len(line_endpoints)):
        root = find(i)
        if root not in components:
            components[root] = []
        components[root].append(line_endpoints[i]["line"])
    
    return list(components.values())


def is_horizontal_line(line, angle_threshold: float = 10.0) -> bool:
    """선이 수평선인지 확인 (각도 기준)"""
    if len(line) < 3:
        return False
    try:
        p1, p2 = line[1], line[2]
        dx = abs(p2.x - p1.x)
        dy = abs(p2.y - p1.y)
        if dx == 0:
            return False
        # 수평선: dy가 dx보다 훨씬 작아야 함
        # tan(10도) ≈ 0.176
        return (dy / dx) < 0.176
    except Exception:
        return False


def is_vertical_line(line, angle_threshold: float = 10.0) -> bool:
    """선이 수직선인지 확인 (각도 기준)"""
    if len(line) < 3:
        return False
    try:
        p1, p2 = line[1], line[2]
        dx = abs(p2.x - p1.x)
        dy = abs(p2.y - p1.y)
        if dy == 0:
            return False
        # 수직선: dx가 dy보다 훨씬 작아야 함
        # tan(10도) ≈ 0.176
        return (dx / dy) < 0.176
    except Exception:
        return False


def is_valid_box(component_lines: List, min_width: float, min_height: float) -> Tuple[bool, Optional[Tuple[float, float, float, float]]]:
    """
    컴포넌트가 유효한 박스인지 검증
    
    Returns:
        (is_valid, rect) 튜플
    """
    if len(component_lines) < 4:
        return False, None
    
    # 수평선과 수직선 개수 확인
    horizontal_lines = [line for line in component_lines if is_horizontal_line(line)]
    vertical_lines = [line for line in component_lines if is_vertical_line(line)]
    
    if len(horizontal_lines) < 2 or len(vertical_lines) < 2:
        return False, None
    
    # 바운딩 박스 계산
    all_points = []
    for line in component_lines:
        if len(line) >= 3:
            try:
                p1, p2 = line[1], line[2]
                all_points.append((p1.x, p1.y))
                all_points.append((p2.x, p2.y))
            except Exception:
                continue
    
    if len(all_points) < 4:
        return False, None
    
    xs = [p[0] for p in all_points]
    ys = [p[1] for p in all_points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    
    width = x1 - x0
    height = y1 - y0
    
    if width < min_width or height < min_height:
        return False, None
    
    return True, (x0, y0, x1, y1)


def calculate_iou(rect1: Tuple[float, float, float, float], rect2: Tuple[float, float, float, float]) -> float:
    """두 사각형의 IoU 계산"""
    x1_min, y1_min, x1_max, y1_max = rect1
    x2_min, y2_min, x2_max, y2_max = rect2
    
    # 겹치는 영역 계산
    overlap_x0 = max(x1_min, x2_min)
    overlap_y0 = max(y1_min, y2_min)
    overlap_x1 = min(x1_max, x2_max)
    overlap_y1 = min(y1_max, y2_max)
    
    if overlap_x0 >= overlap_x1 or overlap_y0 >= overlap_y1:
        return 0.0
    
    overlap_area = (overlap_x1 - overlap_x0) * (overlap_y1 - overlap_y0)
    area1 = (x1_max - x1_min) * (y1_max - y1_min)
    area2 = (x2_max - x2_min) * (y2_max - y2_min)
    union_area = area1 + area2 - overlap_area
    
    if union_area == 0:
        return 0.0
    
    return overlap_area / union_area


def nms(boxes: List[Dict], iou_threshold: float = 0.5) -> List[Dict]:
    """Non-Maximum Suppression으로 중복 박스 제거"""
    if not boxes:
        return []
    
    # 면적 기준으로 정렬 (큰 것부터)
    sorted_boxes = sorted(boxes, key=lambda b: b["width"] * b["height"], reverse=True)
    
    keep = []
    while sorted_boxes:
        # 가장 큰 박스 선택
        current = sorted_boxes.pop(0)
        keep.append(current)
        
        # 나머지 박스들과 IoU 계산하여 중복 제거
        remaining = []
        for box in sorted_boxes:
            iou = calculate_iou(current["rect"], box["rect"])
            if iou < iou_threshold:
                remaining.append(box)
        sorted_boxes = remaining
    
    return keep


def extract_boxes_from_page_improved(page: fitz.Page, min_width: float = 100, min_height: float = 50) -> List[Dict]:
    """
    연결된 선들끼리 그룹화하여 박스 감지 (개선된 버전)
    1. 연결된 선들끼리만 그룹화 (connected components)
    2. 각 컴포넌트에서 사각형 성립 검증
    3. NMS로 중복 제거
    """
    boxes = []
    box_id = 0
    
    try:
        drawings = page.get_drawings()
        all_lines = []
        
        # 모든 선 수집
        for drawing in drawings:
            items = drawing.get("items", [])
            for item in items:
                if item[0] == "l" and len(item) >= 3:  # 선(line)
                    all_lines.append(item)
        
        if len(all_lines) < 4:
            return []
        
        # 1. 연결된 선들끼리 그룹화 (connected components)
        components = find_connected_components(all_lines, eps=5.0)
        
        # 2. 각 컴포넌트에서 사각형 성립 검증
        for component_lines in components:
            is_valid, rect = is_valid_box(component_lines, min_width, min_height)
            
            if is_valid and rect:
                x0, y0, x1, y1 = rect
                width = x1 - x0
                height = y1 - y0
                
                boxes.append({
                    "id": box_id,
                    "rect": rect,
                    "width": width,
                    "height": height,
                    "type": "connected_component",
                    "line_count": len(component_lines)
                })
                box_id += 1
        
        # 3. NMS로 중복 제거
        boxes = nms(boxes, iou_threshold=0.5)
        
        # ID 재할당
        for i, box in enumerate(boxes):
            box["id"] = i
        
        logger.debug(f"페이지에서 {len(boxes)}개 박스 감지 (개선된 방식)")
    
    except Exception as e:
        logger.warning(f"박스 추출 중 오류: {e}")
    
    return boxes


def is_point_inside_box_improved(bbox: List[float], box_rect: Tuple[float, float, float, float], 
                                  margin: float = 2.0) -> bool:
    """
    텍스트 bbox가 박스 안에 있는지 확인 (엄격한 검증)
    텍스트의 대부분(90% 이상)이 박스 안에 있어야 함
    
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
    
    # 텍스트와 박스의 겹치는 영역 계산
    overlap_x0 = max(tx0, bx0)
    overlap_y0 = max(ty0, by0)
    overlap_x1 = min(tx1, bx1)
    overlap_y1 = min(ty1, by1)
    
    # 겹치는 영역이 있는지 확인
    if overlap_x0 >= overlap_x1 or overlap_y0 >= overlap_y1:
        return False
    
    # 겹치는 영역의 크기 계산
    overlap_width = overlap_x1 - overlap_x0
    overlap_height = overlap_y1 - overlap_y0
    text_width = tx1 - tx0
    text_height = ty1 - ty0
    text_area = text_width * text_height
    
    if text_area == 0:
        return False
    
    overlap_area = overlap_width * overlap_height
    overlap_ratio = overlap_area / text_area
    
    # 텍스트의 90% 이상이 박스 안에 있어야 함
    if overlap_ratio < 0.9:
        return False
    
    # X와 Y 방향 모두 90% 이상 겹쳐야 함
    overlap_ratio_x = overlap_width / text_width if text_width > 0 else 0
    overlap_ratio_y = overlap_height / text_height if text_height > 0 else 0
    
    if overlap_ratio_x < 0.9 or overlap_ratio_y < 0.9:
        return False
    
    # 박스 경계 근처에 있는 텍스트는 추가 체크
    # 텍스트가 박스 경계를 넘어서면 제외
    if ty0 < (by0 - margin) or ty1 > (by1 + margin):
        return False
    if tx0 < (bx0 - margin) or tx1 > (bx1 + margin):
        return False
    
    return True


def find_containing_box_improved(bbox: List[float], boxes: List[Dict], margin: float = 2.0) -> Optional[int]:
    """
    텍스트 bbox를 포함하는 박스 ID 찾기 (개선된 버전)
    여러 박스에 포함될 수 있는 경우, 가장 적합한 박스를 선택
    
    Args:
        bbox: 텍스트 영역 [x0, y0, x1, y1]
        boxes: 박스 정보 리스트
        margin: 허용 오차 (포인트)
    
    Returns:
        박스 ID 또는 None
    """
    if len(bbox) != 4 or not boxes:
        return None
    
    tx0, ty0, tx1, ty1 = bbox
    text_area = (tx1 - tx0) * (ty1 - ty0)
    
    # 모든 매칭되는 박스 찾기
    matching_boxes = []
    for box in boxes:
        if is_point_inside_box_improved(bbox, box["rect"], margin):
            matching_boxes.append(box)
    
    if not matching_boxes:
        return None
    
    # 여러 박스 중에서 가장 적합한 박스 선택
    # 전략: 텍스트가 완전히 포함되는 박스를 우선 선택, 그 다음 가장 작은 박스
    
    best_box = None
    best_score = float('inf')
    
    for box in matching_boxes:
        bx0, by0, bx1, by1 = box["rect"]
        box_area = box["width"] * box["height"]
        
        # 텍스트가 완전히 박스 안에 있는지 확인
        fully_inside = (bx0 <= tx0 and tx1 <= bx1 and by0 <= ty0 and ty1 <= by1)
        
        # 텍스트와 박스의 겹치는 영역 계산
        overlap_x0 = max(tx0, bx0)
        overlap_y0 = max(ty0, by0)
        overlap_x1 = min(tx1, bx1)
        overlap_y1 = min(ty1, by1)
        
        overlap_area = (overlap_x1 - overlap_x0) * (overlap_y1 - overlap_y0)
        overlap_ratio = overlap_area / text_area if text_area > 0 else 0
        
        # 점수 계산: 완전히 포함되면 우선순위 높음, 작은 박스 우선
        if fully_inside:
            score = box_area  # 완전히 포함되면 박스 크기만으로 결정
        else:
            score = box_area / (overlap_ratio + 0.1)  # 부분 포함이면 겹침 비율 고려
        
        if score < best_score:
            best_score = score
            best_box = box
    
    return best_box["id"] if best_box else None

