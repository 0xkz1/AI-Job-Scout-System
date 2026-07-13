"""
Match Weight Adjuster — Streamlit Web UI
========================================
Adjust the importance of Skills, Experience, Location, Salary
via sliders and see match scores recalculate in real time.

Usage:
    cd /media/kz003/atelier/00_Kazuki/career/Job-Intelligence-System
    .venv/bin/streamlit run weight_adjuster.py --server.port 8501
"""

import json
import os
import sys
import re
import glob

import streamlit as st
import pandas as pd

# Add scraper dir to path so we can import matcher
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from matcher import (
    analyze_match,
    save_match_report,
    DEFAULT_WEIGHTS,
)
from filter import filter_jobs

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "10_output")
ANALYZED_PATH = os.path.join(OUTPUT_DIR, "_analyzed.json")
MATCH_DIR = os.path.join(OUTPUT_DIR, "00_matches")

# --- Config ---
MIN_SALARY_GBP = 30000

# --- Page Setup ---
st.set_page_config(
    page_title="Match Weight Adjuster",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 Match Weight Adjuster")
st.markdown("Adjust the importance of each dimension and see how match scores change in real time.")

# --- Load analyzed jobs ---
@st.cache_data(ttl=60)
def load_jobs():
    with open(ANALYZED_PATH) as f:
        return json.load(f)

@st.cache_data(ttl=60)
def get_base_scores(jobs_json_str: str):
    """Pre-calculate individual dimension scores (without weights) so we can
    re-compute the weighted composite instantly when sliders change."""
    jobs = json.loads(jobs_json_str)
    config = {"output_dir": OUTPUT_DIR, "min_salary_gbp": MIN_SALARY_GBP}
    results = []
    for job in jobs:
        match = analyze_match(job, config)
        results.append({
            "company": job.get("company", "Unknown"),
            "title": job.get("title", "Unknown"),
            "location": job.get("location", "Unknown"),
            "url": job.get("url", ""),
            "skill_raw": match["skills"]["score"],
            "exp_raw": match["experience"]["score"],
            "loc_raw": match["location"]["score"],
            "sal_raw": match["salary"]["score"],
            "ctx_raw": match.get("context_score", 0.5),
            "tier": match["tier"],
        })
    return results

try:
    jobs = load_jobs()
except FileNotFoundError:
    st.error(f"Analyzed jobs file not found at {ANALYZED_PATH}. Run the scraper first.")
    st.stop()

# --- Weight Sliders ---
st.markdown("### ⚖️ Weight Configuration")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    w_skills = st.slider(
        "🛠 Skills",
        min_value=0, max_value=100, value=40,
        help="How much weight to give skill matching"
    )

with col2:
    w_experience = st.slider(
        "📈 Experience",
        min_value=0, max_value=100, value=25,
        help="How much weight to give experience level matching"
    )

with col3:
    w_location = st.slider(
        "📍 Location",
        min_value=0, max_value=100, value=10,
        help="How much weight to give location/work style matching"
    )

with col4:
    w_salary = st.slider(
        "💰 Salary",
        min_value=0, max_value=100, value=5,
        help="How much weight to give salary matching"
    )

with col5:
    w_context = st.slider(
        "🧠 Context/Ethos",
        min_value=0, max_value=100, value=20,
        help="How much weight to give personal brand & ethos alignment"
    )

total = w_skills + w_experience + w_location + w_salary + w_context

if total == 0:
    st.warning("All weights are 0 — cannot calculate scores. Please adjust sliders.")
    st.stop()

# Normalize to 0-1
norm_skills = w_skills / total
norm_experience = w_experience / total
norm_location = w_location / total
norm_salary = w_salary / total
norm_context = w_context / total

# Show normalization
st.info(
    f"**Normalized weights** — "
    f"Skills: {norm_skills*100:.0f}% | "
    f"Experience: {norm_experience*100:.0f}% | "
    f"Location: {norm_location*100:.0f}% | "
    f"Salary: {norm_salary*100:.0f}% | "
    f"Context: {norm_context*100:.0f}%"
    + (f"  ⚠️ (raw sum={total}, auto-normalized to 100%)" if total != 100 else "")
)

# --- Recalculate Scores ---
jobs_json_str = json.dumps(jobs)
base_results = get_base_scores(jobs_json_str)

# Compute weighted composite scores
weights = {
    "skills": norm_skills,
    "experience": norm_experience,
    "location": norm_location,
    "salary": norm_salary,
    "context": norm_context,
}

for r in base_results:
    composite = (
        r["skill_raw"] * weights["skills"]
        + r["exp_raw"] * weights["experience"]
        + r["loc_raw"] * weights["location"]
        + r["sal_raw"] * weights["salary"]
        + r["ctx_raw"] * weights["context"]
    )
    r["composite_score"] = round(composite * 100)

# Build DataFrame
df = pd.DataFrame(base_results)
df = df[["company", "title", "location", "composite_score",
         "skill_raw", "exp_raw", "loc_raw", "sal_raw", "ctx_raw", "tier", "url"]]
df.columns = ["Company", "Title", "Location", "Score (%)",
              "Skills", "Exp", "Loc", "Salary", "Context", "Tier", "URL"]
df = df.sort_values("Score (%)", ascending=False).reset_index(drop=True)
df.index += 1  # 1-based rank

# --- Tier filter ---
st.markdown("### 📊 Results")
col_a, col_b = st.columns([1, 4])
with col_a:
    min_score = st.slider("Minimum score", 0, 100, 0, 5)

filtered_df = df[df["Score (%)"] >= min_score].copy()
st.metric("Jobs shown", f"{len(filtered_df)} / {len(df)}")

# --- Table ---
st.dataframe(
    filtered_df[["Company", "Title", "Location", "Score (%)",
                 "Skills", "Exp", "Loc", "Salary", "Context", "Tier"]],
    use_container_width=True,
    height=500,
)

# --- Score distribution ---
st.markdown("### 📈 Score Distribution")
col_c, col_d = st.columns(2)

with col_c:
    st.bar_chart(filtered_df.set_index("Company")["Score (%)"].head(30))

with col_d:
    tier_counts = filtered_df["Tier"].value_counts()
    st.bar_chart(tier_counts)

# --- Regenerate MD files with new weights ---
st.markdown("---")
st.markdown("### 🔄 Regenerate Match Reports")
st.markdown(
    f"Click below to regenerate all {len(df)} match report MD files "
    f"with the current weights and updated frontmatter (for Obsidian Dataview)."
)
st.warning("⚠️ This will overwrite existing match report files in `00_matches/`.")

if st.button("🔄 Regenerate Match Reports", type="primary"):
    with st.spinner("Regenerating match reports..."):
        from matcher import _tier_short

        config = {
            "output_dir": OUTPUT_DIR,
            "min_salary_gbp": MIN_SALARY_GBP,
            "weights": weights,
        }

        # Include context in config for match report generation
        config["weights"]["context"] = norm_context

        # Clear old files
        old_files = glob.glob(os.path.join(MATCH_DIR, "match_*.md"))
        for f in old_files:
            os.remove(f)

        count = 0
        for job in jobs:
            match = analyze_match(job, config, weights=weights)
            if match["composite_score"] >= 0.50:
                save_match_report(job, match, MATCH_DIR)
                count += 1

        st.success(f"✅ Regenerated {count} match reports!")
        st.balloons()