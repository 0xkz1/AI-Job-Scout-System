"""
Job Scraper Pipeline — Unified Streamlit App
=============================================
Tabs:
  1. 🔍 Scraper    — search config, run scraper, view results
  2. 🎯 Weights    — adjust match-score weights, regenerate reports

Usage:
    cd /media/kz003/atelier/00_Kazuki/career/scraper
    .venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
"""

import streamlit as st
import subprocess
import json
import os
import re
import sys
import glob
import yaml
from pathlib import Path

import pandas as pd

# --- Paths ---
SCRAPER_DIR = Path(__file__).parent
CONFIG_PATH = SCRAPER_DIR / "config.yaml"
OUTPUT_DIR = SCRAPER_DIR / "output"
ANALYZED_PATH = OUTPUT_DIR / "_analyzed.json"
MATCH_DIR = OUTPUT_DIR / "00_matches"
ASSET_WEAVER_SCRIPT = Path("/media/kz003/atelier/kazukiyunome/scripts/asset-weaver.py")

# Add scraper dir to path so we can import matcher
sys.path.insert(0, str(SCRAPER_DIR))
from matcher import (
    analyze_match,
    save_match_report,
    DEFAULT_WEIGHTS,
)

MIN_SALARY_GBP = 30000

# --- Page Setup (must be first Streamlit call) ---
st.set_page_config(
    page_title="Job Scraper Pipeline",
    page_icon="🔍",
    layout="wide",
)

# ─────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────

def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, allow_unicode=True)

