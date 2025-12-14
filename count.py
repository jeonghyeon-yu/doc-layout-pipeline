"""parsing_results 폴더의 모든 JSON 파일에서 block_label 개수 세기"""
from pathlib import Path
import json
from collections import Counter

# parsing_results 폴더 경로
parsing_results_dir = Path("output/test_full/layout_parsing_output/parsing_results")

if not parsing_results_dir.exists():
    print(f"폴더를 찾을 수 없습니다: {parsing_results_dir}")
    exit(1)

# block_label 카운터
block_label_counter = Counter()
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
            block_label_counter[block_label] += 1
            total_blocks += 1
        
        total_files += 1
        
    except Exception as e:
        print(f"오류 발생 ({json_file.name}): {e}")

# 결과 출력
print("=" * 60)
print("block_label 개수 통계")
print("=" * 60)
print(f"총 파일 수: {total_files}")
print(f"총 블록 수: {total_blocks}")
print()

# block_label별 개수 출력 (내림차순)
print("block_label별 개수:")
for block_label, count in block_label_counter.most_common():
    percentage = (count / total_blocks * 100) if total_blocks > 0 else 0
    print(f"  {block_label:20s}: {count:5d}개 ({percentage:5.2f}%)")

print("=" * 60)