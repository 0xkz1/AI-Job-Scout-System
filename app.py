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
import signal
import json
import os
import re
import sys
import glob
import yaml
from datetime import datetime
from pathlib import Path

import pandas as pd

# --- Paths ---
SCRAPER_DIR = Path(__file__).parent
CONFIG_PATH = SCRAPER_DIR / "config.yaml"
OUTPUT_DIR = SCRAPER_DIR / "10_output"
ANALYZED_PATH = OUTPUT_DIR / "_analyzed.json"
MATCH_DIR = OUTPUT_DIR / "00_matches"
ASSET_WEAVER_SCRIPT = Path("/media/kz003/atelier/kazukiyunome/scripts/asset-weaver.py")


class _AdoptedProcess:
    """A chain started by an earlier Streamlit session, spoken to by PID.

    Popen objects do not survive an auto-reload, and the run they refer to
    does. This stands in for one so the reporting block needs no special case:
    it answers poll() and returncode from whether the PID is still alive.

    Only ever adopts a process this app started (its PID is read back from the
    state file the launcher wrote), and the exit code is unknowable from
    outside — a finished adopted run reports 0 and the log carries the truth.
    """

    def __init__(self, pid: int):
        self.pid = pid
        self.returncode = None

    def poll(self):
        try:
            os.kill(self.pid, 0)
        except OSError:
            self.returncode = 0
            return 0
        return None

    def terminate(self):
        try:
            os.kill(self.pid, signal.SIGTERM)
        except OSError:
            pass

    def kill(self):
        try:
            os.kill(self.pid, signal.SIGKILL)
        except OSError:
            pass

    def wait(self, timeout=None):
        return self.poll()

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
    # sys.executable, not "python3": the venv is not on PATH, so a bare
    # python3 resolves to the system interpreter and fails on imports.
    if site == "saved":
        cmd = [sys.executable, "-u", "run.py", "--saved"]
    else:
        cmd = [sys.executable, "-u", "run.py", "--site", site, "--pages", str(pages)]
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

