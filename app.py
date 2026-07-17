"""
Job Scraper Pipeline — Unified Streamlit App
=============================================
Tabs:
  1. 🔍 Scraper    — search config, run scraper, view results
  2. 🎯 Weights    — adjust match-score weights, regenerate reports

Usage:
    cd /media/kz003/atelier/00_Kazuki/career/Job-Intelligence-System
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
OUTPUT_DIR = SCRAPER_DIR / "10_output"
ANALYZED_PATH = OUTPUT_DIR / "_analyzed.json"
MATCH_DIR = OUTPUT_DIR / "00_matches"
ASSET_WEAVER_SCRIPT = Path("/media/kz003/atelier/kazukiyunome/scripts/asset-weaver.py")

# Add scraper dir to path so we can import matcher
sys.path.insert(0, str(SCRAPER_DIR))
from matcher import (
    analyze_match,
    save_match_report,
    calculate_title_relevance,
    make_safe_name,
    DEFAULT_WEIGHTS,
)
from filter import passes_filter

MIN_SALARY_GBP = 30000

# --- Page Setup (must be first Streamlit call) ---
st.set_page_config(
    page_title="AI Job Scout System",
    page_icon="🔍",
    layout="wide",
)

# --- Theme: Override primary color to #944040 via CSS (keeps dark/light toggle) ---
st.markdown("""
<style>
/* Override primary accent color — works in both light and dark mode */
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background-color: #944040;
    border-color: #944040;
    color: white;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
    background-color: #7a3535;
    border-color: #7a3535;
}
/* Slider, progress bar, toggle accent */
.stSlider > div > div > div > div {
    color: #944040;
}
/* Links */
.stMarkdown a {
    color: #944040;
}
/* Active tab underline */
.stTabs > div > div > div > div[data-baseline*="Tab"] {
    color: #944040;
}
/* Checkbox accent */
.stCheckbox > div > div > div:nth-child(2) {
    border-color: #944040;
}
/* Metric value color */
.stMetric > div > div > div {
    color: #944040;
}
/* Streamlit primary color variable override */
:root {
    --primary-color: #944040;
}
[data-testid="stAppViewContainer"] {
    --primary-color: #944040;
}
/* Hide the Deploy button (meaningless for a local app) */
.stAppDeployButton { display: none; }
/* Accent pinned on every primary-colored widget so #944040 holds in both
   light and dark modes (Streamlit's built-in primary is red otherwise). */
