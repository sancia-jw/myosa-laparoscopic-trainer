"""Trial Breakdown page — human-friendly results."""

from __future__ import annotations

import json

import streamlit as st

from scoring.v2.config import load_active_v2_config
from scoring.v2.metric_metadata import display_name, get_meta, quality_badge
from scoring.v2.presentation import (
    CATEGORY_LABELS,
    build_category_summary,
    display_overall_score,
    format_duration_seconds,
    format_trial_label,
    metric_point_contribution,
)
from storage import get_store
from operating_mode import MODE_LABELS, get_active_mode, render_mode_history_filter
from ui.components import render_benchmark_track, render_category_pct_card, render_empty_state


def render_trial_breakdown() -> None:
    st.markdown("## Trial Breakdown")
    store = get_store()
    _ = st.session_state.get("trial_data_version", 0)
    mode_filter = render_mode_history_filter(key="breakdown_mode")
    trials = store.list_trials(limit=100, mode=mode_filter)
    anon_count = sum(1 for t in trials if not str(t.get("user_name") or "").strip())
    mode_label = MODE_LABELS.get(mode_filter, "All Modes") if mode_filter else "All Modes"
    st.caption(
        f"Showing **{len(trials)}** trial(s) · **{mode_label}** · "
        f"**{anon_count}** anonymous · unnamed trials always appear here (not Track Progress)."
    )
    if not trials:
        render_empty_state(
            "No completed trials yet",
            "Finish a valid trial on Live Trial to see your breakdown here.",
            action_label="Go to Live Trial",
            action_page="Live Trial",
        )
        return

    options = {format_trial_label(t): t["id"] for t in trials}
    ids = list(options.values())
    labels = list(options.keys())
    latest = st.session_state.get("latest_saved_trial_id")
    if latest in ids:
        st.session_state.breakdown_trial_id = latest
    bid = st.session_state.get("breakdown_trial_id")
    default_idx = ids.index(bid) if bid in ids else 0

    label = st.selectbox("Select trial", labels, index=default_idx)
    row_id = options[label]
    st.session_state.breakdown_trial_id = row_id
    row = store.get_trial(row_id)
    if not row:
        return

    cfg = load_active_v2_config(get_store, mode=row.get("mode") or get_active_mode())
    cat_w = cfg.get("category_weights", {})
    raw = json.loads(row.get("raw_metrics_json") or "{}")
    scores = json.loads(row.get("metric_scores_json") or "{}")

    cq = float(row.get("control_score", 0) or 0)
    eq = float(row.get("efficiency_score", 0) or 0)
    tq = float(row.get("target_stability_score", 0) or 0)
    cats = build_category_summary(cq, eq, tq)
    strongest = max(cats, key=lambda k: cats[k]["points"])
    weakest = min(cats, key=lambda k: cats[k]["points"])

    st.markdown(f"### Final Score: **{display_overall_score(row.get('v2_overall'))} / 100**")
    comp = raw.get("completion_time_s")
    st.caption(f"Completion time: **{format_duration_seconds(float(comp) if comp is not None else None)}**")

    st.markdown(
        f"""
        <div class="so-card">
          <p><strong>Strongest area:</strong> {CATEGORY_LABELS.get(strongest, strongest)}</p>
          <p><strong>Highest-priority improvement:</strong> {CATEGORY_LABELS.get(weakest, weakest)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3, gap="small")
    for col, key, color, title in zip(
        (c1, c2, c3),
        ("control", "efficiency", "target_stability"),
        ("#00B4A6", "#7A5CFF", "#58B6FF"),
        ("Control", "Efficiency", "Target Stability"),
    ):
        cat = cats[key]
        with col:
            render_category_pct_card(title, cat["quality"], cat["points"], cat["max_points"], color)

    st.markdown("### Where points were lost")
    lost_rows = []
    for spec in cfg.get("metrics", []):
        name = str(spec["name"])
        sv = scores.get(name)
        if sv is None:
            continue
        earned, max_pts = metric_point_contribution(sv, spec, cat_w)
        lost_rows.append((display_name(name), max_pts - earned, earned, max_pts))
    lost_rows.sort(key=lambda x: x[1], reverse=True)
    for name, lost, earned, max_pts in lost_rows[:6]:
        if max_pts > 0:
            st.caption(f"**{name}** — lost {lost:.1f} pts ({earned:.1f}/{max_pts:.1f} earned)")

    st.markdown("### Metric benchmarks")
    for spec in cfg.get("metrics", []):
        name = str(spec["name"])
        rv = raw.get(name)
        sv = scores.get(name)
        if rv is None and sv is None:
            continue
        meta = get_meta(name)
        dname = meta.display_name if meta else display_name(name)
        expl = meta.explanation if meta else ""
        earned, max_pts = metric_point_contribution(sv, spec, cat_w)
        badge = quality_badge(float(sv) if sv is not None else None)
        if badge == "Needs Improvement":
            badge = "Needs Work"
        render_benchmark_track(
            display_name=dname,
            explanation=expl,
            raw_value=float(rv) if rv is not None else None,
            unit=str(spec.get("units", "")),
            good=float(spec["good"]),
            okay=float(spec["okay"]),
            bad=float(spec["bad"]),
            lower_is_better=str(spec.get("direction", "lower_is_better")) == "lower_is_better",
            badge=badge,
            earned=earned,
            max_pts=max_pts,
        )

    with st.expander("Advanced details"):
        for spec in cfg.get("metrics", []):
            name = spec["name"]
            st.text(
                f"{name}: raw={raw.get(name)} score={scores.get(name)} "
                f"anchors={spec['good']}/{spec['okay']}/{spec['bad']}"
            )
