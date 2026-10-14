"""Application calendar and totals for the existing Streamlit dashboard."""
from __future__ import annotations

import calendar
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from application_history import history_counts, history_events, history_rows, load_history


_calendar = components.declare_component(
    "application_calendar", path=str(Path(__file__).parent / "components" / "application_calendar")
)


@st.cache_data(ttl=60, show_spinner=False)
def _load(output_dir: str):
    return load_history(Path(output_dir))


def _table(jobs: list[dict], timezone: str, key: str):
    st.dataframe(
        pd.DataFrame(history_rows(jobs, timezone)), hide_index=True, use_container_width=True,
        column_config={
            "求人": st.column_config.LinkColumn("求人ページ", display_text="開く"),
            "求人ノート": st.column_config.LinkColumn("Obsidian", display_text="開く"),
        }, key=key,
    )


def render_application_history(output_dir: Path):
    st.header("📅 応募履歴")
    st.caption("応募した日と、募集終了を確認した日を振り返る。日付を選ぶと、その日の求人を一覧で確認できます。")
    # A separate preview can read the live vault without copying or writing it.
    source = os.environ.get("JIS_HISTORY_OUTPUT_DIR", str(output_dir))
    with st.spinner("応募履歴を読み込んでいます…"):
        jobs, warnings = _load(source)
    for warning in warnings[:5]:
        st.warning(warning)

    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    counts = history_counts(jobs, today)
    columns = st.columns(4)
    for column, (label, value) in zip(columns, [
        ("累計応募", counts["applied"]), ("今月の応募", counts["this_month"]),
        ("期限切れ", counts["expired"]), ("期限切れ確認日時不明", counts["expired_undated"]),
    ]):
        column.metric(label, f"{value:,}件")

    with st.expander("日付の意味と集計方法"):
        st.write("応募日は、保存済みの応募日です。既存の記録はノートの更新日から補った日付で、応募時刻は残っていません。")
        st.write("期限切れ確認日時は、自動チェックで募集終了を確認した時刻です。実際の締切日時や、手動でチェックを付けた日時とは異なります。")
        st.write("同じURLの求人は1件にまとめています。日時が不明な求人も累計に含みます。応募済みと期限切れの両方に該当する求人は、それぞれに数えます。")
        st.caption("Obsidianで変更した後は「記録を再読み込み」で表示を更新できます。")
    if st.button("記録を再読み込み", key="history_refresh"):
        _load.clear()
        st.rerun()
    if not jobs:
        st.info("応募済み・期限切れの求人がまだありません。Obsidianでチェックした求人がここに表示されます。")
        return

    controls = st.columns([2, 3, 2])
    timezone_label = controls[2].selectbox("確認日時の表示", ["日本（JST）", "英国（現地時間）"], key="history_timezone")
    timezone = "Asia/Tokyo" if timezone_label == "日本（JST）" else "Europe/London"
    events = history_events(jobs, timezone)
    months = sorted({e["date"].strftime("%Y-%m") for e in events} | {today.strftime("%Y-%m")}, reverse=True)
    latest_application = max((j["applied_date"] for j in jobs if j["applied_date"]), default=today)
    default_month = latest_application.strftime("%Y-%m")
    month = controls[0].selectbox("表示する月", months, index=months.index(default_month),
                                format_func=lambda m: f"{m[:4]}年{int(m[5:])}月", key="history_month")
    view = controls[1].radio("表示内容", ["応募", "期限切れ確認", "両方"], horizontal=True, key="history_view")
    visible = [e for e in events if e["date"].strftime("%Y-%m") == month
               and (view == "両方" or e["kind"] == ("applied" if view == "応募" else "expired"))]
    year, month_number = map(int, month.split("-"))
    by_day = {}
    for event in visible:
        by_day.setdefault(event["date"].isoformat(), []).append({
            "kind": event["kind"], "company": event["job"]["company"], "title": event["job"]["title"],
        })
    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month_number)
    default_day = max((e["date"] for e in visible), default=date(year, month_number, 1)).isoformat()
    st.caption(f"この月の表示：{len(visible):,}件　 ·　 ● 応募　／　◆ 期限切れ確認")
    selected = _calendar(
        weeks=[[{"date": day.isoformat(), "day": day.day, "inMonth": day.month == month_number,
                 "today": day == today, "events": by_day.get(day.isoformat(), [])} for day in week] for week in weeks],
        selected=default_day, default=default_day, key=f"history_calendar_{month}_{view}_{timezone}",
    )
    # Ignore stale or malformed component values instead of selecting another month.
    valid_days = {d.isoformat() for week in weeks for d in week if d.month == month_number}
    selected = selected if selected in valid_days else default_day
    day_events = [e for e in visible if e["date"].isoformat() == selected]
    day_jobs = list({e["job"]["report_paths"][0]: e["job"] for e in day_events}.values())
    selected_date = date.fromisoformat(selected)
    st.subheader(f"{selected_date.month}月{selected_date.day}日 · {len(day_jobs)}件")
    if day_jobs:
        _table(day_jobs, timezone, "history_day_jobs")
    else:
        st.caption("この日の記録はありません。")

    with st.expander(f"日時不明の求人 · 応募 {counts['applied_undated']}件 ／ 期限切れ確認 {counts['expired_undated']}件"):
        undated = [j for j in jobs if (j["applied"] and j["applied_date"] is None)
                   or (j["expired"] and j["expired_checked_at"] is None)]
        if undated:
            _table(undated, timezone, "history_undated_jobs")
        else:
            st.caption("日時不明の求人はありません。")
    with st.expander(f"応募済みの全求人 · {counts['applied']}件"):
        applied_jobs = sorted([j for j in jobs if j["applied"]],
                              key=lambda j: j["applied_date"] or date.min, reverse=True)
        if applied_jobs:
            _table(applied_jobs, timezone, "history_all_applications")
        else:
            st.caption("応募済みの求人はまだありません。")
