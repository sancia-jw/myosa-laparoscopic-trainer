"""Live Trial page — complete live coach on one screen."""

from __future__ import annotations

from typing import Any, Callable

import plotly.graph_objects as go
import streamlit as st

from live_metrics import get_metric_display
from scoring.v2.config import get_scorer_mode
from scoring.v2.metric_metadata import display_name
from scoring.v2.phases import PHASES, phase_index
from scoring.v2.presentation import (
    build_category_summary,
    display_overall_score,
    format_duration_ms,
    plotly_chart_defaults,
)
from scoring.v2.validity import required_hover_dwell_ms
from session_sync import control_flags
from storage import get_store
from trial_context import clear_trial_context, context_for_save, snapshot_trial_context
from ui.components import (
    render_category_pct_card,
    render_hover_dwell_bar,
    render_metric_card,
    render_summary_card,
)
from conference_mode import is_conference_mode
from operating_mode import get_active_mode, MODE_LABELS
from ui.navigation import request_page


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _live_quality_chart(series: list[dict], key: str) -> None:
    if len(series) < 2:
        return
    window = series[-50:]
    xs = list(range(len(window)))
    rot, lin = [], []
    for row in window:
        rot.append(_safe_float(row.get("rot")))
        lin.append(_safe_float(row.get("lin")))
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=rot,
            name="Rotational quality",
            line=dict(color="#00B4A6", width=2.5),
            connectgaps=True,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=lin,
            name="Linear quality",
            line=dict(color="#58B6FF", width=2.5),
            connectgaps=True,
        )
    )
    layout = plotly_chart_defaults()
    layout.update(
        height=220,
        margin=dict(t=36, b=32, l=48, r=16),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            font=dict(color="#1B1E3F", size=12),
        ),
        yaxis=dict(range=[0, 100], title=dict(text="Quality (0–100)", font=dict(color="#1B1E3F"))),
        xaxis=dict(title=dict(text="Samples", font=dict(color="#1B1E3F"))),
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True, key=key)


def render_phase_bar(phase_key: str) -> None:
    idx = phase_index(phase_key)
    parts = []
    for i, (_, label, _) in enumerate(PHASES):
        css = "so-phase-done" if i < idx else ("so-phase-active" if i == idx else "so-phase-future")
        inner = f'<span class="so-phase-name">{label}</span>' if i == idx else label
        parts.append(f'<div class="so-phase-seg {css}">{inner}</div>')
    st.markdown(
        f"""
        <p class="so-phase-kicker">CURRENT PHASE</p>
        <div class="so-phase-bar">{"".join(parts)}</div>
        """,
        unsafe_allow_html=True,
    )


CAL_HELP = {
    "good": "Controlled, smooth, and deliberate.",
    "okay": "Natural performance with minor corrections.",
    "bad": "Deliberately abrupt, hesitant, or inefficient.",
}


