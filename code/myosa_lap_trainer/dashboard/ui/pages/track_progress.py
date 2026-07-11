"""Track Progress page — named users only."""

from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from operating_mode import MODE_LABELS, render_mode_history_filter
from scoring.v2.presentation import CATEGORY_LABELS, format_duration_seconds, plotly_chart_defaults
from storage import get_store
from ui.components import render_empty_state


def _progress_chart_layout(*, title: str, y_title: str, height: int = 220, y_range: list[float] | None = None) -> dict:
    layout = plotly_chart_defaults()
    yaxis = {
        **layout["yaxis"],
        "title": {"text": y_title, "font": {"color": "#1B1E3F", "size": 12}},
    }
    if y_range is not None:
        yaxis["range"] = y_range
    layout.update(
        height=height,
        title={"text": title, "font": {"color": "#1B1E3F", "size": 14}},
        xaxis={
            **layout["xaxis"],
            "title": {"text": "Trial # (chronological)", "font": {"color": "#1B1E3F", "size": 12}},
            "dtick": 1,
        },
        yaxis=yaxis,
        hovermode="x unified",
        margin={"l": 52, "r": 16, "t": 48, "b": 48},
    )
    return layout


def _trend_trace(df: pd.DataFrame, *, y_col: str, color: str, y_fmt: str = ".1f") -> go.Scatter:
    custom = df[["trial_id", "created_at", "mode"]].fillna("—")
    return go.Scatter(
        x=df["trial_num"],
        y=df[y_col],
        mode="lines+markers+text",
        line=dict(color=color, width=2.5),
        marker=dict(size=9),
        text=[f"{v:{y_fmt}}" if pd.notna(v) else "" for v in df[y_col]],
        textposition="top center",
        textfont=dict(color="#1B1E3F", size=11),
        customdata=custom.values,
        hovertemplate=(
            "Session trial %{x}<br>"
            "Firmware trial %{customdata[0]}<br>"
            "Date %{customdata[1]}<br>"
            "Mode %{customdata[2]}<br>"
            f"{y_col}: %{{y:{y_fmt}}}<extra></extra>"
        ),
        name=y_col,
    )


def _mode_filter_label(mode_filter: str | None) -> str:
    if mode_filter is None:
        return "All Modes"
    return MODE_LABELS.get(mode_filter, mode_filter.title())


