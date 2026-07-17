"""ARCHIVED: WebUI Kanban tab (removed from app.py 2026-07-17).

Replaced by the 📄 PDF tab: application-status tracking moved to the
Obsidian Kanban board (10_output/Applications.md). This code is kept
verbatim for reference; to restore, paste back into app.py as a tab
block and re-add "📋 Kanban" to st.tabs. Status data lives on in
10_output/00_kanban/kanban.json (never deleted).
"""

with tab_kanban:
    st.header("📋 Job Application Kanban")
    st.markdown("Track your job applications across the pipeline. Change status to move cards between columns.")

    # Load analyzed jobs
    try:
        all_jobs = load_jobs(st.session_state.config)
    except FileNotFoundError:
        st.error("No job data found. Run the scraper first (🔍 Scraper tab).")
        st.stop()

    # Group by URL for dedup
    job_map = {}
    for j in all_jobs:
        url = j.get("url", "")
        if url:
            job_map[url] = j

    # Load kanban data
    kanban = load_kanban_data()

    # Initialise missing jobs
    changed = False
    for url in job_map:
        if url not in kanban:
            kanban[url] = {"status": "📌 Saved", "updated": ""}
            changed = True
    if changed:
        save_kanban_data(kanban)

    # Compute scores for each job (use pre-computed scores from _analyzed.json)
    scored_jobs = []
    for url, j in job_map.items():
        match = j.get("match", {})
        score = match.get("composite_score", 0)
        ctx = match.get("context_score", 0)
        scored_jobs.append({
            "url": url,
            "company": j.get("company", "?"),
            "title": j.get("title", "?"),
            "location": j.get("location", "?"),
            "score": score,
            "context_score": ctx,
            "tier": match.get("tier", ""),
            "status": kanban.get(url, {}).get("status", "📌 Saved"),
            "salary": j.get("analysis", {}).get("salary", {}),
        })

    # --- Filters ---
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        min_score_filter = st.slider("Min score", 0, 100, 0, key="kanban_min_score")
    with col_f2:
        status_filter = st.multiselect(
            "Status", list(KANBAN_STATUSES.keys()),
            default=list(KANBAN_STATUSES.keys()),
            key="kanban_status_filter"
        )
    with col_f3:
        search_query = st.text_input("🔍 Search company/title", key="kanban_search")

    filtered = [
        j for j in scored_jobs
        if j["score"] * 100 >= min_score_filter
        and j["status"] in status_filter
        and (not search_query or search_query.lower() in j["company"].lower()
             or search_query.lower() in j["title"].lower())
    ]

    st.metric("Showing", f"{len(filtered)} jobs")

    # --- Kanban columns layout ---
    col_k1, col_k2, col_k3, col_k4 = st.columns(4)

    col_k1.markdown("### 📌 Saved  —")
    col_k1.markdown("---")
    col_k2.markdown("### 🔄 Active  —")
    col_k2.markdown("---")
    col_k3.markdown("### 💰 Outcome  —")
    col_k3.markdown("---")
    col_k4.markdown("### ❌ Done  —")
    col_k4.markdown("---")

    # Column 1: Saved
    with col_k1:
        for j in sorted(filtered, key=lambda x: x["score"], reverse=True):
            if j["status"] != "📌 Saved":
                continue
            tier_icon = {"Strong": "🟢", "Good": "🟡", "Partial": "🟠", "Weak": "🔴"}.get(
                j["tier"].split()[-2] if j["tier"] else "", "⚪"
            )
            with st.container(border=True):
                cols = st.columns([3, 1])
                with cols[0]:
                    st.markdown(f"**{j['company']}**  ")
                    st.caption(f"{j['title'][:50]}")
                with cols[1]:
                    st.markdown(f"{tier_icon}  `{j['score']*100:.0f}%`", help=f"Context: {j['context_score']*100:.0f}%")
                new_status = st.selectbox(
                    "Status",
                    options=list(KANBAN_STATUSES.keys()),
                    index=0,
                    key=f"ks_saved_{j['url']}",
                    label_visibility="collapsed",
                )
                if new_status != j["status"]:
                    kanban[j["url"]] = {"status": new_status, "updated": ""}
                    save_kanban_data(kanban)
                    st.rerun()
                pdf_export_controls(j["company"], j["title"], f"saved_{j['url']}", j["url"])

    # Column 2: Active (Applied, Screening, Interviewing)
    with col_k2:
        for j in sorted(filtered, key=lambda x: x["score"], reverse=True):
            if j["status"] not in ("📝 Applied", "🔍 Screening", "📞 Interviewing"):
                continue
            tier_icon = {"Strong": "🟢", "Good": "🟡", "Partial": "🟠", "Weak": "🔴"}.get(
                j["tier"].split()[-2] if j["tier"] else "", "⚪"
            )
            with st.container(border=True):
                st.markdown(f"**{j['company']}**  \n{j['status']}")
                st.caption(j["title"][:45])
                st.markdown(f"{tier_icon} `{j['score']*100:.0f}%`")
                new_status = st.selectbox(
                    "→",
                    options=list(KANBAN_STATUSES.keys()),
                    index=list(KANBAN_STATUSES.keys()).index(j["status"]),
                    key=f"ks_active_{j['url']}",
                    label_visibility="collapsed",
                )
                if new_status != j["status"]:
                    kanban[j["url"]] = {"status": new_status, "updated": ""}
                    save_kanban_data(kanban)
                    st.rerun()
                pdf_export_controls(j["company"], j["title"], f"active_{j['url']}", j["url"])

    # Column 3: Offer / Accepted
    with col_k3:
        for j in sorted(filtered, key=lambda x: x["score"], reverse=True):
            if j["status"] not in ("💼 Offer", "✅ Accepted"):
                continue
            with st.container(border=True):
                st.markdown(f"**🎉 {j['company']}**  \n{j['status']}")
                st.caption(j["title"][:45])
                st.markdown(f"`{j['score']*100:.0f}%`")
                new_status = st.selectbox(
                    "→",
                    options=list(KANBAN_STATUSES.keys()),
                    index=list(KANBAN_STATUSES.keys()).index(j["status"]),
                    key=f"ks_offer_{j['url']}",
                    label_visibility="collapsed",
                )
                if new_status != j["status"]:
                    kanban[j["url"]] = {"status": new_status, "updated": ""}
                    save_kanban_data(kanban)
                    st.rerun()
                pdf_export_controls(j["company"], j["title"], f"offer_{j['url']}", j["url"])

    # Column 4: Rejected / Archived
    with col_k4:
        for j in sorted(filtered, key=lambda x: x["score"], reverse=True):
            if j["status"] not in ("❌ Rejected", "🗑️ Archived"):
                continue
            with st.container(border=True):
                st.markdown(f"~~**{j['company']}**~~  \n{j['status']}")
                st.caption(j["title"][:45], help=f"Score: {j['score']*100:.0f}%")
                new_status = st.selectbox(
                    "→",
                    options=list(KANBAN_STATUSES.keys()),
                    index=list(KANBAN_STATUSES.keys()).index(j["status"]),
                    key=f"ks_rejected_{j['url']}",
                    label_visibility="collapsed",
                )
                if new_status != j["status"]:
                    kanban[j["url"]] = {"status": new_status, "updated": ""}
                    save_kanban_data(kanban)
                    st.rerun()
