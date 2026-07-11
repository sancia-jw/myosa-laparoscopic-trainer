"""Smooth Operator theme and branding CSS."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
LOGO_CANDIDATES = [
    ROOT.parent.parent / "logo.jpg",
    ROOT / "assets" / "logo.jpg",
]

THEME_CSS = """
<style>
:root {
  --indigo-depth: #1B1E3F;
  --lagoon-flow: #00B4A6;
  --sky-current: #58B6FF;
  --apricot-drive: #FF8A5B;
  --butter-light: #FFD54A;
  --soft-warm-white: #FFF7EF;
  --vivid-orbit: #7A5CFF;
  --text-muted: #4A4F73;
}

#MainMenu, footer, .stDeployButton {visibility: hidden; height: 0;}
/* Keep header + sidebar toggle visible; do not force sidebar open */
header[data-testid="stHeader"] {
  visibility: visible !important;
  height: auto !important;
  background: transparent !important;
}
header[data-testid="stHeader"] button {
  color: var(--indigo-depth) !important;
}
header[data-testid="stHeader"] button svg,
header[data-testid="stHeader"] button svg path {
  fill: var(--indigo-depth) !important;
  stroke: var(--indigo-depth) !important;
}
button[data-testid="stSidebarCollapseButton"],
button[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"],
button[kind="header"][aria-label*="sidebar" i],
button[kind="header"][aria-label*="Sidebar" i] {
  visibility: visible !important;
  color: var(--indigo-depth) !important;
  background: rgba(27, 30, 63, 0.1) !important;
  border: 2px solid rgba(27, 30, 63, 0.28) !important;
  border-radius: 10px !important;
  min-width: 2.25rem !important;
  min-height: 2.25rem !important;
}
button[data-testid="stSidebarCollapseButton"] svg,
button[data-testid="collapsedControl"] svg,
[data-testid="stSidebarCollapseButton"] svg,
[data-testid="collapsedControl"] svg {
  fill: var(--indigo-depth) !important;
  stroke: var(--indigo-depth) !important;
  color: var(--indigo-depth) !important;
}
.block-container {padding-top: 0.65rem; max-width: 1180px;}
.stApp {background-color: var(--soft-warm-white); color: var(--indigo-depth);}

[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] h1,
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3,
[data-testid="stAppViewContainer"] .stMarkdown {color: var(--indigo-depth);}
[data-testid="stAppViewContainer"] .stCaption, [data-testid="stAppViewContainer"] small {color: var(--text-muted) !important;}
[data-testid="stAppViewContainer"] input, [data-testid="stAppViewContainer"] textarea {
  color: var(--indigo-depth) !important; background: #FFFFFF !important;
}

/* Branded header */
.so-app-header {
  position: relative; background: var(--indigo-depth); border-radius: 18px;
  padding: 1.1rem 1.5rem; margin-bottom: 0.65rem;
  box-shadow: 0 8px 28px rgba(27,30,63,0.18); overflow: hidden;
}
.so-header-accent {
  position: absolute; left: 0; top: 0; bottom: 0; width: 6px;
  background: linear-gradient(180deg, var(--lagoon-flow), var(--sky-current));
}
.so-header-brand {display: flex; align-items: center; gap: 16px; position: relative; z-index: 1;}
.so-header-logo {width: 80px; height: 80px; border-radius: 14px; object-fit: cover;}
.so-header-fallback {
  width: 80px; height: 80px; border-radius: 14px; background: var(--lagoon-flow);
  color: white; display: inline-flex; align-items: center; justify-content: center; font-weight: 800; font-size: 1.4rem;
}
.so-header-title {font-size: 2rem; font-weight: 800; color: var(--soft-warm-white); letter-spacing: 0.04em;}
.so-header-sub {font-size: 1.05rem; color: rgba(255,247,239,0.92); margin-top: 0.15rem;}

/* Page shell tints */
.so-page-shell {border-radius: 16px; padding: 0.5rem 0.75rem 1rem; margin-top: 0.25rem;}
.so-page-live {background: rgba(0,180,166,0.04);}
.so-page-breakdown {background: rgba(88,182,255,0.05);}
.so-page-progress {background: rgba(122,92,255,0.05);}
.so-page-tune {background: rgba(255,213,74,0.06);}

/* Navigation tabs */
.so-nav-wrap {display: flex; gap: 8px; margin-bottom: 0.35rem;}
.so-nav-btn-wrap {flex: 1;}
.so-nav-btn-wrap .stButton > button {
  border-radius: 12px !important; font-weight: 700 !important; min-height: 2.6rem !important;
  transition: transform 0.12s ease, box-shadow 0.12s ease !important;
}
.so-nav-btn-wrap .stButton > button:hover:not(:disabled) {transform: translateY(-1px); box-shadow: 0 4px 12px rgba(27,30,63,0.12);}

.so-tab-live.so-nav-active .stButton > button {
  background: var(--lagoon-flow) !important; color: #fff !important; border: 2px solid var(--lagoon-flow) !important;
}
.so-tab-live.so-nav-inactive .stButton > button {
  background: rgba(0,180,166,0.1) !important; color: var(--indigo-depth) !important;
  border: 2px solid rgba(0,180,166,0.35) !important;
}
.so-tab-breakdown.so-nav-active .stButton > button {
  background: var(--sky-current) !important; color: var(--indigo-depth) !important; border: 2px solid var(--sky-current) !important;
}
.so-tab-breakdown.so-nav-inactive .stButton > button {
  background: rgba(88,182,255,0.12) !important; color: var(--indigo-depth) !important;
  border: 2px solid rgba(88,182,255,0.35) !important;
}
.so-tab-progress.so-nav-active .stButton > button {
  background: var(--vivid-orbit) !important; color: #fff !important; border: 2px solid var(--vivid-orbit) !important;
}
.so-tab-progress.so-nav-inactive .stButton > button {
  background: rgba(122,92,255,0.1) !important; color: var(--indigo-depth) !important;
  border: 2px solid rgba(122,92,255,0.35) !important;
}
.so-tab-tune.so-nav-active .stButton > button {
  background: var(--butter-light) !important; color: var(--indigo-depth) !important; border: 2px solid #E6C200 !important;
}
.so-tab-tune.so-nav-inactive .stButton > button {
  background: rgba(255,213,74,0.15) !important; color: var(--indigo-depth) !important;
  border: 2px solid rgba(255,213,74,0.45) !important;
}

/* Primary / secondary buttons */
[data-testid="stAppViewContainer"] .stButton > button[kind="primary"] {
  background: var(--lagoon-flow) !important; color: #FFFFFF !important;
  border: none !important; border-radius: 12px !important; font-weight: 700 !important;
}
[data-testid="stAppViewContainer"] .stButton > button[kind="secondary"] {
  background: var(--sky-current) !important; color: var(--indigo-depth) !important;
  border: none !important; border-radius: 12px !important; font-weight: 700 !important;
}
.so-btn-stop .stButton > button {
  background: var(--apricot-drive) !important; color: #fff !important; border: none !important;
}
.so-btn-reset .stButton > button {
  background: transparent !important; color: var(--apricot-drive) !important;
  border: 2px solid var(--apricot-drive) !important;
}
.so-btn-view .stButton > button {
  background: var(--sky-current) !important; color: var(--indigo-depth) !important;
}
.so-mode-badge {
  display: inline-block; padding: 0.25rem 0.65rem; border-radius: 8px;
  font-size: 0.78rem; font-weight: 700; margin: 0.35rem 0 0;
}
.so-mode-open { background: var(--lagoon-flow); color: #FFFFFF; }
.so-mode-box { background: var(--sky-current); color: var(--indigo-depth); }

section[data-testid="stSidebar"] {background: var(--indigo-depth);}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] {color: var(--soft-warm-white) !important;}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background: var(--lagoon-flow) !important; color: #FFFFFF !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="secondary"],
section[data-testid="stSidebar"] .stButton > button {
  background: rgba(255,247,239,0.12) !important; color: var(--soft-warm-white) !important;
  border: 1px solid rgba(255,247,239,0.35) !important;
}
section[data-testid="stSidebar"] .stButton > button:disabled {opacity: 0.35 !important;}

.so-card {
  background: #FFFFFF; border: 1px solid rgba(27,30,63,0.12); border-radius: 14px;
  padding: 0.85rem 1rem; box-shadow: 0 4px 18px rgba(27,30,63,0.05); color: var(--indigo-depth);
}
.so-live-score-card .so-score-xl, .so-feedback-card .so-feedback {margin: 0;}
.so-score-hint {font-size: 0.75rem; color: var(--text-muted); margin: 0.25rem 0 0;}
.so-score-xl {font-size: 3.2rem; font-weight: 800; color: var(--indigo-depth); line-height: 1; margin: 0;}
.so-score-label {font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); margin: 0.2rem 0 0;}
.so-feedback {
  font-size: 1.1rem; font-weight: 700; color: var(--indigo-depth);
  background: rgba(0,180,166,0.12); border-left: 4px solid var(--lagoon-flow);
  padding: 0.75rem 0.9rem; border-radius: 10px; margin: 0;
}
.so-feedback-warn {background: rgba(255,138,91,0.14); border-left-color: var(--apricot-drive);}