tab_scraper, tab_watched, tab_analysis, tab_review, tab_pdf = st.tabs(
    ["🔍 Scraper", "👁 Saved", "🎯 Match Analysis", "🧐 Review", "📄 PDF"]
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
            key="exclude_title_text",
            help="Jobs with these words in the TITLE will be hidden. Uses word-boundary matching: 'senior' matches 'Senior Developer' but NOT 'leadership'. Description text like 'cooperate with senior engineers' is NOT filtered — only the title is checked.",
        )
        # Quick preset button for common seniority exclusions. Merging into the
        # in-memory config + rerun is the only way to move a widget's value —
        # assigning to the local variable after the widget renders is a no-op.
        if st.button("⚡ Add Entry/Mid Preset", help="Add senior, lead, principal, head of, director, manager to title exclusions"):
            presets = ["senior", "lead", "principal", "head of", "director", "manager"]
            current = [k.strip() for k in exclude_title_text.split("\n") if k.strip()]
            st.session_state.config["exclude_title_keywords"] = sorted(set(current + presets))
            del st.session_state["exclude_title_text"]  # let the widget re-read config
            st.rerun()
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
            options=["indeed", "linkedin", "reed", "guardian", "adzuna", "remote_apis"],
            default=st.session_state.config.get("sites", ["indeed"]),
        )
        max_pages = st.slider(
            "Pages per search", 1, 10, st.session_state.config.get("max_pages_per_search", 3),
            help="Overrides config.yaml's per-site depth (max_pages_per_site) for this "
                 "run — every site uses this number. Depth is the main driver of "
                 "runtime: reed measured ~68s per search at depth 6, so raising this "
                 "past 3 pushes a full run past the 1500s nightly timeout.",
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
        # --- Per-stage selection: one top-% number governs each stage ---
        st.markdown("**🎯 対象範囲(上位N%)** — 各段階が処理する求人の割合")
        gen_percent = st.slider(
            "📄 CV+CL 生成対象 (generation_top_percent)",
            1, 100, int(st.session_state.config.get("generation_top_percent", 20)), 1,
            help="ランク付き求人プールの上位何%にCV+カバーレターを生成するか。"
        )
        review_percent = st.slider(
            "🧐 レビュー対象 (review_top_percent)",
            1, 100, int(st.session_state.config.get("review_top_percent", 20)), 1,
            help="上位何%を再レビューするか。生成と揃えると整合が取れる。"
        )
        # Live "top N% = how many jobs" readout from the current pool.
        try:
            from selection import ranked_jobs, top_percent_count
            _pool = len(ranked_jobs(st.session_state.config))
            st.caption(
                f"現在の母数 {_pool}件 → 生成 上位{gen_percent}% = "
                f"**{top_percent_count(_pool, gen_percent)}件** / "
                f"レビュー 上位{review_percent}% = "
                f"**{top_percent_count(_pool, review_percent)}件**"
            )
        except Exception:
            pass

        cv_threshold = st.slider(
            "📄 品質下限スコア (match_score_threshold)",
            0.0, 1.0, float(st.session_state.config.get("match_score_threshold", 0.60)), 0.05,
            help="上位N%内でも、このスコア未満の求人にはCVを生成しない品質下限。0で無効。"
        )
        review_threshold = st.slider(
            "🧐 Review Submission Threshold",
            0, 100, int(st.session_state.config.get("review_score_threshold", 85)), 1,
            help="Minimum review score required for a CV/CL to be considered ready for submission."
        )

    if st.button("💾 Save Configuration"):
        # Merge onto the existing config so keys not exposed here (weights,
        # cv_generation_limit, output_dir, …) are preserved, not dropped.
        st.session_state.config.update({
            "keywords": [k.strip() for k in keywords_text.split("\n") if k.strip()],
            "locations": [l.strip() for l in locations_text.split("\n") if l.strip()],
            "sites": sites,
            "min_salary_gbp": min_salary,
            "max_pages_per_search": max_pages,
            "include_levels": levels,
            "employment_types": emp_types,
            "exclude_title_keywords": [k.strip() for k in exclude_title_text.split("\n") if k.strip()],
            "exclude_description_keywords": [k.strip() for k in exclude_desc_text.split("\n") if k.strip()],
            "generation_top_percent": gen_percent,
            "review_top_percent": review_percent,
            "match_score_threshold": cv_threshold,
            "review_score_threshold": review_threshold,
        })
        save_config(st.session_state.config)
        st.success("✅ 保存しました。適用するにはターミナルで `python3 run.py --reanalyze` を実行。")

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
                    width="stretch",
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
# Tab 2: Match Analysis
# ═══════════════════════════════════════════════════════════

with tab_analysis:
    st.header("🎯 Match Analysis")
    
    st.subheader("▶️ Run Analysis")

    # Analysis is incremental: run.py --from-saved skips URLs already in
    # _analyzed.json, so the number that matters is NEW, not the queue size.
    # Showing the queue size alone reads as "669 will be processed" when the
    # real answer is often zero.
    @st.cache_data(ttl=30)
    def _staging_status() -> tuple[int, int, list[str]]:
        """(new_count, staged_total, ['reed 623', 'url-list 46', …])."""
        import glob as _glob
        from collections import Counter as _Counter
        known: set[str] = set()
        try:
            for j in json.load(open(ANALYZED_PATH)):
                if j.get("url"):
                    known.add(j["url"])
                known.update(j.get("duplicate_urls") or [])
        except Exception:
            pass
        staged, new_src = 0, _Counter()
        parts = []
        for f in sorted(_glob.glob(str(SCRAPER_DIR / "00_saved" / "*.json"))):
            name = os.path.basename(f)
            if not (name.startswith("_raw_") or name in ("local_html_jobs.json",
                                                         "url_list_jobs.json",
                                                         "_saved_index.json")):
                continue
            try:
                jobs = json.load(open(f))
            except Exception:
                continue
            if name.startswith("_raw_"):
                label = name.replace("_raw_", "").rsplit("_", 2)[0]
            elif name == "url_list_jobs.json":
                label = "url-list (👁 Saved)"
            elif name == "_saved_index.json":
                label = "手動保存"
            else:
                label = "ローカルHTML"
            staged += len(jobs)
            parts.append(f"{label} {len(jobs)}")
            for j in jobs:
                if not j.get("url") or j["url"] not in known:
                    new_src[label] += 1
        return sum(new_src.values()), staged, parts

    _new_n, _staged_n, _staged_parts = _staging_status()

    col_run1, col_run2 = st.columns(2)
    with col_run1:
        _btn = f"📥 新規求人を解析 ({_new_n}件)" if _new_n else "📥 新規求人なし — 解析不要"
        if st.button(_btn, type="primary", disabled=_new_n == 0,
                     help="00_saved/ キューのうち、まだ _analyzed.json に無い求人だけを解析します "
                          "(増分処理)。既に解析済みの求人は再処理されません。新たなスクレイプはしません"):
            with st.spinner(f"Analyzing {_new_n} new jobs…"):
                cmd = [sys.executable, "-u", "run.py", "--from-saved"]
                process = subprocess.Popen(
                    cmd, cwd=str(SCRAPER_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                for line in process.stdout:
                    st.code(line)
                process.wait()
                if process.returncode == 0:
                    st.success("✅ Analysis complete! Refresh to see updated results.")
                else:
                    st.error(f"❌ Analysis failed with exit code {process.returncode}")
                    
    with col_run2:
        if st.button("🔄 Re-score Analyzed DB (_analyzed.json)",
                     help="解析済みの _analyzed.json を、現在の matcher・重み設定で再採点。"
                          "新しい求人は取り込まない (取り込みは左の Staged Jobs)"):
            with st.spinner("Re-scoring _analyzed.json with the current matcher…"):
                cmd = [sys.executable, "-u", "run.py", "--reanalyze"]
                process = subprocess.Popen(
                    cmd, cwd=str(SCRAPER_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                for line in process.stdout:
                    st.code(line)
                process.wait()
                if process.returncode == 0:
                    st.success("✅ Re-score complete! Refresh to see updated results.")
                else:
                    st.error(f"❌ Re-score failed with exit code {process.returncode}")

    @st.cache_data(ttl=30)
    def _db_by_source() -> tuple[int, str]:
        from collections import Counter as _Counter
        try:
            db = json.load(open(ANALYZED_PATH))
        except Exception:
            return 0, ""
        c = _Counter(j.get("source", "?") for j in db)
        return len(db), " / ".join(f"{k} {v}" for k, v in c.most_common())

    _db_n, _db_parts = _db_by_source()
    if _db_n:
        st.caption(f"📊 解析済みDB: **{_db_n}件** — {_db_parts}")
    st.caption(
        f"📥 `00_saved/` キュー: {_staged_n}件 ({' / '.join(_staged_parts) or '空'}) "
        f"→ うち未解析 **{_new_n}件**。"
        "キューは「収集した求人の待ち行列」で、スクレイプ分と 👁 Saved (url-list.md) 分が合流します。"
        "処理済みの生データを片付けるには `00_saved/archive/raw/` へ移動してください"
    )

    st.markdown("---")
    st.subheader("⚖️ Match Weight Adjuster")
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
        width="stretch",
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

# Recipient-facing PDF filenames carry the applicant's name so a hiring
# manager can tell whose document this is before opening it. The internal
# .md files (10_cvs, 10_cover-letters, 00_matches) keep their bare
# make_safe_name(company, title) join key — renaming 5,000+ files there
# would break the report↔CV/CL links. Only the PDF output name is prefixed.
APPLICANT_NAME_PREFIX = "Kazuki-Yunome"
# NOTE: ./static/pdfs/ is no longer written to — downloads go through
# st.download_button (see _pdf_download_button). The copies already there are
# left alone, but they duplicate every name under 10_output/20_pdfs/, so an
# Obsidian `pdf: "[[Name.pdf]]"` wikilink has two candidates to resolve to.
CV_DIR = OUTPUT_DIR / "10_cvs"
CL_DIR = OUTPUT_DIR / "10_cover-letters"


def _letter_date(on: "date | None" = None) -> str:
    """A letter's date, UK style: "2 August 2026", never zero-padded (%-d is
    glibc-only, so the day is built separately)."""
    from datetime import date as _date
    d = on or _date.today()
    return f"{d.day} {d.strftime('%B %Y')}"


_DATE_LINE_RE = re.compile(r"^\s*\d{1,2} [A-Z][a-z]+ \d{4}\s*$", re.MULTILINE)


def _dated_today(text: str) -> str:
    """Put today's date in the letter's sender block.

    The date belongs to the day the letter is SENT, not the day the pipeline
    happened to draft it. Held in the markdown it went stale silently: letters
    drafted three weeks earlier were still dated three weeks earlier, and a
    reader sees that before they read a word of the letter. So the markdown
    carries no date and the renderer stamps one. Existing letters do carry one
    — those are rewritten rather than doubled.
    """
    if _DATE_LINE_RE.search(text):
        return _DATE_LINE_RE.sub(_letter_date(), text, count=1)
    # No date line: add one under the name/contact block, which the sender
    # block ends with, i.e. before the first blank line.
    head, sep, rest = text.partition("\n\n")
    return f"{head.rstrip()}\n{_letter_date()}{sep}{rest}" if sep else text


def _md_to_pdf_bytes(md_path: Path) -> bytes:
    """Render a generated CV/CL markdown file to a clean A4 PDF."""
    # Lazy imports: weasyprint is slow to load and only needed on demand
    import markdown as _markdown
    from weasyprint import HTML

    # Cover letters are short prose, not page-count-constrained like a CV —
    # the tightened paragraph margin below exists to fit a CV in two pages
    # and otherwise just crushes CL paragraph breaks flat.
    is_cl = md_path.stem.endswith("_CL")

    text = md_path.read_text(encoding="utf-8")
    # Strip YAML frontmatter (Obsidian metadata, not for the PDF)
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
    # Strip Obsidian Meta Bind blocks (buttons, inputs — not for the PDF)
    text = re.sub(r"```meta-bind[^\n]*\n.*?```\n?", "", text, flags=re.DOTALL)
    # Obsidian wiki-links → plain text ([[target|label]] → label)
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)
    if is_cl:
        text = _dated_today(text)
        # The LLM habitually bolds or italicises a project name mid-sentence
        # ("I built **TAIFUNOME**", "my work on *Feral Bestiary*") as ad-lib
        # emphasis — cover_letter_generator.py never asks for it, and unlike a
        # CV a letter has no structural use for markdown emphasis at all (the
        # sender block, salutation, and closing are plain text). Measured
        # across the letters on disk: 99/471 carry stray bold, 166/471 stray
        # italic. Stripped here rather than fixed in the prompt, since a
        # rendering rule is certain where an LLM instruction is only ever
        # probable — the CL word-count limit is asked for the same way and is
        # still missed on roughly a fifth of openings.
        text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
        text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)

    # Generated CVs/CLs are near-plain text: ALL-CAPS section lines, "•" bullets,
    # and meaningful single line breaks. Preprocess into real markdown.
    lines = text.strip().split("\n")
    out_lines = []
    # Bold-only lines are entry titles in EXPERIENCE/SELECTED PROJECTS but mere
    # category labels in the toolkit; only the former need breathing room.
    titles_want_space = False
    # A CL recipient block is "Hiring Team\n<Company>\n<City>". Company lines
    # are often ALL-CAPS (VCCP, BBC, IBM, D&AD) and would otherwise trip the
    # ALL-CAPS section-header rule below, inflating the addressee to an h2
    # while "Hiring Team" and the city stay body text — a broken look, and one
    # the sender cannot see from the markdown source. The block is plain
    # address text, so every line in it is emitted verbatim. Only active for
    # cover letters: CVs have no such block and a "Hiring Team" heading in one
    # would not be the addressee.
    in_recipient_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "Hiring Team":
            in_recipient_block = is_cl
        elif stripped.startswith("Dear ") or not in_recipient_block:
            in_recipient_block = False
        if in_recipient_block:
            out_lines.append(line)  # recipient block: never a heading
            continue
        if i == 0 and stripped and not stripped.startswith("#"):
            out_lines.append(f"# {stripped}")  # first line = candidate name
        elif re.fullmatch(r"[A-Z][A-Z &/'’\-]{2,40}", stripped):
            titles_want_space = stripped in ("EXPERIENCE", "SELECTED PROJECTS")
            out_lines.append(f"\n## {stripped}")  # ALL-CAPS section header
        elif re.fullmatch(r"\*\*[^*]+\*\*", stripped):
            # A line that is nothing but bold text is an entry title (job,
            # project) or a toolkit category. Left as a paragraph, nl2br glues
            # it to the text beneath with no space at all; as a heading it gets
            # its own margin — a wider one for entries than for categories.
            level = "###" if titles_want_space else "####"
            out_lines.append(f"\n{level} {stripped.strip('*')}")
        elif re.fullmatch(r"\*\*[^*]+\*\* · .+", stripped):
            # Same entry-title line, plus a trailing " · <link>" (a project's
            # URL). The bare-bold pattern above requires the WHOLE line to be
            # "**...**" — the suffix breaks that fullmatch, so this line fell
            # through to the plain-text branch below. There it was joined to
            # the next line with a single \n, which nl2br glues into one <p>
            # with the following bullets — no heading tag, no page-break-avoid,
            # and "•" bullets rendered as literal dashes instead of a <li>
            # list. The ** and [text](url) markers are kept (not stripped):
            # ATX headings run inline markdown, so ### processes both.
            level = "###" if titles_want_space else "####"
            out_lines.append(f"\n{level} {stripped}")
        elif stripped.startswith(("**Other projects:", "**その他のプロジェクト:")):
            # Trails the last project's bullet list, so without a break of its
            # own markdown reads it as more of that list and it ends up flush
            # against the bullets. Its own paragraph, with room above.
            # Raw HTML, so the bold marker is expanded here — markdown does not
            # reach inside an HTML block without the md_in_html extension.
            inner = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", stripped)
            out_lines.append(f'\n<p class="trailing">{inner}</p>\n')
        elif stripped.startswith("**") and titles_want_space is False and ":" not in stripped[:3]:
            # Bold-led lines that continue in plain text (education entries):
            # give each its own paragraph so they do not run together.
            out_lines.append(f"\n{stripped}")
        elif stripped.startswith("•"):
            out_lines.append("- " + stripped.lstrip("• "))
        else:
            out_lines.append(line)
    text = "\n".join(out_lines)

    body = _markdown.markdown(text, extensions=["tables", "fenced_code", "nl2br"])
    # A CL is a greeting to someone else, not a CV — the candidate's name
    # shouldn't read as the headline. It also runs short of a page; a
    # couple of the natural letter breaks (recipient block, salutation,
    # the gap before the signature) get extra air instead of leaving
    # everything crammed at the top with dead space below.
    cl_spacing_css = (
        """p:nth-of-type(2), p:nth-of-type(3) { margin-top: 10pt; }
        p:last-of-type { margin-top: 20pt; }"""
        if is_cl else ""
    )
    html = f"""<html><head><meta charset="utf-8"><style>
        /* Tightened so a CV lands in as few pages as possible without
           reading as cramped — a third page is rarely reached by a reader.
           The page margin is what buys the second page: at 13mm the longest
           CVs spill onto a third, at 10mm none do. Font size and line height
           were left alone deliberately — shrinking them is what makes a CV
           read as cramped, and edge whitespace is the cheaper thing to give
           up. Heading margins barely move the page count; don't trade the
           space above entry titles for it. */
        @page {{ size: A4; margin: 10mm 11mm; }}
        body {{ font-family: "DejaVu Sans", sans-serif; font-size: 9.5pt; line-height: 1.3; color: #1a1a1a; }}
        h1 {{ font-size: {"12pt" if is_cl else "16pt"}; margin: 0 0 3pt; }}
        h2 {{ font-size: 11.5pt; border-bottom: 1px solid #999; padding-bottom: 2pt; margin: 7pt 0 3pt; page-break-after: avoid; }}
        h3 {{ font-size: 9.8pt; margin: 14pt 0 1pt; page-break-after: avoid; }}
        h4 {{ font-size: 9.5pt; margin: 4pt 0 0; page-break-after: avoid; }}
        p, li {{ margin: {"6pt" if is_cl else "1.5pt"} 0; }}
        {cl_spacing_css}
        /* Without an explicit margin the default 1em lands under every entry
           title, so the title floats between its heading space and its own
           text. Space belongs above a title, not below it. */
        ul {{ margin: 0 0 0; padding-left: 13pt; }}
        p.trailing {{ margin: 10pt 0 0; }}
        /* Short-entry CVs separate projects with "---", which is a readable
           divider in Obsidian but renders as a heavy default <hr> in print.
           The space above each entry title already separates them. */
        hr {{ display: none; }}
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


def _pdf_source_sha(md_path: Path) -> str:
    """The identity of a PDF's source: what would actually reach the page.

    Two things are deliberately outside it and one deliberately inside:

    * The frontmatter is EXCLUDED. _md_to_pdf_bytes strips it, so no property
      there can change the PDF — and hashing it made conversion invalidate
      itself once the converter began writing `pdf:` back into the note: each
      run rewrote the file it had just hashed and minted another identical
      version, forever. Stamping a review did the same.
    * The renderer source is INCLUDED. The CSS and markdown preprocessing live
      in _md_to_pdf_bytes, so a layout change leaves the MD byte-identical and
      the stale PDF would be reused forever.

    Both the converter and the freshness badge must ask the same question, so
    they ask it here. They used to compute it separately and drifted: the badge
    hashed raw file bytes with no renderer, so it never matched what the
    converter stored and every freshly built PDF was labelled "(outdated)".
    """
    import hashlib, inspect
    body = re.sub(r"\A---\n.*?\n---\n", "", md_path.read_text(encoding="utf-8"), flags=re.DOTALL)
    # A letter is dated at render time, so the date is part of what it renders
    # to even though it appears nowhere in the source. Leave it out and the
    # reuse branch hands back yesterday's PDF, dated yesterday — the exact
    # staleness moving the date here was meant to end.
    stamped = _letter_date() if md_path.stem.endswith("_CL") else ""
    return hashlib.sha1(
        body.encode("utf-8")
        + stamped.encode("utf-8")
        + inspect.getsource(_md_to_pdf_bytes).encode("utf-8")
    ).hexdigest()


def _convert_pdf_versioned(md_path: Path) -> tuple[Path, int, bool]:
    """Render md_path to a PDF, versioning by source-MD content, and link it.

    If the current markdown is identical to the newest existing version's
    source, reuse that PDF (no pointless duplicate). Otherwise mint the
    next sequential version (highest existing number + 1). Returns
    (pdf_path, version_number, is_new).

    Stamping the `pdf:` property is done HERE rather than left to the caller.
    It used to be a separate follow-up call, and the Gmail-draft path simply
    never made it — minting versions no note ever linked to. A PDF that
    nothing points at is not a finished conversion, so the two steps are one
    function with no seam for a caller to miss.
    """
    # PDF output names carry the applicant's name; the internal .md stem
    # (company_title) stays as the join key used to stamp pdf:/cv_pdf:/cl_pdf:
    # frontmatter back onto the report. Versioning is by prefixed stem so new
    # outputs mint their own sequence instead of colliding with legacy PDFs.
    stem = f"{APPLICANT_NAME_PREFIX}_{md_path.stem}"
    md_sha = _pdf_source_sha(md_path)
    versions = _pdf_versions(stem)
    meta = _load_pdf_meta()

    PDF_DIR.mkdir(exist_ok=True)

    if versions:
        latest_n, latest_path = versions[-1]
        if meta.get(latest_path.name) == md_sha and latest_path.exists():
            _set_report_pdf_property(md_path, latest_path.name)
            return latest_path, latest_n, False  # unchanged — reuse
        n = latest_n + 1
    else:
        n = 1

    target = PDF_DIR / _version_filename(stem, n)
    pdf_bytes = _md_to_pdf_bytes(md_path)
    target.write_bytes(pdf_bytes)
    meta[target.name] = md_sha
    _save_pdf_meta(meta)
    _set_report_pdf_property(md_path, target.name)
    return target, n, True


def _pdf_download_button(pdf_path: Path, label: str, key: str):
    """Download one PDF via Streamlit's own button, not a hand-written <a>.

    This used to be an `<a href="/app/static/…" download>` tag rendered through
    st.markdown, and it handed back a corrupt "Unconfirmed NNNNNN.crdownload"
    instead of a PDF. Two things combine:

    * st.markdown FORCES target="_blank" rel="noopener noreferrer" onto every
      anchor it renders — re-adding them even when the tag is written without
      them, so the popup cannot be avoided from the HTML side.
    * With both `download` and target="_blank", Chrome opens a throwaway tab,
      starts the transfer inside it, then tears the tab down, racing the
      response. When teardown wins, the transfer is interrupted and Chrome
      leaves the unrenamed temp file behind.

    Streamlit's /app/static route also sends no Content-Disposition, so that
    `download` attribute was the only thing naming the file — lose the tab and
    the filename goes with it, hence "Unconfirmed" rather than the CV's name.
    st.download_button serves the bytes from /media/<hash> WITH a
    Content-Disposition filename and no second browsing context, so neither
    failure is reachable.
    """
    st.download_button(
        label,
        data=pdf_path.read_bytes(),
        file_name=pdf_path.name,
        mime="application/pdf",
        key=key,
    )


def _set_frontmatter_property(path: Path, key: str, value: str):
    """Set/replace a single frontmatter property in an existing markdown file."""
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    m = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not m:
        return
    line = f'{key}: "{value}"'
    fm = m.group(1)
    if re.search(rf"^{key}:.*$", fm, flags=re.MULTILINE):
        fm = re.sub(rf"^{key}:.*$", line, fm, flags=re.MULTILINE)
    else:
        fm = fm + "\n" + line
    path.write_text(f"---\n{fm}\n---\n" + text[m.end():], encoding="utf-8")


def _set_report_doc_property(md_path: Path, key_suffix: str, target_name: str):
    """Set a cv_*/cl_* wikilink property on the match report's frontmatter.

    md_path is the CV/CL markdown (…_CV.md / …_CL.md); the report shares its
    base name. key_suffix "pdf" → cv_pdf/cl_pdf, "review" → cv_review/cl_review.
    Frontmatter properties keep these Dataview-queryable from the report.
    """
    stem = md_path.stem
    if stem.endswith("_CV"):
        key, base = f"cv_{key_suffix}", stem[:-3]
    elif stem.endswith("_CL"):
        key, base = f"cl_{key_suffix}", stem[:-3]
    else:
        return
    report = MATCH_DIR / f"{base}.md"
    _set_frontmatter_property(report, key, f"[[{target_name}]]")


def _set_report_pdf_property(md_path: Path, pdf_name: str):
    _set_report_doc_property(md_path, "pdf", pdf_name)
    # Same property on the CV/CL's own frontmatter, not just the report's —
    # the PDF should be reachable from either direction.
    _set_frontmatter_property(md_path, "pdf", f"[[{pdf_name}]]")


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


def _score_badge(review_path: Path) -> str:
    """Submission badge from a review's frontmatter. Threshold is read live
    from config (review_score_threshold, default 85) so tuning it re-labels
    every stored review without re-reviewing. fact_block overrides the score;
    a missing/null score is shown as unknown, never as a pass."""
    import re
    text = review_path.read_text(encoding="utf-8")[:600]
    m = re.search(r"^submission_score:\s*(\d+)", text, flags=re.MULTILINE)
    fb = re.search(r"^fact_block:\s*true", text, flags=re.MULTILINE)
    if fb:
        score_txt = f" {m.group(1)}%" if m else ""
        return f"⛔{score_txt} 事実要修正"
    if not m:
        return "⚪ スコア未算出 (再レビューで算出)"
    score = int(m.group(1))
    threshold = int(st.session_state.get("config", {}).get("review_score_threshold", 85))
    return f"🟢 {score}% 提出可" if score >= threshold else f"🔴 {score}% (基準 {threshold}%)"


def show_review(label: str, md_path: Path, job: dict | None = None):
    """Display the stored review with freshness status, plus the annotation
    dialogue: user comments added in Obsidian block one-click apply until the
    LLM has replied and the user has settled them. Reviews are produced by the
    batch runner (skips unchanged docs), not by per-row buttons."""
    import re
    import hashlib
    from reviewer import review_is_current, detect_annotations
    display = "CV" if label == "CV" else "Cover Letter"
    if not md_path.exists():
        st.caption(f"{display}: —")
        return
    # md_path.stem collides when two different jobs (distinct urls) resolve to
    # the same filename base (see resolve_doc_base) — widget keys need a
    # per-job suffix on top of the stem to stay unique.
    key_suffix = hashlib.md5((job or {}).get("url", "").encode()).hexdigest()[:8] if job else ""
    is_cur, rpath = review_is_current(md_path)
    if not rpath or not rpath.exists():
        st.caption(f"{display}: レビュー未実施")
        return
    status = "✅ current" if is_cur else "⚠️ 編集済み — 次回バッチで再レビュー"
    notes = detect_annotations(rpath)
    if notes:
        status += f" / 💬 追記{len(notes)}件"

    score_badge = f" | {_score_badge(rpath)}" if rpath and rpath.exists() else ""

    with st.expander(f"{'📄' if label == 'CV' else '✉️'} {display} review ({status}){score_badge}"):
        text = rpath.read_text(encoding="utf-8")
        m = re.match(r"\A---\n.*?\n---\n", text, flags=re.DOTALL)
        st.markdown(text[m.end():] if m else text)

        from reviewer import parse_review_fixes, apply_review_fixes, respond_to_annotations, trace_finding_sources
        fixes = parse_review_fixes(rpath)

        # Source tracing: findings quoting a reusable block should be fixed at
        # the SOURCE (once, for every CV) — not argued per-review.
        traced = [(q, src) for q, src in trace_finding_sources(rpath) if src]
        if traced:
            uniq = sorted({src for _q, src in traced})
            st.info(
                f"📌 **ソース由来の指摘 {len(traced)}件** — 対応するならレビューではなく元ファイルを直すこと"
                f"(1回直せば全CV/CLに効く):\n" + "\n".join(f"- `{s}`" for s in uniq)
            )

        # ── Annotation gate ──────────────────────────────────────────────
        # notes == None: pre-feature review, no pristine baseline → can't tell
        # whether the user annotated it; offer the dialogue button but don't
        # block. notes == [...]: user annotations pending → block apply.
        if notes:
            st.warning(
                f"⏸ **あなたの追記 {len(notes)}件が保留中** — 回答が済むまで一括適用はブロックされます:\n"
                + "\n".join(f"- {n[:90]}…" if len(n) > 90 else f"- {n}" for n in notes[:8])
            )
        # The dialogue must survive document edits: 一括適用 itself edits the
        # doc and flips is_cur to False — gating on is_cur here deadlocked
        # pending annotations until the next batch re-review.
        if (notes or notes is None) and job is not None:
            btn_label = "💬 追記に回答して修正案を更新" if notes else "💬 追記があれば回答させる (原本未登録の旧レビュー)"
            if st.button(btn_label, key=f"respond_{md_path.stem}_{key_suffix}",
                         help="LLMがあなたの追記(質問・反論・賛成)に回答し、正当な指摘は修正案に反映した改訂版レビューを書きます。旧版は 15_reviews/archive/ に保存"):
                with st.spinner("LLMが追記を読んで回答中…"):
                    try:
                        respond_to_annotations(label, md_path, job)
                        st.rerun()
                    except Exception as e:
                        st.error(f"回答生成に失敗: {e}")

        # ── Per-fix apply with destination choice (deterministic, no LLM) ─
        # Blocked while annotations are pending: un-annotated 修正案 count as
        # agreed, but the user's open questions must be settled first.
        # Apply is exact-match-only (unmatched quotes are just reported), so a
        # stale review is safe to apply — no is_cur gate for the same reason.
        # Destination defaults to この文書のみ: masters must NOT drift with every
        # job posting — a source edit is an explicit, per-fix opt-in for
        # durable improvements only.
        if fixes and not notes:
            from reviewer import fix_targets, apply_fixes_to_sources
            targets = fix_targets(rpath)
            st.caption(
                f"抽出された修正案: {len(targets)}件 — 各修正の適用先を選んで実行 "
                f"(元ファイル適用は今後生成される全CV/CLに影響。求人特化の調整は「この{display}のみ」を推奨)"
            )
            DOC_ONLY, TO_SOURCE, SKIP = f"この{display}のみ", "元ファイル+この文書", "適用しない"
            choice_by_orig: dict[str, str] = {}
            for i, (orig, repl, src, why) in enumerate(targets):
                short_o = orig[:80] + "…" if len(orig) > 80 else orig
                short_r = repl[:80] + "…" if len(repl) > 80 else repl
                st.markdown(f"**{i+1}.** ~~{short_o}~~\n   → {short_r}")
                opts = [DOC_ONLY, f"{TO_SOURCE} (`{src}`)", SKIP] if src else [DOC_ONLY, SKIP]
                choice_by_orig[orig] = st.radio(
                    "適用先", opts, horizontal=True, index=0,
                    key=f"dest_{md_path.stem}_{key_suffix}_{i}", label_visibility="collapsed",
                )
                # Never omit the source option silently — say why it is absent.
                if why:
                    kind, _, where = why.partition(":")
                    st.caption({
                        "applied": f"↳ 元ファイル適用は不要 — `{where}` には適用済み "
                                   f"(この{display}は生成が古いだけ。再生成でも解消します)",
                        "frontmatter": f"↳ 元ファイル適用は不可 — 引用は `{where}` の frontmatter "
                                       f"(role_tagline 等の設定値)。変更するならファイルを直接編集",
                        "doc-only": "↳ 元ファイル適用は不可 — この文言はマスターに無い "
                                    "(求人ごとにLLM生成された箇所)",
                    }[kind])
            if st.button(
                f"✅ 選択した修正を適用",
                key=f"apply_{md_path.stem}_{key_suffix}",
                help="この文書: レビュー引用と完全一致する箇所のみ置換 (バックアップ: 15_reviews/.backups/)。"
                     "元ファイル: profile/projects 等のマスター側も置換 (バックアップ: 15_reviews/.source_backups/)",
            ):
                doc_set = {o for o, c in choice_by_orig.items() if c != SKIP}
                src_set = {o for o, c in choice_by_orig.items() if c.startswith(TO_SOURCE)}
                applied, unmatched = 0, []
                if doc_set:
                    applied, unmatched = apply_review_fixes(md_path, rpath, only=doc_set)
                    if applied:
                        st.success(f"{applied}件を{display}に適用 (バックアップ: 15_reviews/.backups/)")
                    if unmatched:
                        st.warning(
                            f"{len(unmatched)}件は{display}の原文と一致せず未適用 — 手動で対応してください:\n"
                            + "\n".join(f"- {u[:80]}…" if len(u) > 80 else f"- {u}" for u in unmatched[:5])
                        )
                if src_set:
                    s_applied, s_unmatched = apply_fixes_to_sources(rpath, only=src_set)
                    if s_applied:
                        files = sorted({lbl for lbl, _o in s_applied})
                        st.success(
                            f"{len(s_applied)}件を元ファイルに適用: " + ", ".join(f"`{f}`" for f in files)
                            + " — 次回生成される全CV/CLに反映されます"
                        )
                    if s_unmatched:
                        st.warning(
                            f"{len(s_unmatched)}件はソース由来だが原文と完全一致せず未適用 — 手動で対応:\n"
                            + "\n".join(f"- {u[:80]}…" if len(u) > 80 else f"- {u}" for u in s_unmatched[:5])
                        )
                if not doc_set and not src_set:
                    st.info(
                        "適用対象が選択されていません (全て「適用しない」)。"
                        f"この{display}を今のマスターから作り直すなら下の「🔄 再生成」を使ってください"
                    )
                elif applied:
                    st.rerun()

        # ── Regenerate from current masters ──────────────────────────────
        # The way out when the fixes are already applied at the source (or all
        # skipped): the stale document is rebuilt from the masters as they are
        # now, which also picks up header/role_tagline changes.
        if job is not None:
            st.caption(
                f"修正案が全て元ファイル側で解決済みの場合は、{display}を作り直すのが早い "
                "(現在のマスター・ヘッダー設定で再生成 → 次回バッチで再レビュー)"
            )
            if st.button(
                f"🔄 {display}を今のマスターから再生成",
                key=f"regen_{md_path.stem}_{key_suffix}",
                help="career/cv/ の profile/projects/toolkit と role_title/role_tagline から作り直します。"
                     "現在のファイルは 15_reviews/.backups/ にバックアップされます。手動編集は失われます",
            ):
                try:
                    with st.spinner(f"{display}を再生成中…"):
                        from reviewer import REVIEWS_DIR
                        REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
                        (_regen_bk_dir := REVIEWS_DIR / ".backups").mkdir(parents=True, exist_ok=True) or (_regen_bk_dir / f"{md_path.stem}.pre_regen.md").write_text(
                            md_path.read_text(encoding="utf-8"), encoding="utf-8")
                        base = md_path.stem[:-3]  # strip _CV / _CL
                        title = job.get("title", "")
                        company = job.get("company", "")
                        desc = job.get("description") or job.get("snippet") or ""
                        if label == "CV":
                            from cv_generator import detect_role_type, generate_cv
                            md_path.write_text(
                                generate_cv(
                                    role_type=detect_role_type(title, desc),
                                    job_title=title, company=company, job_description=desc,
                                    match_filename=base, cl_filename=f"{base}_CL",
                                ), encoding="utf-8")
                        else:
                            from cover_letter_generator import save_cover_letter
                            save_cover_letter(
                                title, company, job.get("location", "Edinburgh"), desc,
                                str(md_path.parent), match_filename=base,
                                cv_filename=f"{base}_CV",
                            )
                    st.success(
                        f"{display}を再生成しました (バックアップ: 15_reviews/.backups/)。"
                        "レビューは古くなったので、次回バッチで再レビューされます"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"再生成に失敗: {e}")


def pdf_doc_controls(label: str, md_path: Path, key_prefix: str):
    """Inline convert-button + versioned download links for ONE document
    (a CV or a CL). PDFs are saved to 10_output/20_pdfs/ with sequential
    versioning — editing the source .md and re-converting mints v2, v3, …
    while identical re-conversions reuse the latest version."""
    import hashlib
    if not md_path.exists():
        st.caption(f"{label}: —")
        return

    # Submission badge next to the PDF button (badge only — never blocks)
    from reviewer import REVIEWS_DIR
    review_path = REVIEWS_DIR / f"{md_path.stem}_review.md"
    if review_path.exists():
        st.markdown(f"**Review:** {_score_badge(review_path)}")

    if st.button(f"{label} → PDF", key=f"conv_{key_prefix}_{label}"):
        try:
            _pdf_path, ver, is_new = _convert_pdf_versioned(md_path)
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
        current_sha = _pdf_source_sha(md_path)
        meta = _load_pdf_meta()
        is_current = meta.get(latest_path.name) == current_sha
        if not is_current:
            st.caption(f"⚠️ edited since v{latest_n} — reconvert")
        for n, pdf_path in reversed(versions):
            if n == latest_n:
                suffix = " (latest)" if is_current else " (outdated)"
            else:
                suffix = ""
            _pdf_download_button(
                pdf_path,
                f"⬇ {label} v{n}{suffix}",
                key=f"dl_{key_prefix}_{label}_{n}",
            )


with tab_review:
    st.header("🧐 Document Review")
    st.markdown(
        "LLM proofreading BEFORE PDF export: checks your (hand-edited) CV/CL "
        "against the job posting and your verified profile — factual claims, "
        "job-fit gaps, style. Findings only; it never rewrites your text. "
        "Reviews are saved to `15_reviews/` and linked from the match report. "
        "**Batch mode**: reviews the top X% in one go; documents unchanged "
        "since their last review are skipped (no wasted LLM calls)."
    )

    try:
        all_jobs = load_jobs(st.session_state.config)
    except FileNotFoundError:
        st.error("No job data found. Run the scraper first (🔍 Scraper tab).")
        st.stop()

    rows = ranked_job_rows(all_jobs)
    scored_rows = [r for r in rows if r["score"] > 0]

    from reviewer import review_is_current, REVIEW_MODEL

    import math
    c_pct, c_docs, c_pending = st.columns(3)
    with c_pct:
        top_pct = st.number_input("Top %", 1, 100, 5, key="review_top_pct")
    targets = [r for r in scored_rows[:math.ceil(len(scored_rows) * top_pct / 100)] if r["has_docs"]]

    # Collect (label, md_path, job) for every existing doc in scope, and
    # which of them actually need a (re-)review. Locked documents (hand-edited /
    # applied / expired — see gen_version) are held out entirely: run_review
    # writes a backlink into the document, and a fresh verdict on a submitted or
    # closed application is advice that can no longer be taken.
    import gen_version
    doc_jobs, locked_docs = [], 0
    for r in targets:
        for label, path in (("CV", CV_DIR / f"{r['base']}_CV.md"), ("CL", CL_DIR / f"{r['base']}_CL.md")):
            if not path.exists():
                continue
            if gen_version.is_locked(r["base"], path.read_text(encoding="utf-8"), MATCH_DIR):
                locked_docs += 1
                continue
            doc_jobs.append((label, path, r["job"]))
    pending = [(l, p, j) for l, p, j in doc_jobs if not review_is_current(p)[0]]

    with c_docs:
        st.metric("対象ドキュメント", f"{len(doc_jobs)} ({len(targets)} jobs)",
                  help=f"ロック済み {locked_docs} 件を除外" if locked_docs else None)
    with c_pending:
        st.metric("要レビュー (未変更はスキップ)", f"{len(pending)}")

    if pending and st.button(f"🧐 Review {len(pending)} documents", type="primary", key="review_batch"):
        from reviewer import run_review
        import time as _time
        prog = st.progress(0.0)
        status = st.empty()
        ok, failed = 0, []
        for i, (label, path, job) in enumerate(pending):
            status.text(f"[{i+1}/{len(pending)}] {job.get('company','?')} — {label} … ({REVIEW_MODEL})")
            try:
                rpath = run_review(label, path, job)
                _set_report_doc_property(path, "review", rpath.stem)
                ok += 1
            except Exception as e:
                failed.append(f"{path.stem}: {e}")
            prog.progress((i + 1) / len(pending))
            _time.sleep(1)  # be polite to the API
        status.empty()
        if failed:
            st.error(f"{ok} done, {len(failed)} failed:\n" + "\n".join(failed[:5]))
        else:
            st.success(f"✅ {ok} reviews completed → 15_reviews/")
        st.rerun()
    elif not pending and doc_jobs:
        st.success("✅ 全ドキュメントのレビューが最新です (編集すると自動で再レビュー対象になります)")

    st.divider()
    search_query = st.text_input("🔍 Search company/title", key="review_search")
    shown = [
        r for r in targets
        if not search_query
        or search_query.lower() in r["company"].lower()
        or search_query.lower() in r["title"].lower()
    ]
    for r in shown[:50]:
        c_score, c_job = st.columns([1, 7])
        with c_score:
            st.markdown(f"{_tier_icon(r['tier'])} `{r['score']*100:.0f}%`")
        with c_job:
            st.markdown(f"**{r['company']}** — {r['title'][:70]}")
        c_cv, c_cl = st.columns(2)
        with c_cv:
            show_review("CV", CV_DIR / f"{r['base']}_CV.md", r["job"])
        with c_cl:
            show_review("CL", CL_DIR / f"{r['base']}_CL.md", r["job"])
        st.divider()


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
    # Every row mounts four PDF widgets, so the whole filtered list cannot be
    # rendered at once — 300+ jobs means thousands of widgets. Paginate instead
    # of truncating: a hard [:100] slice hid every job below rank 100 while the
    # metric still counted them, so a CV that existed on disk looked missing.
    PAGE_SIZE = 100
    total = len(filtered)
    pages = max(1, -(-total // PAGE_SIZE))

    st.session_state.setdefault("pdf_page", 1)
    # Tightening a filter can strand the selected page past the end of the new
    # list — clamp before the widget reads it, or the page renders empty.
    if st.session_state["pdf_page"] > pages:
        st.session_state["pdf_page"] = pages

    col_m, col_p = st.columns([1, 2])
    with col_m:
        st.metric("Matching", f"{total} jobs")
    with col_p:
        if pages > 1:
            st.selectbox(
                "Page",
                list(range(1, pages + 1)),
                key="pdf_page",
                format_func=lambda p: (
                    f"{(p - 1) * PAGE_SIZE + 1}–{min(p * PAGE_SIZE, total)} of {total}"
                ),
            )

    start = (st.session_state["pdf_page"] - 1) * PAGE_SIZE
    page_rows = filtered[start:start + PAGE_SIZE]

    for r in page_rows:
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

    if pages > 1:
        st.caption(
            f"Showing {start + 1}–{start + len(page_rows)} of {total}. "
            "Use the Page selector, or search to narrow down."
        )


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
    for _key in ["saved_proc", "watched_proc"]:
        if _key not in st.session_state:
            st.session_state[_key] = None
        if f"{_key}_running" not in st.session_state:
            st.session_state[f"{_key}_running"] = False
        if f"{_key}_output" not in st.session_state:
            st.session_state[f"{_key}_output"] = []

    # Two-stage pipeline state for the URL-list flow:
    #   saved_stage    — which step saved_proc is currently running ("scrape"/"analyze")
    #   saved_chain    — True when the scrape should auto-continue into --from-saved analysis
    #   saved_log_path — file the subprocess writes to (PIPE would block on drain pause)
    st.session_state.setdefault("saved_stage", None)
    st.session_state.setdefault("saved_chain", False)
    st.session_state.setdefault("saved_log_path", None)
    st.session_state.setdefault("saved_log_fh", None)

    def _new_chain_log(stage: str):
        """Open a fresh log file for this stage and return (fh, path)."""
        OUTPUT_DIR.mkdir(exist_ok=True)
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _path = OUTPUT_DIR / f"_saved_chain_{stage}_{_ts}.log"
        _fh = open(_path, "w", encoding="utf-8")
        return _fh, _path

    def _saved_tail(n=200):
        """Read up to n lines from the tail of the current log file."""
        _p = st.session_state.get("saved_log_path")
        if not _p or not Path(_p).exists():
            return []
        try:
            with open(_p, "r", encoding="utf-8") as _f:
                return _f.read().splitlines()[-n:]
        except OSError:
            return []

    def _close_saved_log():
        _fh = st.session_state.pop("saved_log_fh", None)
        if _fh:
            try: _fh.close()
            except Exception: pass

    # Where a running chain records itself. session_state does not survive a
    # Streamlit auto-reload, so without this a reload mid-run shows an idle
    # button while the work is still going — and a second press would start a
    # rival scrape that only finds the lock.
    _CHAIN_STATE = OUTPUT_DIR / ".saved_chain_state.json"

    def _write_chain_state(pid: int, log_path, stage: str):
        try:
            OUTPUT_DIR.mkdir(exist_ok=True)
            _CHAIN_STATE.write_text(json.dumps(
                {"pid": pid, "log": str(log_path), "stage": stage}), encoding="utf-8")
        except OSError:
            pass

    def _clear_chain_state():
        try:
            _CHAIN_STATE.unlink()
        except OSError:
            pass

    def _adopt_running_chain():
        """Re-attach to a chain this session did not launch, if one is alive."""
        if st.session_state.get("saved_proc") is not None:
            return
        try:
            state = json.loads(_CHAIN_STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        pid = state.get("pid")
        try:
            os.kill(int(pid), 0)  # signal 0 asks "does this exist", kills nothing
        except (OSError, TypeError, ValueError):
            _clear_chain_state()
            return
        st.session_state.saved_proc = _AdoptedProcess(int(pid))
        st.session_state.saved_stage = state.get("stage") or "chain"
        st.session_state.saved_log_path = state.get("log")
        st.session_state.saved_chain = False

    _adopt_running_chain()

    # ════════════════════════════════════════
    # Section B: URL List Scraper
    # ════════════════════════════════════════
    st.subheader("🔗 B: URL List Scraper & Matcher")
    st.caption("""
        Add job detail page URLs to `00_saved/url-list.md` (one per line).
        - **⚡ Scrape → 解析まで一気通貫** — スクレイプから解析・表反映まで自動実行(通常はこれ)。
        - **▶ Scrape のみ** — 00_saved/ に貯めるだけ。解析は 🎯 Match Analysis タブで別途。
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

    col_b1, col_b3 = st.columns([1, 2])

    scrape_running = st.session_state.saved_proc is not None and st.session_state.saved_proc.poll() is None

    def _start_scrape(chain: bool):
        """Launch the whole chain as ONE detached process.

        stdout goes to a log file, not a PIPE — a PIPE blocks the subprocess
        the moment the browser leaves the page and the Streamlit drain loop
        stops reading (observed 2026-08-06: anon_pipe_write wchan for 37 min).

        Two further reasons this is one process in its own session:

        Both stages live in run_saved_chain.py, so the analysis no longer waits
        on Streamlit to notice the scrape exited and start it. That handoff ran
        inside the rerun loop, which does not survive an auto-reload — editing
        any watched module restarts the script and the pending chain is
        forgotten. On 2026-08-12 that lost the enrichment of 1,004 postings at
        item 100, silently, with the scrape already banked.

        start_new_session detaches it from Streamlit's process group, so a
        SIGHUP or SIGTERM aimed at the server — a reload, a closed terminal —
        does not travel to the work.
        """
        _close_saved_log()
        _fh, _path = _new_chain_log("chain")
        cmd = [sys.executable, "-u", "run_saved_chain.py"]
        if not chain:
            cmd.append("--scrape-only")
        st.session_state.saved_proc = subprocess.Popen(
            cmd, cwd=str(SCRAPER_DIR),
            stdout=_fh, stderr=subprocess.STDOUT, text=True,
            start_new_session=True,
        )
        st.session_state.saved_stage = "chain" if chain else "scrape"
        st.session_state.saved_chain = False  # the child owns the sequencing now
        st.session_state.saved_running = True
        st.session_state.saved_log_fh = _fh
        st.session_state.saved_log_path = str(_path)
        # So a reload can find a run it did not start. session_state is gone by
        # then; this file is not.
        _write_chain_state(st.session_state.saved_proc.pid, _path,
                           "chain" if chain else "scrape")
        st.rerun()

    with col_b1:
        if not scrape_running:
            if st.button("▶ Scrape のみ", key="start_saved",
                         help="URL をスクレイプして 00_saved/ に貯めるだけ。表は更新されません "
                              "(解析は 🎯 Match Analysis タブで別途)。"):
                _start_scrape(chain=False)
            if st.button("⚡ Scrape → 解析まで一気通貫", type="primary", key="start_saved_chain",
                         help="スクレイプ完了後、そのまま run.py --from-saved を自動実行し "
                              "`URL List Match Table` まで反映します。"):
                _start_scrape(chain=True)
        else:
            _label = ("⏹ Stop 一気通貫" if st.session_state.saved_stage == "chain"
                      else "⏹ Stop Scrape")
            if st.button(_label, type="secondary", key="stop_saved", disabled=not scrape_running):
                st.session_state.saved_chain = False
                _kill_process("saved_proc")
                _close_saved_log()
                _clear_chain_state()
                st.rerun()

    with col_b3:
        # Show status/output for the current pipeline step (scrape or analyze)
        if st.session_state.saved_proc is not None:
            proc = st.session_state.saved_proc
            _stage = st.session_state.saved_stage or "scrape"
            _step_name = ("Scrape → 解析 一気通貫" if _stage == "chain"
                          else "解析 (run.py --from-saved)" if _stage == "analyze"
                          else "Scrape")
            # Tail the log file — PIPE would block the subprocess if the
            # browser drain paused, but the file keeps growing regardless.
            _tail = _saved_tail(200)

            st.info(f"{_step_name} running (PID {proc.pid})" if proc.poll() is None
                    else f"{_step_name} finished (exit code {proc.returncode})")

            if _tail:
                with st.expander(f"{_step_name} Output", expanded=True):
                    st.code("\n".join(_tail[-100:]))

            if proc.poll() is None:
                import time
                time.sleep(2)
                st.rerun()
            else:
                # One process now owns both stages (run_saved_chain.py), so
                # there is no handoff to perform here — only a verdict to show.
                # An adopted run always reports 0, since an exit code cannot be
                # read from outside the process that waited on it; the log
                # above carries what actually happened.
                if proc.returncode == 0:
                    if _stage == "scrape":
                        st.success("✅ Scrape 完了")
                        st.info("次: 🎯 **Match Analysis** タブで解析すると "
                                "`URL List Match Table` に反映されます。")
                    else:
                        st.success("✅ 一気通貫 完了 — `URL List Match Table` に反映されました。"
                                   "（Obsidian でテーブルを開き直すと最新化されます）")
                elif proc.returncode == 2:
                    st.error("⚠ skipped: another process holds the url_list_jobs lock. "
                             "Wait for it to finish, then retry.")
                else:
                    st.error(f"❌ failed (exit code {proc.returncode}). See output above.")
                _close_saved_log()
                _clear_chain_state()
                st.session_state.saved_proc = None
                st.session_state.saved_stage = None
        else:
            st.caption("待機中。「Scrape のみ」または「Scrape → 解析まで一気通貫」を押してください。")


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

    # ════════════════════════════════════════
    # Section D: Email Outreach (cold email drafts)
    # ════════════════════════════════════════
    st.divider()
    st.subheader("✉️ D: Email Outreach (メール下書き)")
    st.caption(
        "`00_saved/email-targets/` に1社1ノート (`00_saved/Email Targets.base` から編集) → 下のボタンで "
        "`10_output/30_emails_draft/` にテンプレートから下書きを生成。会社名が空欄のノートは企業ドメインから推定 "
        "(gmail 等は推定不可)。メールアドレスが未記入のターゲット (フォーム応募など) は一覧には出ますが "
        "下書きは作られません。既存の下書きは上書きしません — 作り直すにはファイルを削除。"
    )

    from email_outreach import (
        parse_email_list, generate_all, draft_path, link_outputs_into_list,
        generate_outreach_cv, outreach_cv_path, resolved_profile,
        OUT_DIR as EMAIL_OUT_DIR,
    )
    _email_rows = parse_email_list()
    if _email_rows:
        import pandas as _pd
        st.dataframe(_pd.DataFrame([{
            "メール": r["email"],
            "会社名": r["company"] + (" (推定)" if r["company_guessed"] else "") if r["company"] else "❌ 要記入",
            "ロール": r["role"],
            "プロファイル": resolved_profile(r["role"]) + (
                "" if resolved_profile(r["role"]) == r["role"] else " (フォールバック)"),
            "CV": (outreach_cv_path(r).name if outreach_cv_path(r) and outreach_cv_path(r).exists() else "—"),
            "下書き": (draft_path(r).name if draft_path(r) and draft_path(r).exists() else "—"),
            "送信": "✅" if r["sent"] else "—",
            "メモ": r["notes"],
        } for r in _email_rows]), hide_index=True, width="stretch")

        st.caption(
            "求人票が無いため、CVはロール別マスターからそのまま生成する汎用版 (求人特化のマッチ度調整・レビューは行いません)。"
            "CLはこの用途では作成しません — 冒頭文を書く根拠となる求人内容が無いため。"
        )
        col_cv, col_mail, col_regen, col_imap = st.columns(4)
        with col_cv:
            if st.button("📄 CVを生成", key="gen_outreach_cvs"):
                results = [(r, *generate_outreach_cv(r)) for r in _email_rows]
                created = [(r, p) for r, p, s in results if s == "created"]
                skipped = [r for r, p, s in results if s == "exists"]
                failed = [(r, s) for r, p, s in results if s not in ("created", "exists")]
                if created:
                    st.success("生成: " + ", ".join(f"`{p.name}`" for _r, p in created)
                               + " → `10_output/31_emails_cvs/`")
                if skipped:
                    st.info(f"{len(skipped)}件は最新版のためスキップ "
                            "(CV生成の仕様やデータが変わると次回自動で作り直します)")
                for r, s in failed:
                    st.warning(f"{r['email']}: {s}")
                # Write [[wikilinks]] back into each target note's cv: frontmatter
                # so Obsidian readers can jump straight from the Base to the CV.
                if created or skipped:
                    if link_outputs_into_list():
                        st.caption("📎 ターゲットノートの `cv:` にリンクを記入しました")
                if created:
                    st.rerun()
        with col_mail:
            if st.button("✉️ メール下書きを生成", type="primary", key="gen_emails"):
                results = generate_all()
                created = [(r, p) for r, p, s in results if s == "created"]
                skipped = [r for r, p, s in results if s == "exists"]
                failed = [(r, s) for r, p, s in results if s not in ("created", "exists")]
                if created:
                    st.success("生成: " + ", ".join(f"`{p.name}`" for _r, p in created)
                               + " → `10_output/30_emails_draft/` (Obsidianで編集して送信)")
                if skipped:
                    st.info(f"{len(skipped)}件は既存の下書きあり — 変更する場合はファイル側を直接編集、"
                            "またはテンプレート変更後は「🔄 作り直す」で上書き")
                for r, s in failed:
                    st.warning(f"{r['email']}: {s}")
                # Write [[wikilinks]] back into each target note's draft: frontmatter
                # so Obsidian readers can jump straight from the Base to the draft.
                if created or skipped:
                    if link_outputs_into_list():
                        st.caption("📎 ターゲットノートの `draft:` にリンクを記入しました")
                    st.rerun()
        with col_regen:
            if st.button("🔄 作り直す (上書き)", key="regen_emails",
                         help="既存の下書きファイルを削除して、現在のテンプレートから作り直します。"
                              "手動で編集した内容があれば失われます。"):
                results = generate_all(force=True)
                created = [(r, p) for r, p, s in results if s == "created"]
                failed = [(r, s) for r, p, s in results if s not in ("created", "exists")]
                if created:
                    st.success(f"{len(created)}件を最新テンプレートで作り直しました → `10_output/30_emails_draft/`")
                for r, s in failed:
                    st.warning(f"{r['email']}: {s}")
                if created:
                    st.rerun()
        with col_imap:
            if st.button("💾 Gmail下書きに保存", key="imap_save_all"):
                from email_outreach import save_imap_draft
                ok_count, fail_count = 0, 0
                for r in _email_rows:
                    cv_md = outreach_cv_path(r)
                    cv_pdf = None
                    if cv_md and cv_md.exists():
                        try:
                            cv_pdf, _v, _new = _convert_pdf_versioned(cv_md)
                        except Exception as _pdf_err:
                            st.warning(f"{r['company']}: PDF変換失敗 — {_pdf_err} (本文のみで保存)")
                    ok, msg = save_imap_draft(r, cv_pdf)
                    if ok:
                        ok_count += 1
                        st.success(f"✓ {msg}")
                    else:
                        fail_count += 1
                        st.error(f"✗ {r.get('company','?')}: {msg}")
                if ok_count:
                    st.caption(f"Gmail の「下書き」フォルダを開いて内容を確認してから送信してください。")
    else:
        st.info("`00_saved/email-targets/` にまだノートがありません。`Email Targets.base` から追加してください。")

    _drafts = sorted(EMAIL_OUT_DIR.glob("*.md")) if EMAIL_OUT_DIR.exists() else []
    if _drafts:
        from email_outreach import gmail_compose_url
        st.markdown("**生成済み下書き:**")
        for d in _drafts:
            with st.expander(f"✉️ {d.stem}"):
                gmail_url = gmail_compose_url(d)
                if gmail_url:
                    st.link_button("📧 Gmail で下書きを開く (CANDIDATE_EMAIL)", gmail_url)
                    st.caption("宛先・件名・本文は入力済み。CVの添付だけ手動で行い、内容を確認して送信してください "
                               "(URL経由でのファイル自動添付はブラウザ仕様上できません)。")
                else:
                    st.caption("⚠️ 宛先またはSubjectを読み取れず、Gmailリンクを生成できませんでした。")
                st.markdown(d.read_text(encoding="utf-8", errors="replace"))