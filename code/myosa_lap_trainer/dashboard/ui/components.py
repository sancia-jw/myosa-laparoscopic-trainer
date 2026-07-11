"""Reusable Smooth Operator UI components."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import streamlit as st

from ui.navigation import request_page
from ui.theme import logo_path


def render_app_header() -> None:
    lp = logo_path()
    img_html = ""
    if lp and lp.exists():
        try:
            b64 = base64.b64encode(lp.read_bytes()).decode("ascii")
            img_html = (
                f'<img src="data:image/jpeg;base64,{b64}" '
                f'class="so-header-logo" alt="Smooth Operator logo"/>'
            )
        except Exception:
            img_html = '<span class="so-header-fallback">SO</span>'
    else:
        img_html = '<span class="so-header-fallback">SO</span>'

    st.markdown(
        f"""
        <div class="so-app-header">
          <div class="so-header-accent"></div>
          <div class="so-header-brand">
            {img_html}
            <div>
              <div class="so-header-title">SMOOTH OPERATOR</div>
              <div class="so-header-sub">Smart Laparoscopic Skill Trainer</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(
    title: str,
    body: str,
    *,
    action_label: str | None = None,
    action_page: str | None = None,
) -> None:
    st.markdown(
        f"""
        <div class="so-card so-empty">
          <h3>{title}</h3>
          <p>{body}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if action_label and action_page:
        if st.button(action_label, type="primary", key=f"empty_action_{action_page}"):
            request_page(action_page)
            st.rerun()


def render_summary_card(
    *,
    score: int | float,
    score_label: str,
    completion: str,
    strongest: str,
    improvement: str,
    incomplete: bool = False,
) -> None:
    status = "Incomplete trial" if incomplete else score_label
    st.markdown(
        f"""
        <div class="so-card so-summary-card">
          <div class="so-score-xl">{score:.0f}</div>
          <div class="so-score-label">{status}</div>
          <p class="so-summary-line"><strong>Time:</strong> {completion}</p>
          <p class="so-summary-line"><strong>Strongest:</strong> {strongest}</p>
          <p class="so-summary-line"><strong>Focus next:</strong> {improvement}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(title: str, value: str, *, help_text: str = "", css_class: str = "") -> None:
    tip = f'<span class="so-metric-help">{help_text}</span>' if help_text else ""
    st.markdown(
        f"""
        <div class="so-card so-metric-card {css_class}">
          <div class="so-metric-title">{title}</div>
          <div class="so-metric-value">{value}</div>
          {tip}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hover_dwell_bar(hover_ms: int, target_ms: int, *, occ: int | None = None) -> None:
    target_ms = max(1, target_ms)
    pct = min(100.0, 100.0 * hover_ms / target_ms)
    lost = occ == 0
    label = "Target lost — reacquire" if lost else "Hold steady over target"
    st.markdown(f"**{label}**")
    st.markdown(
        f"""
        <div class="so-dwell-wrap">
          <div class="so-dwell-fill" style="width:{pct:.1f}%"></div>
        </div>
        <div class="so-dwell-caption">{hover_ms / 1000:.1f} s / {target_ms / 1000:.1f} s · {pct:.0f}%</div>
        """,
        unsafe_allow_html=True,
    )


def render_category_pct_card(
    label: str,
    quality: float,
    points: float,
    max_points: float,
    color: str,
) -> None:
    st.markdown(
        f"""
        <div class="so-cat-card" style="--cat-color:{color};">
          <div class="so-cat-label">{label}</div>
          <div class="so-cat-pct">{quality:.0f}%</div>
          <div class="so-cat-pts">{points:.1f} / {max_points:.0f} points</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _benchmark_scale(
    raw_value: float,
    good: float,
    okay: float,
    bad: float,
    *,
    lower_is_better: bool,
) -> tuple[float, float, float, float]:
    """Return region boundary percentages (good_end, okay_end, bad_end) and marker position."""
    hi = max(good, okay, bad, raw_value, 1e-6) * 1.15
    lo = 0.0
    span = hi - lo

    def pos(v: float) -> float:
        return min(100.0, max(0.0, 100.0 * (float(v) - lo) / span))

    g, o, b, m = pos(good), pos(okay), pos(bad), pos(raw_value)
    if lower_is_better:
        return g, o, 100.0, m
    return pos(okay), pos(good), 100.0, m


def render_benchmark_track(
    *,
    display_name: str,
    explanation: str,
    raw_value: float | None,
    unit: str,
    good: float,
    okay: float,
    bad: float,
    lower_is_better: bool,
    badge: str,
    earned: float,
    max_pts: float,
) -> None:
    if raw_value is None:
        st.markdown(f"**{display_name}** — no data")
        return

    badge_key = badge.lower().replace(" ", "-").replace("improvement", "work")
    g, o, _, marker = _benchmark_scale(raw_value, good, okay, bad, lower_is_better=lower_is_better)
    direction = "Lower is better" if lower_is_better else "Higher is better"
    val_fmt = f"{raw_value:.1f}" if abs(raw_value) >= 10 else f"{raw_value:.2f}"
    if unit == "ms" and raw_value < 1000:
        val_fmt = f"{raw_value:.0f}"
    display_val = f"{val_fmt} {unit}".strip()

    if lower_is_better:
        track_html = (
            f'<div class="so-track-good" style="width:{g:.1f}%"></div>'
            f'<div class="so-track-okay" style="left:{g:.1f}%;width:{max(0.0, o - g):.1f}%"></div>'
            f'<div class="so-track-bad" style="left:{o:.1f}%;width:{max(0.0, 100.0 - o):.1f}%"></div>'
        )
    else:
        track_html = (
            f'<div class="so-track-bad" style="width:{g:.1f}%"></div>'
            f'<div class="so-track-okay" style="left:{g:.1f}%;width:{max(0.0, o - g):.1f}%"></div>'
            f'<div class="so-track-good" style="left:{o:.1f}%;width:{max(0.0, 100.0 - o):.1f}%"></div>'
        )

    st.markdown(
        f"""<div class="so-benchmark-card">
          <div class="so-benchmark-head">
            <span class="so-benchmark-title">{display_name}</span>
            <span class="so-badge so-badge-{badge_key}">{badge}</span>
          </div>
          <p class="so-benchmark-expl">{explanation}</p>
          <div class="so-benchmark-value-lg">{display_val}</div>
          <div class="so-benchmark-pts">{earned:.1f} / {max_pts:.1f} points</div>
          <div class="so-track" title="{direction}">{track_html}<div class="so-track-marker" style="left:{marker:.1f}%"></div></div>
          <div class="so-track-legend"><span>Good</span><span>Okay</span><span>Needs Work</span><span class="so-track-dir">{direction}</span></div>
        </div>""",
        unsafe_allow_html=True,
    )