.so-phase-kicker {font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-muted); margin: 0 0 0.35rem;}
.so-phase-bar {display: flex; gap: 6px; margin: 0 0 0.65rem 0;}
.so-phase-seg {
  flex: 1; text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px;
  font-size: 0.76rem; font-weight: 700; border: 2px solid transparent;
}
.so-phase-active .so-phase-name {font-size: 1.05rem; display: block;}
.so-phase-done {background: rgba(0,180,166,0.18); border-color: var(--lagoon-flow); color: var(--indigo-depth);}
.so-phase-active {background: var(--lagoon-flow); color: #FFFFFF;}
.so-phase-future {background: rgba(27,30,63,0.05); color: var(--text-muted);}

.so-brand-title {font-size: 1.35rem; font-weight: 800; color: var(--soft-warm-white); margin: 0;}
.so-brand-sub {font-size: 0.8rem; color: rgba(255,247,239,0.88); margin: 0;}
.so-metric-card {padding: 0.65rem 0.75rem !important;}
.so-metric-card .so-metric-title {font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted);}
.so-metric-card .so-metric-value {font-size: 1.35rem; font-weight: 800; color: var(--indigo-depth);}
.so-metric-help {font-size: 0.7rem; color: var(--text-muted); display: block; margin-top: 0.15rem;}

