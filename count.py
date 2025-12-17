"""parsing_results 폴더의 모든 JSON 파일에서 block_label 개수 및 font_size 통계"""
from pathlib import Path
import json
from collections import Counter, defaultdict

# 분석할 block_label 목록
TARGET_LABELS = ["doc_title", "paragraph_title", "text", "figure_title", "header", "vision_footnote"]

# parsing_results 폴더 경로
parsing_results_dir = Path("output/test_full/layout_parsing_output/parsing_results")

if not parsing_results_dir.exists():
    print(f"폴더를 찾을 수 없습니다: {parsing_results_dir}")
    exit(1)

# block_label별 카운터 및 font_size 수집
block_label_counter = Counter()
block_label_font_sizes = defaultdict(list)  # block_label별 font_size 리스트
total_blocks = 0
total_files = 0

# 모든 JSON 파일 처리
json_files = list(parsing_results_dir.glob("*.json"))
print(f"총 {len(json_files)}개 JSON 파일 발견\n")

for json_file in sorted(json_files):
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        parsing_res_list = data.get("parsing_res_list", [])
        
        for block in parsing_res_list:
            block_label = block.get("block_label", "unknown")
            
            # 타겟 block_label만 처리
            if block_label in TARGET_LABELS:
                block_label_counter[block_label] += 1
                total_blocks += 1
                
                # font_size 수집
                font_size = block.get("font_size")
                if font_size is not None:
                    block_label_font_sizes[block_label].append(font_size)
        
        total_files += 1
        
    except Exception as e:
        print(f"오류 발생 ({json_file.name}): {e}")

# 결과 출력
print("=" * 80)
print("block_label 개수 및 font_size 통계")
print("=" * 80)
print(f"총 파일 수: {total_files}")
print(f"총 블록 수 (타겟 block_label): {total_blocks}")
print()

# block_label별 개수 및 font_size 평균 출력
print("block_label별 개수 및 font_size 평균:")
print("-" * 80)
for block_label in TARGET_LABELS:
    count = block_label_counter[block_label]
    font_sizes = block_label_font_sizes[block_label]
    
    if count > 0:
        percentage = (count / total_blocks * 100) if total_blocks > 0 else 0
        avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else None
        font_size_count = len(font_sizes)
        font_size_coverage = (font_size_count / count * 100) if count > 0 else 0
        
        print(f"{block_label:20s}: {count:5d}개 ({percentage:5.2f}%)", end="")
        if avg_font_size is not None:
            print(f" | font_size 평균: {avg_font_size:6.2f}pt (데이터: {font_size_count}/{count}, {font_size_coverage:5.1f}%)")
        else:
            print(" | font_size: 데이터 없음")
    else:
        print(f"{block_label:20s}: {count:5d}개")

print()
print("=" * 80)
print("block_label별 font_size 분포 (value_counts)")
print("=" * 80)

# block_label별 font_size value_counts 출력
for block_label in TARGET_LABELS:
    font_sizes = block_label_font_sizes[block_label]
    if not font_sizes:
        continue
    
    # font_size를 반올림하여 그룹화 (0.5 단위)
    rounded_sizes = [round(size * 2) / 2 for size in font_sizes]
    size_counter = Counter(rounded_sizes)
    
    print(f"\n[{block_label}]")
    print(f"  총 {len(font_sizes)}개 블록에 font_size 데이터 있음")
    print("  font_size 분포:")
    
    # 내림차순으로 정렬하여 출력
    for size, count in sorted(size_counter.items(), key=lambda x: (-x[1], x[0])):
        percentage = (count / len(font_sizes) * 100) if font_sizes else 0
        print(f"    {size:6.1f}pt: {count:4d}개 ({percentage:5.1f}%)")

print()
print("=" * 80)