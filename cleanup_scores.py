import re
from pathlib import Path

def remove_scores(file_path):
    if not file_path.exists():
        return False
    
    content = file_path.read_text(encoding="utf-8")
    
    if "submission_score:" not in content and "submission_ready:" not in content:
        return False
    
    parts = content.split("---", 2)
    if len(parts) >= 3:
        fm = parts[1]
        fm = re.sub(r"^submission_score:.*\n?", "", fm, flags=re.MULTILINE)
        fm = re.sub(r"^submission_ready:.*\n?", "", fm, flags=re.MULTILINE)
        new_content = f"---{fm}---{parts[2]}"
        file_path.write_text(new_content, encoding="utf-8")
        return True
    return False

reviews_dir = Path("10_output/15_reviews")
pristine_dir = reviews_dir / ".pristine"

count_main = 0
count_pristine = 0

for f in reviews_dir.glob("*_review.md"):
    if remove_scores(f):
        count_main += 1

for f in pristine_dir.glob("*_review.md"):
    if remove_scores(f):
        count_pristine += 1

print(f"Removed scores from {count_main} main files and {count_pristine} pristine files.")