[data-baseweb="tab-highlight"] { background-color: #944040 !important; }
[data-baseweb="checkbox"]:has(input[aria-checked="true"]) > span:first-of-type {
    background-color: #944040 !important;
    border-color: #944040 !important;
}
[data-baseweb="radio"]:has(input:checked) > div:first-of-type {
    border-color: #944040 !important;
    background-color: #944040 !important;
}
[data-baseweb="slider"] [role="slider"] {
    background-color: #944040 !important;
    border-color: #944040 !important;
}
[data-baseweb="input"]:focus-within,
[data-baseweb="select"] > div:focus-within,
[data-baseweb="textarea"]:focus-within {
    border-color: #944040 !important;
}
.stProgress > div > div > div > div { background-color: #944040 !important; }
/* Custom Title Style resembling Hermes Agent */
.jis-title {
    text-align: left;
    font-size: clamp(1.5rem, 5vw, 2.5rem);
    font-weight: 800;
    letter-spacing: 0.03em;
    margin-bottom: 1.5rem;
    line-height: 1.2;
}
</style>
""", unsafe_allow_html=True)

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
    if site == "saved":
        cmd = ["python3", "run.py", "--saved"]
    else:
        cmd = ["python3", "run.py", "--site", site, "--pages", str(pages)]
    process = subprocess.Popen(
        cmd, cwd=str(SCRAPER_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    for line in process.stdout:
        yield line
    process.wait()
    yield f"\n✅ Done! Exit code: {process.returncode}"


# ─────────────────────────────────────────────
# Title & Tabs
# ─────────────────────────────────────────────

# Theme switching is done via the native ⋮ menu; config.toml pins the dark
# base and the #944040 accent.
st.markdown('<h1 class="jis-title">AI Job Scout System</h1>', unsafe_allow_html=True)

tab_scraper, tab_weights, tab_watched, tab_review, tab_pdf = st.tabs(
    ["🔍 Scraper", "🎯 Weights", "👁 Saved", "🧐 Review", "📄 PDF"]
)

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
            help="Jobs with these words in the TITLE will be hidden. Uses word-boundary matching: 'senior' matches 'Senior Developer' but NOT 'leadership'. Description text like 'cooperate with senior engineers' is NOT filtered — only the title is checked.",
        )
        # Quick preset button for common seniority exclusions
        if st.button("⚡ Add Entry/Mid Preset", help="Add senior, lead, principal, head of, director, manager to title exclusions"):
            current = [k.strip() for k in exclude_title_text.split("\n") if k.strip()]
            presets = ["senior", "lead", "principal", "head of", "director", "manager"]
            merged = sorted(set(current + presets))
            exclude_title_text = "\n".join(merged)
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
            options=["indeed", "linkedin", "reed", "guardian", "adzuna"],
            default=st.session_state.config.get("sites", ["indeed"]),
        )
        max_pages = st.slider(
            "Pages per search", 1, 10, st.session_state.config.get("max_pages_per_search", 3)
        )
        levels = st.multiselect(
            "Experience Levels",
            options=["internship", "entry_level", "mid", "senior", "director"],
            default=st.session_state.config.get("include_levels", ["entry_level", "mid", "senior"]),
        )
        emp_types = st.multiselect(
            "Employment Types",
            options=["full_time", "part_time", "contract", "internship", "freelance"],
            default=st.session_state.config.get("employment_types", ["full_time", "part_time", "contract"]),
        )
        cv_threshold = st.slider(
            "📄 CV & Cover Letter Generation Threshold", 
            0.0, 1.0, float(st.session_state.config.get("match_score_threshold", 0.50)), 0.05,
            help="Minimum match score required to generate a tailored CV and Cover Letter."
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
            "match_score_threshold": cv_threshold,
        }
        save_config(st.session_state.config)
        st.success("✅ Configuration saved! Run `python3 run.py --reanalyze` in your terminal to apply the new threshold.")

    # === Section 2: Run Scraper ===
    st.subheader("🚀 Run Scraper")

    col3, col4 = st.columns([1, 3])
    with col3:
        selected_site = st.selectbox("Site", options=["indeed", "linkedin", "reed", "guardian", "adzuna", "all"])
        run_pages = st.number_input("Pages", min_value=1, max_value=10, value=3)

    with col4:
        if st.button("🚀 Run Selected Scraper"):
            with st.spinner(f"Running scraper for {selected_site}..."):
                for line in run_scraper(site=selected_site, pages=run_pages):
                    st.code(line)

        if st.button("Run All Scrapers (Saved + All Main)"):
                with st.spinner("Running scraper for saved jobs & all main sites..."):
                    for line in run_scraper(site="saved", pages=run_pages):
                        st.code(line)
                    for line in run_scraper(site="all", pages=run_pages):
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
                ok, _ = passes_filter(j, st.session_state.config)
                if not ok:
                    continue
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
                    "Context": f"{match.get('context_score', 0)*100:.0f}%",
                    "Tier": tier,
                    "Company": j.get("company", "?"),
                    "Title": j.get("title", "?"),
                    "Location": j.get("location", "?"),
                    "Level": level,
                    "Work": work_style,
                    "Salary": salary_str,
                    "Skills": skill_str,
                    "Reasoning": match.get("context_reasoning", ""),
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

            filtered_jobs = [j for j in jobs_with_score if float(j["Score"].strip("%")) >= min_score_filter]

            if filtered_jobs:
                st.dataframe(
                    [
                        {
                            "🎯": j["Score"],
                            "🧠": j["Context"],
                            "Company": j["Company"],
                            "Title": j["Title"],
                            "📍": j["Location"],
                            "💰": j["Salary"],
                            "Level": j["Work"],
                            "Skills": j["Skills"],
                            "URL": j["url"],
                        }
                        for j in filtered_jobs
                    ],
                    column_config={
                        "🎯": st.column_config.Column(width="small"),
                        "🧠": st.column_config.Column(width="small"),
                        "URL": st.column_config.LinkColumn(width="small", display_text="🔗 Open"),
                        "Skills": st.column_config.Column(width="large"),
                    },
                    use_container_width=True,
                    height=500,
                )

                st.subheader("💡 Context Insights")
                selected_title = st.selectbox("Select a job to see why it matches:", [j["Title"] for j in filtered_jobs])
                for j in filtered_jobs:
                    if j["Title"] == selected_title:
                        with st.expander("View Philosophy Alignment Reasoning", expanded=True):
                            st.info(j["Reasoning"] if j["Reasoning"] else "No context reasoning available.")
                        break
            else:
                st.warning("No jobs match the selected score filter.")

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
- [View output folder](10_output/00_matches/)
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
    def load_jobs(config):
        with open(ANALYZED_PATH) as f:
            all_jobs = json.load(f)
        passed = []
        for j in all_jobs:
            ok, _ = passes_filter(j, config)
            if ok:
                passed.append(j)
        return passed

    @st.cache_data(ttl=60)
    def get_base_scores(jobs_json_str: str):
        """Pre-calculate individual dimension scores (without weights) so we can
        re-compute the weighted composite instantly when sliders change.
        Uses pre-computed scores from _analyzed.json instead of re-running analyze_match
        (which would invoke Ollama LLM for every job — extremely slow)."""
        jobs = json.loads(jobs_json_str)
        results = []
        for job in jobs:
            match = job.get("match", {})
            # Use pre-computed scores from _analyzed.json
            results.append({
                "company": job.get("company", "Unknown"),
                "title": job.get("title", "Unknown"),
                "location": job.get("location", "Unknown"),
                "url": job.get("url", ""),
                "skill_raw": match.get("skills", {}).get("score", 0),
                "exp_raw": match.get("experience", {}).get("score", 0),
                "loc_raw": match.get("location", {}).get("score", 0),
                "sal_raw": match.get("salary", {}).get("score", 0),
                "ctx_raw": match.get("context_score", 0.5),
                "title_relevance": calculate_title_relevance(job.get("title", "")),
                "tier": match.get("tier", ""),
            })
        return results

    try:
        jobs = load_jobs(st.session_state.config)
    except FileNotFoundError:
        st.error(f"Analyzed jobs file not found at {ANALYZED_PATH}. Run the scraper first.")
        st.stop()

    # --- Weight Sliders ---
    st.subheader("⚖️ Weight Configuration")

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
        composite = composite * r.get("title_relevance", 1.0)
        r["composite_score"] = round(composite * 100)

    # Build DataFrame
    df = pd.DataFrame(base_results)
    df = df[["company", "title", "location", "composite_score",
             "skill_raw", "exp_raw", "loc_raw", "sal_raw", "ctx_raw", "tier", "url"]]
    df.columns = ["Company", "Title", "Location", "Score (%)",
                  "Skills", "Exp", "Loc", "Salary", "Context", "Tier", "URL"]
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
                     "Skills", "Exp", "Loc", "Salary", "Context", "Tier"]],
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
            config["weights"]["context"] = norm_context

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

# ═══════════════════════════════════════════════════════════
# Tab 3: Kanban Board
# ═══════════════════════════════════════════════════════════

KANBAN_DIR = OUTPUT_DIR / "00_kanban"
KANBAN_FILE = KANBAN_DIR / "kanban.json"

KANBAN_STATUSES = {
    "📌 Saved": 0,
    "📝 Applied": 1,
    "🔍 Screening": 2,
    "📞 Interviewing": 3,
    "💼 Offer": 4,
    "✅ Accepted": 5,
    "❌ Rejected": 6,
    "🗑️ Archived": 7,
}

def load_kanban_data():
    """Load or initialise kanban status for each job (keyed by URL)."""
    if KANBAN_FILE.exists():
        with open(KANBAN_FILE) as f:
            return json.load(f)
    return {}

def save_kanban_data(data):
    KANBAN_DIR.mkdir(parents=True, exist_ok=True)
    with open(KANBAN_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# --- PDF export (CV / Cover Letter) ---
PDF_DIR = OUTPUT_DIR / "20_pdfs"
# Static-serving copy dir: files under ./static are served at <app>/app/static/
STATIC_PDF_DIR = SCRAPER_DIR / "static" / "pdfs"
CV_DIR = OUTPUT_DIR / "10_cvs"
CL_DIR = OUTPUT_DIR / "10_cover-letters"


def _md_to_pdf_bytes(md_path: Path) -> bytes:
    """Render a generated CV/CL markdown file to a clean A4 PDF."""
    # Lazy imports: weasyprint is slow to load and only needed on demand
    import markdown as _markdown
    from weasyprint import HTML

    text = md_path.read_text(encoding="utf-8")
    # Strip YAML frontmatter (Obsidian metadata, not for the PDF)
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
    # Obsidian wiki-links → plain text ([[target|label]] → label)
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)

    # Generated CVs/CLs are near-plain text: ALL-CAPS section lines, "•" bullets,
    # and meaningful single line breaks. Preprocess into real markdown.
    lines = text.strip().split("\n")
    out_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped and not stripped.startswith("#"):
            out_lines.append(f"# {stripped}")  # first line = candidate name
        elif re.fullmatch(r"[A-Z][A-Z &/'’\-]{2,40}", stripped):
            out_lines.append(f"\n## {stripped}")  # ALL-CAPS section header
        elif stripped.startswith("•"):
            out_lines.append("- " + stripped.lstrip("• "))
        else:
            out_lines.append(line)
    text = "\n".join(out_lines)

    body = _markdown.markdown(text, extensions=["tables", "fenced_code", "nl2br"])
    html = f"""<html><head><meta charset="utf-8"><style>
        @page {{ size: A4; margin: 18mm 16mm; }}
        body {{ font-family: "DejaVu Sans", sans-serif; font-size: 10.5pt; line-height: 1.45; color: #1a1a1a; }}
        h1 {{ font-size: 17pt; margin: 0 0 4pt; }}
        h2 {{ font-size: 12.5pt; border-bottom: 1px solid #999; padding-bottom: 2pt; margin: 14pt 0 6pt; }}
        h3 {{ font-size: 11pt; margin: 10pt 0 3pt; }}
        p, li {{ margin: 3pt 0; }}
        ul {{ padding-left: 14pt; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ccc; padding: 3pt 6pt; text-align: left; }}
        a {{ color: #1a1a1a; text-decoration: none; }}
    </style></head><body>{body}</body></html>"""
    return HTML(string=html).write_pdf()


_PDF_VERSIONS_META = PDF_DIR / ".pdf_versions.json"


def _version_filename(stem: str, n: int) -> str:
    """v1 keeps the bare name (backward compatible); v2+ gets a _vN suffix."""
    return f"{stem}.pdf" if n == 1 else f"{stem}_v{n}.pdf"


def _pdf_versions(stem: str) -> list[tuple[int, Path]]:
    """Existing PDF versions for a stem, ascending: [(1, stem.pdf), (2, stem_v2.pdf), ...]."""
    import re
    out = []
    p1 = PDF_DIR / f"{stem}.pdf"
    if p1.exists():
        out.append((1, p1))
    for p in PDF_DIR.glob(f"{stem}_v*.pdf"):
        m = re.fullmatch(rf"{re.escape(stem)}_v(\d+)\.pdf", p.name)
        if m:
            out.append((int(m.group(1)), p))
    out.sort()
    return out


def _load_pdf_meta() -> dict:
    import json
    try:
        return json.loads(_PDF_VERSIONS_META.read_text())
    except Exception:
        return {}


def _save_pdf_meta(meta: dict):
    import json
    PDF_DIR.mkdir(exist_ok=True)
    _PDF_VERSIONS_META.write_text(json.dumps(meta, indent=2))


def _convert_pdf_versioned(md_path: Path) -> tuple[Path, int, bool]:
    """Render md_path to a PDF, versioning by source-MD content.

    If the current markdown is identical to the newest existing version's
    source, reuse that PDF (no pointless duplicate). Otherwise mint the
    next sequential version (highest existing number + 1). Returns
    (pdf_path, version_number, is_new).
    """
    import hashlib
    stem = md_path.stem
    md_sha = hashlib.sha1(md_path.read_bytes()).hexdigest()
    versions = _pdf_versions(stem)
    meta = _load_pdf_meta()

    if versions:
        latest_n, latest_path = versions[-1]
        if meta.get(latest_path.name) == md_sha and latest_path.exists():
            return latest_path, latest_n, False  # unchanged — reuse
        n = latest_n + 1
    else:
        n = 1

    PDF_DIR.mkdir(exist_ok=True)
    target = PDF_DIR / _version_filename(stem, n)
    target.write_bytes(_md_to_pdf_bytes(md_path))
    meta[target.name] = md_sha
    _save_pdf_meta(meta)
    return target, n, True


def _static_pdf_link(pdf_path: Path, label: str) -> str:
    """Copy a PDF into the static-served dir and return an <a download> tag."""
    import shutil
    import urllib.parse
    STATIC_PDF_DIR.mkdir(parents=True, exist_ok=True)
    static_copy = STATIC_PDF_DIR / pdf_path.name
    if not static_copy.exists() or static_copy.stat().st_mtime < pdf_path.stat().st_mtime:
        shutil.copyfile(pdf_path, static_copy)
    href = "/app/static/pdfs/" + urllib.parse.quote(static_copy.name)
    return (
        f'<a href="{href}" download="{static_copy.name}" target="_blank" rel="noopener">'
        f'{label}</a>'
    )


def _set_report_doc_property(md_path: Path, key_suffix: str, target_name: str):
    """Set a cv_*/cl_* wikilink property on the match report's frontmatter.

    md_path is the CV/CL markdown (…_CV.md / …_CL.md); the report shares its
    base name. key_suffix "pdf" → cv_pdf/cl_pdf, "review" → cv_review/cl_review.
    Frontmatter properties keep these Dataview-queryable from the report.
    """
    import re
    stem = md_path.stem
    if stem.endswith("_CV"):
        key, base = f"cv_{key_suffix}", stem[:-3]
    elif stem.endswith("_CL"):
        key, base = f"cl_{key_suffix}", stem[:-3]
    else:
        return
    report = MATCH_DIR / f"{base}.md"
    if not report.exists():
        return
    text = report.read_text(encoding="utf-8")
    m = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not m:
        return
    line = f'{key}: "[[{target_name}]]"'
    fm = m.group(1)
    if re.search(rf"^{key}:.*$", fm, flags=re.MULTILINE):
        fm = re.sub(rf"^{key}:.*$", line, fm, flags=re.MULTILINE)
    else:
        fm = fm + "\n" + line
    report.write_text(f"---\n{fm}\n---\n" + text[m.end():], encoding="utf-8")


def _set_report_pdf_property(md_path: Path, pdf_name: str):
    _set_report_doc_property(md_path, "pdf", pdf_name)


def resolve_doc_base(company: str, title: str, url: str = "") -> str:
    """Filename base for a job's CV/CL/report; falls back to the URL-hash
    suffixed variant generate_outputs() uses on company+title collisions."""
    import hashlib
    base = make_safe_name(company, title)
    hashed = f"{base}_{hashlib.md5((url or '').encode()).hexdigest()[:6]}"
    if not (CV_DIR / f"{base}_CV.md").exists() and (CV_DIR / f"{hashed}_CV.md").exists():
        return hashed
    return base


def ranked_job_rows(all_jobs: list[dict]) -> list[dict]:
    """URL-deduped jobs sorted by match score desc, with doc-file existence.
    Shared by the Review and PDF tabs."""
    job_map = {}
    for j in all_jobs:
        url = j.get("url", "")
        if url:
            job_map[url] = j
    rows = []
    for url, j in job_map.items():
        match = j.get("match", {})
        base = resolve_doc_base(j.get("company", "company"), j.get("title", "job"), url)
        has_cv = (CV_DIR / f"{base}_CV.md").exists()
        has_cl = (CL_DIR / f"{base}_CL.md").exists()
        rows.append({
            "url": url,
            "company": j.get("company", "?"),
            "title": j.get("title", "?"),
            "score": match.get("composite_score", 0),
            "tier": match.get("tier", ""),
            "base": base,
            "has_cv": has_cv,
            "has_cl": has_cl,
            "has_docs": has_cv or has_cl,
            "job": j,
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def _tier_icon(tier: str) -> str:
    return {"Strong": "🟢", "Good": "🟡", "Partial": "🟠", "Weak": "🔴"}.get(
        tier.split()[-2] if tier else "", "⚪"
    )


def review_doc_controls(label: str, md_path: Path, job: dict, key_prefix: str):
    """Run/show the LLM review for ONE document (CV or CL). The review is a
    findings list, never a rewrite — the user's manual edit stays final."""
    import re
    from reviewer import run_review, review_is_current, REVIEW_MODEL
    if not md_path.exists():
        st.caption(f"{label}: —")
        return
    is_cur, rpath = review_is_current(md_path)
    if st.button(f"🧐 Review {label}", key=f"rev_{key_prefix}_{label}"):
        with st.spinner(f"Reviewing {label} with {REVIEW_MODEL}…"):
            try:
                rpath = run_review(label, md_path, job)
                _set_report_doc_property(md_path, "review", rpath.stem)
                is_cur = True
                st.success(f"{label} review saved → 15_reviews/{rpath.name}")
            except Exception as e:
                st.error(f"Review failed: {e}")
    if rpath and rpath.exists():
        status = "current" if is_cur else "⚠️ doc edited since this review"
        with st.expander(f"{label} review ({status})"):
            text = rpath.read_text(encoding="utf-8")
            m = re.match(r"\A---\n.*?\n---\n", text, flags=re.DOTALL)
            st.markdown(text[m.end():] if m else text)


def pdf_doc_controls(label: str, md_path: Path, key_prefix: str):
    """Inline convert-button + versioned download links for ONE document
    (a CV or a CL). PDFs are saved to 10_output/20_pdfs/ with sequential
    versioning — editing the source .md and re-converting mints v2, v3, …
    while identical re-conversions reuse the latest version."""
    import hashlib
    if not md_path.exists():
        st.caption(f"{label}: —")
        return
    if st.button(f"{label} → PDF", key=f"conv_{key_prefix}_{label}"):
        try:
            _pdf_path, ver, is_new = _convert_pdf_versioned(md_path)
            _set_report_pdf_property(md_path, _pdf_path.name)
            if is_new:
                st.success(f"{label} → v{ver} created")
            else:
                st.info(f"{label} unchanged since v{ver} — reusing")
        except Exception as e:
            st.error(f"PDF conversion failed: {e}")

    # List every version (newest first) as a download link. The
    # highest-numbered version is only labeled "latest" if it was
    # actually generated from the CURRENT .md content — otherwise the
    # .md was edited since that PDF was made and the link is stale
    # (this is exactly the bug that shipped once: editing the CV and
    # re-downloading the old, unconverted PDF without noticing).
    versions = _pdf_versions(md_path.stem)
    if versions:
        latest_n, latest_path = versions[-1]
        current_sha = hashlib.sha1(md_path.read_bytes()).hexdigest()
        meta = _load_pdf_meta()
        is_current = meta.get(latest_path.name) == current_sha
        if not is_current:
            st.caption(f"⚠️ edited since v{latest_n} — reconvert")
        for n, pdf_path in reversed(versions):
            if n == latest_n:
                suffix = " (latest)" if is_current else " (outdated)"
            else:
                suffix = ""
            link = _static_pdf_link(pdf_path, f"⬇ {label} v{n}{suffix}")
            st.markdown(link, unsafe_allow_html=True)


with tab_review:
    st.header("🧐 Document Review")
    st.markdown(
        "LLM proofreading BEFORE PDF export: checks your (hand-edited) CV/CL "
        "against the job posting and your verified profile — factual claims, "
        "job-fit gaps, style. Findings only; it never rewrites your text. "
        "Reviews are saved to `15_reviews/` and linked from the match report."
    )

    try:
        all_jobs = load_jobs(st.session_state.config)
    except FileNotFoundError:
        st.error("No job data found. Run the scraper first (🔍 Scraper tab).")
        st.stop()

    rows = ranked_job_rows(all_jobs)

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        min_score = st.slider("Min score", 0, 100, 50, key="review_min_score")
    with col_f2:
        search_query = st.text_input("🔍 Search company/title", key="review_search")

    filtered = [
        r for r in rows
        if r["score"] * 100 >= min_score
        and r["has_docs"]
        and (not search_query
             or search_query.lower() in r["company"].lower()
             or search_query.lower() in r["title"].lower())
    ]
    st.metric("Showing", f"{len(filtered)} jobs")

    for r in filtered[:50]:
        c_score, c_job = st.columns([1, 7])
        with c_score:
            st.markdown(f"{_tier_icon(r['tier'])} `{r['score']*100:.0f}%`")
        with c_job:
            st.markdown(f"**{r['company']}** — {r['title'][:70]}")
        c_cv, c_cl = st.columns(2)
        with c_cv:
            review_doc_controls("CV", CV_DIR / f"{r['base']}_CV.md", r["job"], f"rv_{r['url']}")
        with c_cl:
            review_doc_controls("CL", CL_DIR / f"{r['base']}_CL.md", r["job"], f"rv_{r['url']}")
        st.divider()
    if len(filtered) > 50:
        st.caption(f"…and {len(filtered)-50} more — raise Min score or search to narrow down.")


with tab_pdf:
    st.header("📄 PDF Export")
    st.markdown(
        "Jobs ranked by match score. Convert each CV/CL markdown to a versioned PDF "
        "and download it. Application-status tracking lives in Obsidian "
        "(`10_output/Applications.md`, Kanban plugin board)."
    )

    try:
        all_jobs = load_jobs(st.session_state.config)
    except FileNotFoundError:
        st.error("No job data found. Run the scraper first (🔍 Scraper tab).")
        st.stop()

    rows = ranked_job_rows(all_jobs)

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        min_score = st.slider("Min score", 0, 100, 50, key="pdf_min_score")
    with col_f2:
        only_docs = st.checkbox("Only jobs with CV/CL", value=True, key="pdf_only_docs")
    with col_f3:
        search_query = st.text_input("🔍 Search company/title", key="pdf_search")

    filtered = [
        r for r in rows
        if r["score"] * 100 >= min_score
        and (not only_docs or r["has_docs"])
        and (not search_query
             or search_query.lower() in r["company"].lower()
             or search_query.lower() in r["title"].lower())
    ]
    st.metric("Showing", f"{len(filtered)} jobs")

    for r in filtered[:100]:
        c_score, c_job, c_cv, c_cl = st.columns([1, 4, 2, 2])
        with c_score:
            st.markdown(f"{_tier_icon(r['tier'])} `{r['score']*100:.0f}%`")
        with c_job:
            st.markdown(f"**{r['company']}** — {r['title'][:70]}")
        with c_cv:
            pdf_doc_controls("CV", CV_DIR / f"{r['base']}_CV.md", f"pdf_{r['url']}")
        with c_cl:
            pdf_doc_controls("CL", CL_DIR / f"{r['base']}_CL.md", f"pdf_{r['url']}")
        st.divider()
    if len(filtered) > 100:
        st.caption(f"…and {len(filtered)-100} more — raise Min score or search to narrow down.")


# ═════════════════════════════════════════════════════════
# Tab 4: Watched & Saved
# ═════════════════════════════════════════════════════════

WATCHED_DIR = SCRAPER_DIR / "00_saved" / "watched-list"
SAVED_DIR = SCRAPER_DIR / "00_saved"

with tab_watched:
    st.header("👁 Saved Jobs")

    st.markdown("""
    Two additional job-collection routes beyond the main scraper:

    - **B: URL List** — Paste job detail page URLs into `00_saved/url-list.md`, then auto-scrape & extract with AI.
    - **C: Watched List** — Manually paste job descriptions into `00_saved/watched-list/*.md`, then analyze them against your profile.
    """)

    # --- Process management helpers ---
    def _kill_process(key: str):
        """Terminate a background subprocess stored in session_state."""
        proc = st.session_state.get(key)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        st.session_state[key] = None
        st.session_state.pop(f"{key}_running", None)

    # Initialize process state
    for _key in ["saved_proc", "watched_proc", "analysis_proc"]:
        if _key not in st.session_state:
            st.session_state[_key] = None
        if f"{_key}_running" not in st.session_state:
            st.session_state[f"{_key}_running"] = False
        if f"{_key}_output" not in st.session_state:
            st.session_state[f"{_key}_output"] = []

    # ════════════════════════════════════════
    # Section B: URL List Scraper
    # ════════════════════════════════════════
    st.subheader("🔗 B: URL List Scraper & Matcher")
    st.caption("""
        Add job detail page URLs to `00_saved/url-list.md` (one per line). 
        First, click **Start URL List Scrape** to extract job description texts with AI.
        Once scraping is done, click **Run Match Analysis** to evaluate matches and generate CVs.
    """)

    # Show url-list.md contents & count
    url_list_path = SCRAPER_DIR / "00_saved" / "url-list.md"
    url_list_jobs_path = SCRAPER_DIR / "00_saved" / "url_list_jobs.json"
    if url_list_path.exists():
        import re as _re
        _urls = _re.findall(r'https?://[^\s)\]]+', url_list_path.read_text(encoding="utf-8"))
        st.metric("URLs in url-list.md", len(_urls))
        if _urls:
            with st.expander(f"View {len(_urls)} URLs"):
                for u in _urls:
                    st.text(f"  🔗 {u}")
    else:
        st.info("`00_saved/url-list.md` not found. It will be created on first run.")

    if url_list_jobs_path.exists():
        import json as _json
        try:
            _url_jobs = _json.loads(url_list_jobs_path.read_text(encoding="utf-8"))
            st.metric("Extracted Jobs (url_list_jobs.json)", len(_url_jobs))
        except Exception:
            pass

    col_b1, col_b2, col_b3 = st.columns([1.5, 1.5, 3])

    # ── Mutual exclusion: scrape and analysis can't run simultaneously ──
    scrape_running = st.session_state.saved_proc is not None and st.session_state.saved_proc.poll() is None
    analysis_running = st.session_state.analysis_proc is not None and st.session_state.analysis_proc.poll() is None
    _any_b_running = scrape_running or analysis_running

    with col_b1:
        if not scrape_running:
            if st.button("▶ Start URL List Scrape", type="primary", key="start_saved", disabled=_any_b_running):
                cmd = [sys.executable, "-u", "scraper_url_list.py"]
                st.session_state.saved_proc = subprocess.Popen(
                    cmd, cwd=str(SCRAPER_DIR),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                st.session_state.saved_running = True
                st.session_state.saved_proc_output = [] # Clear previous log
                st.rerun()
        else:
            if st.button("⏹ Stop Scrape", type="secondary", key="stop_saved", disabled=not scrape_running):
                _kill_process("saved_proc")
                st.rerun()

    with col_b2:
        if not analysis_running:
            if st.button("🎯 Run Match Analysis", type="primary", key="start_analysis", disabled=_any_b_running):
                cmd = [sys.executable, "-u", "run.py", "--from-saved"]
                st.session_state.analysis_proc = subprocess.Popen(
                    cmd, cwd=str(SCRAPER_DIR),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                st.session_state.analysis_running = True
                st.session_state.analysis_proc_output = [] # Clear previous log
                st.rerun()
        else:
            if st.button("⏹ Stop Analysis", type="secondary", key="stop_analysis", disabled=not analysis_running):
                _kill_process("analysis_proc")
                st.rerun()

    # Show lock warning
    if _any_b_running:
        _running_label = "Scrape" if scrape_running else "Analysis"
        st.caption(f"⏳ {_running_label} is running — the other action is disabled to prevent file conflicts.")

    with col_b3:
        # Show status/output for scrape
        if st.session_state.saved_proc is not None:
            proc = st.session_state.saved_proc
            # Drain available output lines (non-blocking)
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    st.session_state.saved_proc_output.append(line.rstrip())
            except Exception:
                pass

            st.info(f"Scraper running (PID {proc.pid})" if proc.poll() is None else f"Scraper finished (exit code {proc.returncode})")

            if st.session_state.saved_proc_output:
                with st.expander("Scraper Output", expanded=True):
                    st.code("\n".join(st.session_state.saved_proc_output[-100:]))

            if proc.poll() is None:
                import time
                time.sleep(2)
                st.rerun()
            else:
                st.success(f"✅ Scraper Finished (exit code {proc.returncode})")
                st.session_state.saved_proc = None

        # Show status/output for analysis
        elif st.session_state.analysis_proc is not None:
            proc = st.session_state.analysis_proc
            # Drain available output lines (non-blocking)
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    st.session_state.analysis_proc_output.append(line.rstrip())
            except Exception:
                pass

            st.info(f"Analyzer running (PID {proc.pid})" if proc.poll() is None else f"Analyzer finished (exit code {proc.returncode})")

            if st.session_state.analysis_proc_output:
                with st.expander("Analyzer Output", expanded=True):
                    st.code("\n".join(st.session_state.analysis_proc_output[-100:]))

            if proc.poll() is None:
                import time
                time.sleep(2)
                st.rerun()
            else:
                st.success(f"✅ Analysis Finished (exit code {proc.returncode})")
                st.session_state.analysis_proc = None
        else:
            st.caption("Not running. Choose an action to start.")


    # ════════════════════════════════════════
    # Section C: Watched List (manual paste → match)
    # ════════════════════════════════════════
    st.divider()
    st.subheader("📁 C: Watched List (Manual Paste → Match)")
    st.caption("Drop `.md` files into `00_saved/watched-list/` with a job description, then run match analysis.")

    # Show watched directory contents
    if WATCHED_DIR.exists():
        watched_files = sorted([f for f in WATCHED_DIR.glob("*.md") if f.name != "README.md"])
        st.metric("Watched MDs", len(watched_files))
        if watched_files:
            with st.expander(f"View {len(watched_files)} watched files"):
                for f in watched_files:
                    st.text(f"  📄 {f.name}")
    else:
        st.warning("`00_saved/watched-list/` directory not found. It will be created on first run.")

    col_c1, col_c2 = st.columns([1, 3])
    with col_c1:
        c_running = st.session_state.watched_proc is not None and st.session_state.watched_proc.poll() is None
        use_llm = st.checkbox("Use LLM Context Score", value=False, key="watched_llm", help="Run Ollama gemma4:26b for deeper context matching (slower)")
        if not c_running:
            if st.button("▶ Run Watched Match", type="primary", key="start_watched", disabled=c_running):
                cmd = [sys.executable, "-u", "watched_matcher.py"]
                if use_llm:
                    cmd.append("--llm-context")
                st.session_state.watched_proc = subprocess.Popen(
                    cmd, cwd=str(SCRAPER_DIR),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                st.session_state.watched_running = True
                st.session_state.watched_proc_output = [] # Clear previous log
                st.rerun()
        else:
            if st.button("⏹ Stop", type="secondary", key="stop_watched", disabled=not c_running):
                _kill_process("watched_proc")
                st.rerun()

    with col_c2:
        proc = st.session_state.watched_proc
        if proc is not None:
            # Drain available output lines (non-blocking)
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    st.session_state.watched_proc_output.append(line.rstrip())
            except Exception:
                pass

            st.info(f"Process running (PID {proc.pid})" if proc.poll() is None else f"Process finished (exit code {proc.returncode})")

            if st.session_state.watched_proc_output:
                with st.expander("Output", expanded=True):
                    st.code("\n".join(st.session_state.watched_proc_output[-100:]))

            if proc.poll() is None:
                import time
                time.sleep(2)
                st.rerun()
            else:
                st.success(f"✅ Finished (exit code {proc.returncode})")
                st.session_state.watched_proc = None
        else:
            st.caption("Not running. Press Start to analyze `00_saved/watched-list/` MDs against your profile.")

    # Show watched match reports
    watched_reports = sorted(MATCH_DIR.glob("watched_*.md")) if MATCH_DIR.exists() else []
    if watched_reports:
        st.divider()
        st.subheader("📊 Watched Match Reports")
        for report in watched_reports:
            with st.expander(f"📄 {report.stem}"):
                content = report.read_text(encoding="utf-8", errors="replace")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        frontmatter = parts[1].strip()
                        body = parts[2].strip()
                        st.text(frontmatter)
                        st.markdown(body[:2000] + ("..." if len(body) > 2000 else ""))
                    else:
                        st.text(content[:2000])
                else:
                    st.text(content[:2000])