def run_scraper(site="indeed", pages=5):
    """Run scraper and stream output."""
    cmd = ["python3", "run.py", "--site", site, "--pages", str(pages)]
    process = subprocess.Popen(
        cmd, cwd=str(SCRAPER_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    for line in process.stdout:
        yield line
    process.wait()
    yield f"\n✅ Done! Exit code: {process.returncode}"


# ─────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────

tab_scraper, tab_weights = st.tabs(["🔍 Scraper", "🎯 Weights"])

# ═══════════════════════════════════════════════════════════
# Tab 1: Scraper
# ═══════════════════════════════════════════════════════════

with tab_scraper:
    st.header("🔍 Job Scraper Control Panel")

    # Load current config
    if "config" not in st.session_state:
        st.session_state.config = load_config()

    # === Section 1: Config Form ===
    st.subheader("🔧 Search Configuration")

    col1, col2 = st.columns(2)

    with col1:
        keywords_text = st.text_area(
            "Keywords (one per line)",
            value="\n".join(st.session_state.config.get("keywords", [])),
            height=150,
        )
        locations_text = st.text_area(
            "Locations (one per line, leave empty for anywhere)",
            value="\n".join(st.session_state.config.get("locations", ["Edinburgh"])),
            height=80,
        )
        exclude_title_text = st.text_area(
            "🚫 Exclude from Title (one per line)",
            value="\n".join(st.session_state.config.get("exclude_title_keywords", [])),
            height=80,
            help="Jobs with these words in the title will be hidden. e.g. Senior, Lead, Manager, Director",
        )
        exclude_desc_text = st.text_area(
            "🚫 Exclude from Description (one per line)",
            value="\n".join(st.session_state.config.get("exclude_description_keywords", [])),
            height=80,
            help="Jobs whose description contains these words will be hidden.",
        )

    with col2:
        min_salary = st.number_input(
            "💰 Min Salary (GBP)",
            min_value=0,
            value=st.session_state.config.get("min_salary_gbp", 0),
            step=1000,
        )
        sites = st.multiselect(
            "Sites",
            options=["indeed", "linkedin"],
            default=st.session_state.config.get("sites", ["indeed"]),
        )
        max_pages = st.slider(
            "Pages per search", 1, 10, st.session_state.config.get("max_pages_per_search", 3)
        )
        levels = st.multiselect(
            "Experience Levels",
            options=["entry_level", "mid_senior", "director"],
            default=st.session_state.config.get("include_levels", ["entry_level", "mid_senior", "director"]),
        )
        emp_types = st.multiselect(
            "Employment Types",
            options=["full_time", "part_time", "contract", "internship", "freelance"],
            default=st.session_state.config.get("employment_types", ["full_time", "part_time", "contract"]),
        )

    if st.button("💾 Save Configuration"):
        st.session_state.config = {
            "keywords": [k.strip() for k in keywords_text.split("\n") if k.strip()],
            "locations": [l.strip() for l in locations_text.split("\n") if l.strip()],
            "sites": sites,
            "min_salary_gbp": min_salary,
            "max_pages_per_search": max_pages,
            "include_levels": levels,
            "employment_types": emp_types,
            "exclude_title_keywords": [k.strip() for k in exclude_title_text.split("\n") if k.strip()],
            "exclude_description_keywords": [k.strip() for k in exclude_desc_text.split("\n") if k.strip()],
        }
        save_config(st.session_state.config)
        st.success("✅ Configuration saved!")

    # === Section 2: Run Scraper ===
    st.subheader("🚀 Run Scraper")

    col3, col4 = st.columns([1, 3])
    with col3:
        selected_site = st.selectbox("Site", options=["indeed", "linkedin", "all"])
        run_pages = st.number_input("Pages", min_value=1, max_value=10, value=3)

    with col4:
        if st.button("Run All Scrapers (Saved + Main)"):
                with st.spinner("Running scraper & saved jobs scraper..."):
                    for line in run_scraper(site="saved", pages=run_pages):
                        st.code(line)
                    for line in run_scraper(site="indeed", pages=5):
                        st.code(line)

        if st.button("🔄 Re-analyze Existing Data"):
            with st.spinner("Re-analyzing _analyzed.json with updated analyzer..."):
                cmd = ["python3", "run.py", "--reanalyze"]
                process = subprocess.Popen(
                    cmd, cwd=str(SCRAPER_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                for line in process.stdout:
                    st.code(line)
                process.wait()
                if process.returncode == 0:
                    st.success("✅ Re-analysis complete! Refresh to see updated results.")
                else:
                    st.error(f"❌ Re-analysis failed with exit code {process.returncode}")

    # === Section 3: Results ===
    st.subheader("📊 Recent Results")

    index_path = OUTPUT_DIR / "_index.json"

    if ANALYZED_PATH.exists():
        with open(ANALYZED_PATH, encoding="utf-8") as f:
            try:
                analyzed = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                with open(ANALYZED_PATH) as f:
                    analyzed = json.load(f)
        if analyzed:
            jobs_with_score = []
            for j in analyzed:
                match = j.get("match", {})
                score = match.get("composite_score", 0)
                tier = match.get("tier", "")
                analysis = j.get("analysis", {})
                salary = analysis.get("salary", {})
                salary_str = ""
                if salary.get("min") and salary.get("max"):
                    salary_str = f"£{salary['min']:.0f}K-{salary['max']:.0f}K"
                elif salary.get("max"):
                    salary_str = f"Up to £{salary['max']:.0f}K"
                level = analysis.get("experience_level", "?")
                work_style = analysis.get("work_style", "?")
                skills = analysis.get("skills", [])
                skill_str = ", ".join(skills[:6]) + ("..." if len(skills) > 6 else "")

                jobs_with_score.append({
                    "Score": f"{score*100:.0f}%",
                    "Tier": tier,
                    "Company": j.get("company", "?"),
                    "Title": j.get("title", "?"),
                    "Location": j.get("location", "?"),
                    "Level": level,
                    "Work": work_style,
                    "Salary": salary_str,
                    "Skills": skill_str,
                    "url": j.get("url", ""),
                })

            jobs_with_score.sort(key=lambda x: float(x["Score"].strip("%")), reverse=True)

            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            strong = sum(1 for j in jobs_with_score if "Strong" in j["Tier"])
            good = sum(1 for j in jobs_with_score if "Good" in j["Tier"])
            partial = sum(1 for j in jobs_with_score if "Partial" in j["Tier"])
            weak = sum(1 for j in jobs_with_score if "Weak" in j["Tier"])
            with col_m1:
                st.metric("Total Jobs", len(jobs_with_score))
            with col_m2:
                st.metric("🟢 Strong Match", strong)
            with col_m3:
                st.metric("🟡 Good Match", good)
            with col_m4:
                st.metric("🔴 Weak / Partial", weak + partial)

            min_score_filter = st.slider("Minimum match score", 0, 100, 0, 5)

            st.dataframe(
                [
                    {
                        "🎯": j["Score"],
                        "Company": j["Company"],
                        "Title": j["Title"],
                        "📍": j["Location"],
                        "💰": j["Salary"],
                        "Level": j["Level"],
                        "URL": j["url"],
                        "Skills": j["Skills"],
                    }
                    for j in jobs_with_score
                    if float(j["Score"].strip("%")) >= min_score_filter
                ],
                column_config={
                    "🎯": st.column_config.Column(width="small"),
                    "URL": st.column_config.LinkColumn(width="small", display_text="🔗 Open"),
                    "Skills": st.column_config.Column(width="large"),
                },
                use_container_width=True,
                height=500,
            )
        else:
            st.info("No jobs scraped yet. Run the scraper above.")
    elif index_path.exists():
        st.info("Run the scraper again to enable match analysis.")
        with open(index_path) as f:
            index = json.load(f)
        if index:
            st.metric("Total Jobs Scraped (legacy format)", len(index))
            st.table(
                [
                    {"Company": r["company"], "Title": r["title"], "Location": r["location"]}
                    for r in index[-20:]
                ]
            )
    else:
        st.info("No outputs found. Run the scraper to generate results.")

    st.sidebar.markdown(
        """
### 🎯 Quick Links
- [Edit config.yaml](config.yaml)
- [View output folder](output/00_matches/)
- [Open n8n dashboard](http://localhost:5678)
"""
    )


# ═══════════════════════════════════════════════════════════
# Tab 2: Weights
# ═══════════════════════════════════════════════════════════

with tab_weights:
    st.header("🎯 Match Weight Adjuster")
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
        config = {"output_dir": str(OUTPUT_DIR), "min_salary_gbp": MIN_SALARY_GBP}
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
                "tier": match["tier"],
            })
        return results

    try:
        jobs = load_jobs()
    except FileNotFoundError:
        st.error(f"Analyzed jobs file not found at {ANALYZED_PATH}. Run the scraper first.")
        st.stop()

    # --- Weight Sliders ---
    st.subheader("⚖️ Weight Configuration")

    col1, col2, col3, col4 = st.columns(4)

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
            min_value=0, max_value=100, value=20,
            help="How much weight to give location/work style matching"
        )

    with col4:
        w_salary = st.slider(
            "💰 Salary",
            min_value=0, max_value=100, value=15,
            help="How much weight to give salary matching"
        )

    total = w_skills + w_experience + w_location + w_salary

    if total == 0:
        st.warning("All weights are 0 — cannot calculate scores. Please adjust sliders.")
        st.stop()

    # Normalize to 0-1
    norm_skills = w_skills / total
    norm_experience = w_experience / total
    norm_location = w_location / total
    norm_salary = w_salary / total

    st.info(
        f"**Normalized weights** — "
        f"Skills: {norm_skills*100:.0f}% | "
        f"Experience: {norm_experience*100:.0f}% | "
        f"Location: {norm_location*100:.0f}% | "
        f"Salary: {norm_salary*100:.0f}%"
        + (f"  ⚠️ (raw sum={total}, auto-normalized to 100%)" if total != 100 else "")
    )

    # --- Recalculate Scores ---
    jobs_json_str = json.dumps(jobs)
    base_results = get_base_scores(jobs_json_str)

    weights = {
        "skills": norm_skills,
        "experience": norm_experience,
        "location": norm_location,
        "salary": norm_salary,
    }

    for r in base_results:
        composite = (
            r["skill_raw"] * weights["skills"]
            + r["exp_raw"] * weights["experience"]
            + r["loc_raw"] * weights["location"]
            + r["sal_raw"] * weights["salary"]
        )
        r["composite_score"] = round(composite * 100)

    # Build DataFrame
    df = pd.DataFrame(base_results)
    df = df[["company", "title", "location", "composite_score",
             "skill_raw", "exp_raw", "loc_raw", "sal_raw", "tier", "url"]]
    df.columns = ["Company", "Title", "Location", "Score (%)",
                  "Skills", "Exp", "Loc", "Salary", "Tier", "URL"]
    df = df.sort_values("Score (%)", ascending=False).reset_index(drop=True)
    df.index += 1  # 1-based rank

    # --- Results table ---
    st.subheader("📊 Results")
    col_a, col_b = st.columns([1, 4])
    with col_a:
        min_score = st.slider("Minimum score", 0, 100, 0, 5)

    filtered_df = df[df["Score (%)"] >= min_score].copy()
    st.metric("Jobs shown", f"{len(filtered_df)} / {len(df)}")

    st.dataframe(
        filtered_df[["Company", "Title", "Location", "Score (%)",
                     "Skills", "Exp", "Loc", "Salary", "Tier"]],
        use_container_width=True,
        height=500,
    )

    # --- Score distribution ---
    st.subheader("📈 Score Distribution")
    col_c, col_d = st.columns(2)

    with col_c:
        st.bar_chart(filtered_df.set_index("Company")["Score (%)"].head(30))

    with col_d:
        tier_counts = filtered_df["Tier"].value_counts()
        st.bar_chart(tier_counts)

    # --- Regenerate MD files with new weights ---
    st.markdown("---")
    st.subheader("🔄 Regenerate Match Reports")
    st.markdown(
        f"Click below to regenerate all {len(df)} match report MD files "
        f"with the current weights and updated frontmatter (for Obsidian Dataview)."
    )
    st.warning("⚠️ This will overwrite existing match report files in `00_matches/`.")

    if st.button("🔄 Regenerate Match Reports", type="primary"):
        with st.spinner("Regenerating match reports..."):
            config = {
                "output_dir": str(OUTPUT_DIR),
                "min_salary_gbp": MIN_SALARY_GBP,
                "weights": weights,
            }

            # Clear old files
            old_files = glob.glob(os.path.join(str(MATCH_DIR), "match_*.md"))
            for f in old_files:
                os.remove(f)

            count = 0
            for job in jobs:
                match = analyze_match(job, config, weights=weights)
                if match["composite_score"] >= 0.50:
                    save_match_report(job, match, str(MATCH_DIR))
                    count += 1

            st.success(f"✅ Regenerated {count} match reports with new weights!")
            st.balloons()