.so-dwell-wrap {height: 10px; background: rgba(27,30,63,0.08); border-radius: 8px; overflow: hidden; margin: 0.3rem 0;}
.so-dwell-fill {height: 100%; background: var(--sky-current); border-radius: 8px; transition: width 0.25s ease;}
.so-dwell-caption {font-size: 0.82rem; color: var(--text-muted); margin-bottom: 0.4rem;}

.so-cat-card {
  background: color-mix(in srgb, var(--cat-color) 12%, white);
  border: 1px solid color-mix(in srgb, var(--cat-color) 35%, transparent);
  border-radius: 14px; padding: 0.85rem 1rem; text-align: center;
  min-height: 118px; height: 100%; box-sizing: border-box;
  display: flex; flex-direction: column; justify-content: center;
}
.so-cat-label {font-size: 0.85rem; font-weight: 700; color: var(--indigo-depth);}
.so-cat-pct {font-size: 2rem; font-weight: 800; color: var(--indigo-depth); line-height: 1.1;}
.so-cat-pts {font-size: 0.82rem; color: var(--text-muted); margin-top: 0.2rem;}

.so-summary-line {margin: 0.3rem 0; color: var(--indigo-depth);}
.so-empty h3 {margin-top: 0;}

.so-cal-btn-good button, .so-cal-btn-okay button, .so-cal-btn-bad button {
  min-height: 3.2rem !important; font-size: 1.05rem !important; font-weight: 800 !important;
  border-radius: 14px !important; border-width: 2px !important;
}
.so-cal-btn-good button {background: rgba(0,180,166,0.12) !important; color: var(--indigo-depth) !important; border-color: rgba(0,180,166,0.4) !important;}
.so-cal-btn-okay button {background: rgba(255,213,74,0.18) !important; color: var(--indigo-depth) !important; border-color: rgba(255,213,74,0.5) !important;}
.so-cal-btn-bad button {background: rgba(255,138,91,0.12) !important; color: var(--indigo-depth) !important; border-color: rgba(255,138,91,0.4) !important;}
.so-cal-selected.so-cal-btn-good button {background: var(--lagoon-flow) !important; color: #fff !important; border-color: var(--lagoon-flow) !important; box-shadow: 0 0 0 3px rgba(0,180,166,0.25);}
.so-cal-selected.so-cal-btn-okay button {background: var(--butter-light) !important; color: var(--indigo-depth) !important; border-color: #C9A800 !important; box-shadow: 0 0 0 3px rgba(255,213,74,0.35);}
.so-cal-selected.so-cal-btn-bad button {background: var(--apricot-drive) !important; color: #fff !important; border-color: var(--apricot-drive) !important; box-shadow: 0 0 0 3px rgba(255,138,91,0.25);}

.so-badge {display: inline-block; padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.78rem; font-weight: 700;}
.so-badge-good {background: rgba(0,180,166,0.15); color: var(--lagoon-flow);}
.so-badge-okay {background: rgba(255,213,74,0.25); color: var(--indigo-depth);}
.so-badge-needs-work {background: rgba(255,138,91,0.18); color: var(--apricot-drive);}

.so-benchmark-card {background: #fff; border: 1px solid rgba(27,30,63,0.1); border-radius: 14px; padding: 1rem 1.1rem; margin-bottom: 0.75rem;}
.so-benchmark-head {display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap;}
.so-benchmark-title {font-size: 1.15rem; font-weight: 800;}
.so-benchmark-expl {font-size: 0.88rem; color: var(--text-muted); margin: 0.35rem 0 0.5rem;}
.so-benchmark-value-lg {font-size: 1.6rem; font-weight: 800; color: var(--indigo-depth);}
.so-benchmark-pts {font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.6rem;}

.so-track {position: relative; height: 14px; border-radius: 8px; overflow: visible; background: rgba(27,30,63,0.06); margin: 0.5rem 0;}
.so-track-good, .so-track-okay, .so-track-bad {position: absolute; top: 0; height: 100%;}
.so-track-good {left: 0; background: rgba(0,180,166,0.55);}
.so-track-okay {background: rgba(255,213,74,0.55);}
.so-track-bad {background: rgba(255,138,91,0.5);}
.so-track-marker {
  position: absolute; top: -5px; width: 0; height: 0;
  border-left: 7px solid transparent; border-right: 7px solid transparent;
  border-bottom: 10px solid var(--indigo-depth); transform: translateX(-50%);
}
.so-track-legend {display: flex; gap: 1rem; font-size: 0.72rem; color: var(--text-muted); flex-wrap: wrap;}
.so-track-dir {margin-left: auto; font-style: italic;}
</style>
"""


def inject_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def logo_path() -> Path | None:
    for p in LOGO_CANDIDATES:
        if p.exists():
            return p
    return None


def render_sidebar_branding() -> None:
    lp = logo_path()
    if lp:
        try:
            st.image(str(lp), use_container_width=True)
        except Exception:
            st.markdown('<p class="so-brand-title">SMOOTH OPERATOR</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="so-brand-title">SMOOTH OPERATOR</p>', unsafe_allow_html=True)
    st.markdown('<p class="so-brand-sub">Smart Laparoscopic Skill Trainer</p>', unsafe_allow_html=True)
