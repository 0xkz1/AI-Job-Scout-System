#!/usr/bin/env bash
set -euo pipefail

SCRAPER_DIR="/media/kz003/atelier/00_Kazuki/career/Job-Intelligence-System"
OUTPUT_DIR="${SCRAPER_DIR}/10_output"
SAVED_DIR="${SCRAPER_DIR}/00_saved"
REPORT_DIR="${HOME}/.hermes/cron/output/20e08388d5df"
TIMESTAMP=$(date '+%Y-%m-%d-%H:%M:%S')
REPORT_FILE="${REPORT_DIR}/runner-${TIMESTAMP}.md"

mkdir -p "${REPORT_DIR}"

cd "${SCRAPER_DIR}"

echo "# Job Scraper Pipeline — ${TIMESTAMP}" > "${REPORT_FILE}"
echo "" >> "${REPORT_FILE}"

# ---- Step 1: scraper_saved.py ----
echo "## Step 1: 保存済み求人スクレイプ" >> "${REPORT_FILE}"
START_TS=$(date +%s)
if python3 scraper_saved.py >> "${REPORT_FILE}" 2>&1; then
    echo "✅ scraper_saved.py 成功" >> "${REPORT_FILE}"
else
    echo "⚠️ scraper_saved.py 失敗（無視して続行）" >> "${REPORT_FILE}"
fi
echo "" >> "${REPORT_FILE}"

# ---- Step 2: run.py (Indeed) ----
echo "## Step 2: Indeed メインスクレイパー" >> "${REPORT_FILE}"
if python3 run.py --site indeed --pages 5 >> "${REPORT_FILE}" 2>&1; then
    echo "✅ run.py 成功" >> "${REPORT_FILE}"
else
    echo "❌ run.py 失敗" >> "${REPORT_FILE}"
fi
echo "" >> "${REPORT_FILE}"

# ---- Step 3: 集計 ----
echo "## Step 3: 結果サマリー" >> "${REPORT_FILE}"
MATCH_COUNT=$(find "${OUTPUT_DIR}/00_matches" -name "*_match.md" 2>/dev/null | wc -l)
CV_COUNT=$(find "${OUTPUT_DIR}/10_cvs" -name "*CV.md" 2>/dev/null | wc -l)
CL_COUNT=$(find "${OUTPUT_DIR}/10_cover-letters" -name "*.md" 2>/dev/null | wc -l)
SAVED_COUNT=$(find "${SAVED_DIR}" -type f 2>/dev/null | wc -l)

echo "| 出力先 | ファイル数 |" >> "${REPORT_FILE}"
echo "|--------|-----------|" >> "${REPORT_FILE}"
echo "| 00_matches | ${MATCH_COUNT} |" >> "${REPORT_FILE}"
echo "| 10_cvs | ${CV_COUNT} |" >> "${REPORT_FILE}"
echo "| 10_cover-letters | ${CL_COUNT} |" >> "${REPORT_FILE}"
echo "| 00_saved | ${SAVED_COUNT} |" >> "${REPORT_FILE}"

ELAPSED=$(( $(date +%s) - START_TS ))
echo "" >> "${REPORT_FILE}"
echo "**実行時間**: ${ELAPSED}秒" >> "${REPORT_FILE}"

# Output the report path for delivery context
echo "---"
echo "Report saved to: ${REPORT_FILE}"
cat "${REPORT_FILE}"
