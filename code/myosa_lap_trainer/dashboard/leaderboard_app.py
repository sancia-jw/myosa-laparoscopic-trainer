"""Conference leaderboard display — run on a second screen (port 8502)."""

from __future__ import annotations

import time

import streamlit as st

from conference_leaderboard import fetch_leaderboard
from operating_mode import MODE_LABELS
from storage import get_store
from ui.theme import inject_theme

LEADERBOARD_CSS = """
<style>
#MainMenu, footer, .stDeployButton {visibility: hidden; height: 0;}
.so-lb-header {
  background: #1B1E3F; color: #FFF7EF; border-radius: 16px;
  padding: 1rem 1.25rem; margin-bottom: 0.75rem; text-align: center;
}
.so-lb-header h1 { color: #FFF7EF !important; margin: 0; font-size: 2.2rem; }
.so-lb-header p { color: rgba(255,247,239,0.85); margin: 0.35rem 0 0; }
.so-lb-row {
  display: grid; grid-template-columns: 90px 1.4fr 140px 160px;
  gap: 1rem; align-items: center; background: #FFFFFF;
  border: 1px solid rgba(27,30,63,0.12); border-radius: 14px;
  padding: 0.9rem 1.1rem; margin-bottom: 0.55rem;
  box-shadow: 0 4px 16px rgba(27,30,63,0.05);
}
.so-lb-row-top { border-left: 6px solid #00B4A6; }
.so-lb-rank { font-size: 2.4rem; font-weight: 800; color: #1B1E3F; text-align: center; }
.so-lb-name { font-size: 1.9rem; font-weight: 700; color: #1B1E3F; }
.so-lb-score { font-size: 2rem; font-weight: 800; color: #00B4A6; text-align: right; }
.so-lb-time { font-size: 1.5rem; font-weight: 600; color: #4A4F73; text-align: right; }
.so-lb-empty {
  text-align: center; color: #4A4F73; font-size: 1.3rem; padding: 2rem 1rem;
}
.so-lb-colhead {
  display: grid; grid-template-columns: 90px 1.4fr 140px 160px;
  gap: 1rem; padding: 0 1.1rem 0.35rem; color: #4A4F73;
  font-size: 0.95rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
}
</style>
"""


def _render_mode_board(mode: str) -> None:
    rows = fetch_leaderboard(mode=mode)
    st.markdown(
        f"""
        <div class="so-lb-header">
          <h1>{MODE_LABELS[mode]} Leaderboard</h1>
          <p>Higher score wins · faster time breaks ties</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not rows:
        st.markdown('<p class="so-lb-empty">No conference results yet.</p>', unsafe_allow_html=True)
        return
    st.markdown(
        """
        <div class="so-lb-colhead">
          <div>Rank</div><div>Participant</div><div style="text-align:right">Score</div>
          <div style="text-align:right">Time</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for row in rows:
        top = " so-lb-row-top" if row["rank"] <= 3 else ""
        st.markdown(
            f"""
            <div class="so-lb-row{top}">
              <div class="so-lb-rank">#{row["rank"]}</div>
              <div class="so-lb-name">{row["name"]}</div>
              <div class="so-lb-score">{row["score"]:.0f}</div>
              <div class="so-lb-time">{row["completion_display"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_leaderboards() -> None:
    open_tab, box_tab = st.tabs([MODE_LABELS["open"], MODE_LABELS["box"]])
    with open_tab:
        _render_mode_board("open")
    with box_tab:
        _render_mode_board("box")


def main() -> None:
    st.set_page_config(
        page_title="Smooth Operator Leaderboard",
        page_icon="🏆",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_theme()
    st.markdown(LEADERBOARD_CSS, unsafe_allow_html=True)
    _ = get_store()

    try:
        import streamlit.components.v1  # noqa: F401

        @st.fragment(run_every=3)
        def auto_refresh_boards() -> None:
            _render_leaderboards()
            st.caption("Auto-refreshes every 3 seconds")

        auto_refresh_boards()
    except Exception:
        _render_leaderboards()
        st.caption("Auto-refreshes every 3 seconds")
        time.sleep(3)
        st.rerun()


if __name__ == "__main__":
    main()