def render_live_trial(*, session_action: Callable[[str], None], connected: bool) -> None:
    session = str(st.session_state.get("session", "READY")).upper()
    flags = control_flags(session)
    fw = str(st.session_state.get("current_state", "IDLE")).upper()
    last = st.session_state.get("live_metrics_last") or {}

    if session in ("IDLE", "READY"):
        cal_pending = bool(st.session_state.get("calibration_pending"))
        cal_label = str(st.session_state.get("calibration_label") or "")
        device_ready = connected and session == "READY" and fw in ("IDLE", "READY")

        if cal_pending:
            st.markdown("## Calibration Trial")
            st.caption(f"**{MODE_LABELS[get_active_mode()]}**")
            st.info(
                f"Collecting **{cal_label.title() or 'labeled'}** calibration data. "
                f"Complete a full trial — results save under Tune Scoring → Stored Trials."
            )
            if cal_label:
                st.caption(CAL_HELP.get(cal_label, ""))
            if not connected:
                st.warning("Connect device in the sidebar to begin.")
            elif not device_ready:
                st.warning("Waiting for firmware READY state.")
            else:
                st.success("Device ready — start the calibration trial when you are set.")
            if st.session_state.get("pending_calibration_start") and device_ready:
                st.session_state.pending_calibration_start = False
                snapshot_trial_context(st.session_state)
                session_action("s")
                st.rerun()
            if st.button(
                "Start Calibration Trial",
                type="primary",
                use_container_width=True,
                disabled=not device_ready,
                key="live_start_calibration",
            ):
                snapshot_trial_context(st.session_state)
                session_action("s")
            if st.button("Cancel calibration", use_container_width=True, key="live_cancel_calibration"):
                st.session_state.calibration_pending = False
                st.session_state.pending_calibration_start = False
                clear_trial_context(st.session_state)
                request_page("Tune Scoring")
                st.rerun()
            return

        st.markdown("## Ready to Train")
        st.caption(f"**{MODE_LABELS[get_active_mode()]}**")
        conference = is_conference_mode()
        if conference:
            st.info("**Conference mode** — enter participant name before starting.")
        if not connected:
            st.warning("Connect device to begin.")
        elif not device_ready:
            st.warning("Waiting for firmware READY state.")
        elif fw in ("IDLE", "READY"):
            st.success("Device ready — press Start Trial when you are set.")
        participant = st.text_input(
            "Participant name" if conference else "Operator name (optional)",
            key="user_name_input",
            placeholder="Required for conference mode" if conference else "Add a name to save personal progress.",
        )
        if conference:
            st.caption("Participant name is required for conference trials.")
        else:
            st.caption("Add a name to save personal progress.")
        name_ok = bool(str(participant or "").strip()) or not conference
        if conference and not name_ok:
            st.warning("Enter participant name before starting.")
        if st.button(
            "Start Trial",
            type="primary",
            use_container_width=True,
            disabled=not device_ready or not name_ok,
        ):
            st.session_state.calibration_pending = False
            st.session_state.trial_valid = True
            snapshot_trial_context(st.session_state)
            session_action("s")
        return

    if session == "RUNNING":
        cal_ctx = context_for_save(st.session_state)
        if cal_ctx.get("source_type") == "manual_calibration":
            label = str(cal_ctx.get("manual_label") or "labeled")
            st.info(f"**Calibration trial** — collecting **{label.title()}** performance data.")
        lv2 = st.session_state.get("live_v2") or {}
        phase = lv2.get("phase", "approach")
        render_phase_bar(phase)

        use_v1 = get_scorer_mode(get_store, mode=get_active_mode()) == "v1_legacy"
        score = (
            _safe_int(st.session_state.get("live_score", 0))
            if use_v1
            else _safe_int(lv2.get("displayed_score", st.session_state.get("live_v2_score", 0)))
        )
        feedback = st.session_state.get("immediate_feedback", "Smooth and controlled")
        warn = feedback in ("Target lost — reacquire", "Reduce abrupt linear motion", "Fewer corrections")
        fb_class = "so-feedback so-feedback-warn" if warn else "so-feedback"
        elapsed = _safe_int(last.get("elapsed_ms", st.session_state.get("elapsed_ms", 0)))

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                f"""
                <div class="so-card so-live-score-card">
                  <p class="so-score-xl">{score}</p>
                  <p class="so-score-label">{"LIVE SCORE (V1)" if use_v1 else "LIVE SCORE"}</p>
                  <p class="so-score-hint">Provisional — final score after trial completes</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
                <div class="so-card so-feedback-card">
                  <p class="{fb_class}">{feedback}</p>
                  <p class="so-score-label">Immediate Feedback</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        if phase == "stable_hover":
            hover_ms = _safe_int(last.get("hover_ms", 0))
            target_ms = _safe_int(
                last.get("hover_target_ms"),
                required_hover_dwell_ms(st.session_state.get("thresholds")),
            )
            occ = last.get("occ")
            occ_i = _safe_int(occ) if occ is not None else None
            render_hover_dwell_bar(hover_ms, target_ms, occ=occ_i)

        m1, m2, m3, m4, m5 = st.columns(5)
        with m1:
            render_metric_card(
                display_name("course_smoothness_gyro_rms"),
                get_metric_display(last, "gyro_rms", fmt="{:.1f}"),
                help_text="Rotational control",
                css_class="so-metric-smooth",
            )
        with m2:
            render_metric_card(
                display_name("course_jerk_rms"),
                get_metric_display(last, "jerk_rms", fmt="{:.1f}"),
                help_text="Linear motion control",
                css_class="so-metric-hover",
            )
        with m3:
            render_metric_card(
                display_name("correction_spike_rate"),
                get_metric_display(last, "spike_rate", fmt="{:.2f}"),
                help_text="Abrupt corrections",
                css_class="so-metric-warn",
            )
        with m4:
            stable = last.get("stable")
            val = "Yes" if stable is not None and int(stable) else ("No" if stable is not None else "—")
            render_metric_card("Hover Stability", val, css_class="so-metric-hover")
        with m5:
            render_metric_card("Elapsed Time", format_duration_ms(elapsed))

        _live_quality_chart(st.session_state.get("live_chart_series") or [], "live_motion_quality")

        b1, b2 = st.columns(2)
        with b1:
            st.markdown('<div class="so-btn-stop">', unsafe_allow_html=True)
            if st.button("Stop Trial", use_container_width=True, disabled=not flags["stop"]):
                session_action("e")
            st.markdown("</div>", unsafe_allow_html=True)
        with b2:
            st.markdown('<div class="so-btn-reset">', unsafe_allow_html=True)
            if st.button("Reset", use_container_width=True, disabled=not flags["reset"]):
                session_action("r")
            st.markdown("</div>", unsafe_allow_html=True)
        return

    if session == "COMPLETE":
        use_v1 = get_scorer_mode(get_store, mode=get_active_mode()) == "v1_legacy"
        v2 = st.session_state.get("latest_v2_final") or st.session_state.get("latest_v2_preview") or {}
        fin = st.session_state.get("latest_final") or {}
        total_ms = _safe_int(fin.get("total_ms", st.session_state.get("elapsed_ms", 0)))
        valid = bool(st.session_state.get("trial_valid", True))
        incomplete_msg = str(st.session_state.get("trial_status_message", ""))
        cal_ctx = context_for_save(st.session_state)
        is_calibration = cal_ctx.get("source_type") == "manual_calibration"

        if is_calibration:
            st.markdown("## Calibration Trial Complete")
            label = str(cal_ctx.get("manual_label") or "labeled")
            st.success(
                f"Calibration data saved as **{label.title()}** — "
                "view it under **Tune Scoring → Stored Trials**."
            )
            if not valid:
                st.warning(
                    incomplete_msg
                    or "Trial did not meet full hover requirements — scores are provisional, but calibration metrics were saved."
                )
        elif not valid:
            st.markdown("## Trial Incomplete")
            st.warning(incomplete_msg or "Incomplete — stable hover not completed.")
            render_summary_card(
                score=0,
                score_label="Not scored",
                completion=format_duration_ms(total_ms),
                strongest="—",
                improvement="Complete stable hover before stopping",
                incomplete=True,
            )
        elif use_v1:
            st.markdown("## Trial Complete")
            display_score = _safe_int(fin.get("total", st.session_state.get("live_score", 0)))
            render_summary_card(
                score=display_score,
                score_label="Final Score (V1 Legacy)",
                completion=format_duration_ms(total_ms),
                strongest="—",
                improvement=str(fin.get("feedback", "")),
            )
        elif is_calibration or valid:
            if not is_calibration:
                st.markdown("## Trial Complete")
            cq = _safe_float(v2.get("control_score"))
            eq = _safe_float(v2.get("efficiency_score"))
            tq = _safe_float(v2.get("target_stability_score"))
            cats = build_category_summary(cq, eq, tq)
            final_score = display_overall_score(v2.get("overall_score"))
            render_summary_card(
                score=final_score,
                score_label="Final Score / 100",
                completion=format_duration_ms(total_ms),
                strongest=str(v2.get("strongest_category", "—")),
                improvement=str(v2.get("weakest_category", "—")),
            )
            cat_cols = st.columns(3, gap="small")
            for col, key, color, label in zip(
                cat_cols,
                ("control", "efficiency", "target_stability"),
                ("#00B4A6", "#7A5CFF", "#58B6FF"),
                ("Control", "Efficiency", "Target Stability"),
            ):
                cat = cats[key]
                with col:
                    render_category_pct_card(
                        label,
                        cat["quality"],
                        cat["points"],
                        cat["max_points"],
                        color,
                    )

        btn_cols = st.columns(2, gap="medium")
        with btn_cols[0]:
            if st.button("Start Next Trial", type="primary", use_container_width=True):
                session_action("r")
        with btn_cols[1]:
            if st.button(
                "View Results",
                type="secondary",
                use_container_width=True,
                disabled=not valid and not is_calibration,
                key="complete_view_results",
            ):
                request_page("Trial Breakdown")
                st.rerun()
        return

    if session == "ERROR":
        st.error("Sensor unavailable — check connection and press Reset.")
        if st.button("Reset", type="primary"):
            session_action("r")