def render_track_progress() -> None:
    st.markdown("## Track Progress")
    store = get_store()
    _ = st.session_state.get("trial_data_version", 0)

    mode_filter = render_mode_history_filter(key="track_progress_mode")
    st.caption(f"Showing **{_mode_filter_label(mode_filter)}** trials for the selected user.")

    users = store.list_user_names(mode=mode_filter)
    if not users:
        render_empty_state(
            "No personal history yet",
            "Enter a name before starting a Live Trial to track progress here. "
            "Anonymous trials are still saved — view them under Trial Breakdown.",
            action_label="Go to Live Trial",
            action_page="Live Trial",
        )
        return

    user = st.selectbox("Select user", users)
    trials = list(reversed(store.list_trials(user_name=user, named_only=True, mode=mode_filter)))
    if len(trials) < 1:
        render_empty_state("Not enough data", f"No named trials found for {user}.")
        return

    df = pd.DataFrame(trials).sort_values("created_at").reset_index(drop=True)
    comp_times: list[float | None] = []
    for _, r in df.iterrows():
        try:
            raw = json.loads(r.get("raw_metrics_json") or "{}")
            val = raw.get("completion_time_s")
            comp_times.append(float(val) if val is not None else None)
        except (json.JSONDecodeError, TypeError, ValueError):
            comp_times.append(None)
    df["completion_s"] = comp_times
    df["trial_num"] = range(1, len(df) + 1)
    if "mode" not in df.columns:
        df["mode"] = "open"
    else:
        df["mode"] = df["mode"].fillna("open")

    first_date = str(df["created_at"].iloc[0])[:10]
    last_date = str(df["created_at"].iloc[-1])[:10]
    st.caption(f"**{user}** · {len(df)} trial(s) · {first_date} → {last_date}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Trials", len(df))
    c2.metric("Personal best", f"{df['v2_overall'].max():.0f}", help="Highest overall V2 score")
    c3.metric("Latest", f"{df['v2_overall'].iloc[-1]:.0f}", help="Most recent overall V2 score")
    if len(df) >= 2:
        overall_delta = float(df["v2_overall"].iloc[-1] - df["v2_overall"].iloc[0])
        c4.metric(
            "Overall change",
            f"{overall_delta:+.0f}",
            help="Latest minus first trial in this view",
        )
    else:
        c4.metric("Overall change", "—")
    if df["completion_s"].notna().any():
        c5.metric(
            "Best time",
            format_duration_seconds(float(df["completion_s"].min())),
            help="Fastest completion in this view",
        )
    else:
        c5.metric("Best time", "—")

    if len(df) >= 2:
        deltas = {
            "control_score": float(df["control_score"].iloc[-1] - df["control_score"].iloc[0]),
            "efficiency_score": float(df["efficiency_score"].iloc[-1] - df["efficiency_score"].iloc[0]),
            "target_stability_score": float(
                df["target_stability_score"].iloc[-1] - df["target_stability_score"].iloc[0]
            ),
        }
        improved = max(deltas, key=deltas.get)
        delta_val = deltas[improved]
        label = CATEGORY_LABELS.get(improved, improved)
        if delta_val > 0:
            st.info(f"Most improved category: **{label}** (+{delta_val:.0f} quality points since first trial)")
        elif delta_val < 0:
            st.warning(f"Largest decline: **{label}** ({delta_val:.0f} quality points since first trial)")
        else:
            st.caption("Category scores unchanged between first and latest trial.")

    st.markdown("### Overall score trend")
    fig = go.Figure(_trend_trace(df, y_col="v2_overall", color="#00B4A6", y_fmt=".0f"))
    fig.update_layout(**_progress_chart_layout(title="Overall V2 score", y_title="Score (0–100)", height=260, y_range=[0, 100]))
    st.plotly_chart(fig, use_container_width=True, key="progress_v2")

    st.markdown("### Category trends")
    st.caption("Quality scores (0–100) for each V2 category across trials.")
    cols = [
        ("control_score", "Control", "#00B4A6"),
        ("efficiency_score", "Efficiency", "#7A5CFF"),
        ("target_stability_score", "Target Stability", "#58B6FF"),
    ]
    tcols = st.columns(3)
    for col, (field, title, color) in zip(tcols, cols):
        f2 = go.Figure(_trend_trace(df, y_col=field, color=color))
        f2.update_layout(**_progress_chart_layout(title=title, y_title="Quality (0–100)", height=210, y_range=[0, 100]))
        col.plotly_chart(f2, use_container_width=True, key=f"prog_{field}")

    if df["completion_s"].notna().any():
        st.markdown("### Completion time trend")
        st.caption("Total trial duration in seconds (lower is faster).")
        f3 = go.Figure(_trend_trace(df, y_col="completion_s", color="#7A5CFF", y_fmt=".1f"))
        f3.update_layout(**_progress_chart_layout(title="Completion time", y_title="Seconds", height=210))
        st.plotly_chart(f3, use_container_width=True, key="prog_time")

    st.markdown("### Recent trials")
    show = df[
        [
            "trial_num",
            "trial_id",
            "created_at",
            "mode",
            "v2_overall",
            "control_score",
            "efficiency_score",
            "target_stability_score",
            "completion_s",
        ]
    ].copy()
    show["completion"] = show["completion_s"].apply(
        lambda s: format_duration_seconds(float(s)) if pd.notna(s) else "—"
    )
    show = show.drop(columns=["completion_s"])
    show = show.rename(
        columns={
            "trial_num": "Session #",
            "trial_id": "Firmware #",
            "created_at": "Date/time",
            "mode": "Mode",
            "v2_overall": "Overall",
            "control_score": "Control",
            "efficiency_score": "Efficiency",
            "target_stability_score": "Target stability",
            "completion": "Time",
        }
    )
    for col in ("Overall", "Control", "Efficiency", "Target stability"):
        show[col] = show[col].map(lambda v: f"{float(v):.1f}" if pd.notna(v) else "—")
    st.dataframe(show, use_container_width=True, hide_index=True)
