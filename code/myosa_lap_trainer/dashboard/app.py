"""
MYOSA Laparoscopic Trainer — product-style Streamlit dashboard.
Connects to firmware via pyserial; parses EVENT / LIVE / FINAL_SCORE lines.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import serial
import serial.tools.list_ports
import streamlit as st

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
SUMMARY_DIR = ROOT / "data" / "summary"
SUMMARY_CSV = SUMMARY_DIR / "trials.csv"
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

BAUD = 115200
RAW_LOG_MAX = 200
LIVE_BUFFER_MAX = 40
POLL_FRAGMENT_SEC = 0.4
DATA_QUIET_SEC = 5.0

COMPONENT_LABELS = [
    ("course", "Course", 35),
    ("hover", "Hover", 30),
    ("axis", "Axis", 15),
    ("flow", "Flow", 10),
    ("target", "Target", 5),
    ("dock", "Dock", 5),
]

COMPONENT_COLORS = {
    "course": "#3498db",
    "hover": "#2ecc71",
    "axis": "#9b59b6",
    "flow": "#f39c12",
    "target": "#1abc9c",
    "dock": "#e74c3c",
}

COURSE_STEPS = [
    ("start", "🟢 Start", "GREEN START"),
    ("tube", "Tube", "Tube / entry"),
    ("poles", "Poles", "Course"),
    ("target", "🎯 Target", "Purple target"),
    ("hover", "Hover", "Stable hover"),
    ("dock", "🔴 Dock", "RED END"),
    ("complete", "✅ Done", "Complete"),
]

FLOW_IDEAL_LO_S = 25
FLOW_IDEAL_HI_S = 35
FLOW_TARGET_S = 30
HOVER_TARGET_MS_DEFAULT = 2000

STATUS_BANNERS = {
    "IDLE": "Ready: Press GREEN START",
    "APPROACH": "Navigate tube and poles smoothly",
    "HOVER": "Hold steady over target",
    "DOCK": "Press RED dock gently",
    "COMPLETE": "Trial complete: review score",
}

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
.hero-card {
  background: linear-gradient(135deg, #1a5276 0%, #154360 100%);
  color: #fff;
  padding: 1.25rem 1.5rem;
  border-radius: 12px;
  margin-bottom: 1rem;
  box-shadow: 0 4px 14px rgba(0,0,0,0.15);
}
.hero-card h1 { color: #fff !important; font-size: 1.75rem !important; margin: 0 0 0.25rem 0 !important; }
.hero-card .sub { opacity: 0.9; font-size: 1rem; }
.metric-card {
  background: var(--secondary-background-color, #f8f9fa);
  border: 1px solid rgba(128,128,128,0.25);
  border-radius: 10px;
  padding: 0.85rem 1rem;
  text-align: center;
  min-height: 5.5rem;
}
.metric-card .label { font-size: 0.8rem; opacity: 0.75; text-transform: uppercase; letter-spacing: 0.04em; }
.metric-card .value { font-size: 2rem; font-weight: 700; line-height: 1.2; }
.state-badge {
  display: inline-block;
  font-size: 1.35rem;
  font-weight: 700;
  padding: 0.35rem 0.9rem;
  border-radius: 8px;
  background: rgba(255,255,255,0.15);
}
.status-banner {
  font-size: 1.15rem;
  font-weight: 600;
  padding: 0.65rem 1rem;
  border-radius: 8px;
  margin: 0.5rem 0 1rem 0;
  border-left: 4px solid #3498db;
  background: rgba(52,152,219,0.12);
}
.coach-card {
  font-size: 1.45rem;
  font-weight: 600;
  padding: 1rem 1.25rem;
  border-radius: 10px;
  margin: 0.75rem 0;
  text-align: center;
}
.coach-good { background: rgba(46,204,113,0.18); border: 2px solid #2ecc71; color: #1e8449; }
.coach-warn { background: rgba(241,196,15,0.18); border: 2px solid #f1c40f; color: #9a7d0a; }
.coach-bad  { background: rgba(231,76,60,0.15); border: 2px solid #e74c3c; color: #922b21; }
.coach-neutral { background: rgba(128,128,128,0.12); border: 2px solid rgba(128,128,128,0.4); }
.skill-card {
  border: 1px solid rgba(128,128,128,0.3);
  border-radius: 10px;
  padding: 0.75rem;
  min-height: 6rem;
}
.skill-card h4 { margin: 0 0 0.35rem 0; font-size: 0.95rem; }
.course-map { display: flex; flex-wrap: wrap; gap: 6px; align-items: stretch; margin: 0.75rem 0 1rem 0; }
.course-step {
  flex: 1 1 90px;
  min-width: 72px;
  text-align: center;
  padding: 0.55rem 0.35rem;
  border-radius: 8px;
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1.25;
  border: 2px solid transparent;
}
.phase-complete { background: rgba(46,204,113,0.2); border-color: #27ae60; color: #1e8449; }
.phase-current  { background: rgba(52,152,219,0.25); border-color: #2980b9; color: #1a5276; font-size: 0.85rem; }
.phase-future   { background: rgba(128,128,128,0.08); border-color: rgba(128,128,128,0.25); opacity: 0.65; }
.course-arrow { align-self: center; opacity: 0.4; font-size: 0.7rem; }
.report-score { font-size: 3rem; font-weight: 800; line-height: 1; }
.conn-ok { color: #2ecc71; font-weight: 600; }
.conn-warn { color: #f39c12; font-weight: 600; }
.conn-off { color: #95a5a6; font-weight: 600; }
</style>
"""


def inject_custom_css() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Safe helpers
# ---------------------------------------------------------------------------
def safe_get(d: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if not d:
        return default
    return d.get(key, default)


def safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse_key_value_line(line: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    line = line.strip()
    if not line or line.startswith("#"):
        return out
    parts = [p.strip() for p in line.split(",") if p.strip()]
    for i, part in enumerate(parts):
        if "=" not in part:
            if i == 0:
                out["type"] = part
            continue
        key, _, val = part.partition("=")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if re.fullmatch(r"-?\d+", val):
            out[key] = int(val)
        elif re.fullmatch(r"-?\d+\.\d+", val) or re.fullmatch(r"-?\d+\.\d*e[+-]?\d+", val, re.I):
            try:
                out[key] = float(val)
            except ValueError:
                out[key] = val
        else:
            out[key] = val
    return out


def parse_event_line(line: str) -> dict[str, Any] | None:
    if not line.startswith("EVENT,"):
        return None
    d = parse_key_value_line(line)
    d["type"] = "EVENT"
    d["received_at"] = datetime.now().isoformat(timespec="seconds")
    return d


def parse_live_line(line: str) -> dict[str, Any] | None:
    if not line.startswith("LIVE,"):
        return None
    d = parse_key_value_line(line)
    d["type"] = "LIVE"
    d["received_at"] = datetime.now().isoformat(timespec="seconds")
    if "hover" in d and isinstance(d["hover"], str) and "/" in str(d["hover"]):
        try:
            a, b = str(d["hover"]).split("/", 1)
            d["hover_ms"] = int(float(a))
            d["hover_target_ms"] = int(float(b))
        except ValueError:
            pass
    return d


def parse_final_score_line(line: str) -> dict[str, Any] | None:
    if not line.startswith("FINAL_SCORE,"):
        return None
    d = parse_key_value_line(line)
    d["type"] = "FINAL_SCORE"
    d["received_at"] = datetime.now().isoformat(timespec="seconds")
    return d


def parse_calibration_line(line: str) -> dict[str, Any] | None:
    if line.startswith("CAL_SET,"):
        d = parse_key_value_line(line)
        d["type"] = "CAL_SET"
        return d
    if line.startswith("CAL_CLEAR"):
        return {"type": "CAL_CLEAR", "raw": line.strip()}
    return None


def parse_threshold_block(lines: list[str]) -> dict[str, Any]:
    th: dict[str, Any] = {"calibration_active": False}
    for line in lines:
        line = line.strip()
        if line.startswith("calibration="):
            th["calibration_active"] = "active" in line.lower()
        elif line.startswith("cal_course_gyro_rms="):
            try:
                th["cal_course_gyro_rms"] = float(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line.startswith("cal_course_jerk_rms="):
            try:
                th["cal_course_jerk_rms"] = float(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line.startswith("cal_course_spike_rate="):
            try:
                th["cal_course_spike_rate"] = float(line.split("=", 1)[1])
            except ValueError:
                pass
        elif "good/bad=" in line:
            m = re.match(r"([\w_]+(?:\s+[\w_]+)*)\s+good/bad=([^/]+)/(.+)", line)
            if m:
                key = m.group(1).strip().replace(" ", "_")
                try:
                    th[f"{key}_good"] = float(m.group(2))
                    th[f"{key}_bad"] = float(m.group(3))
                except ValueError:
                    pass
        elif line.startswith("flow_target_ms="):
            m = re.search(r"(\d+)-(\d+)", line)
            if m:
                th["flow_lo_ms"] = int(m.group(1))
                th["flow_hi_ms"] = int(m.group(2))
        elif line.startswith("apds_enter/exit="):
            m = re.search(r"([\d.]+)/([\d.]+)", line)
            if m:
                th["apds_enter"] = float(m.group(1))
                th["apds_exit"] = float(m.group(2))
        elif line.startswith("hover_dwell_ms="):
            try:
                th["hover_dwell_ms"] = int(line.split("=", 1)[1])
            except ValueError:
                pass
    return th


def _touch_data_received() -> None:
    st.session_state.last_data_ts = time.time()


def ingest_line(line: str) -> None:
    line = line.strip()
    if not line:
        return
    st.session_state.raw_lines.append(line)
    if len(st.session_state.raw_lines) > RAW_LOG_MAX:
        st.session_state.raw_lines = st.session_state.raw_lines[-RAW_LOG_MAX:]

    try:
        if line.startswith("EVENT,"):
            ev = parse_event_line(line)
            if ev:
                _touch_data_received()
                st.session_state.events.append(ev)
                st.session_state.latest_event = ev
                if "trial" in ev:
                    st.session_state.current_trial = int(ev["trial"])
                if "state" in ev:
                    st.session_state.current_state = str(ev["state"]).upper()
                if "score" in ev:
                    st.session_state.live_score = int(ev["score"])
                if "feedback" in ev:
                    st.session_state.current_feedback = str(ev["feedback"])
                elif "issue" in ev:
                    st.session_state.current_feedback = str(ev["issue"])
                if ev.get("event") == "DOCK_COMPLETE":
                    st.session_state.current_state = "COMPLETE"
            return

        if line.startswith("LIVE,"):
            live = parse_live_line(line)
            if live:
                _touch_data_received()
                st.session_state.latest_live = live
                st.session_state.live_rows.append(live)
                if len(st.session_state.live_rows) > LIVE_BUFFER_MAX:
                    st.session_state.live_rows = st.session_state.live_rows[-LIVE_BUFFER_MAX:]
                if "state" in live:
                    st.session_state.current_state = str(live["state"]).upper()
                if "score" in live:
                    st.session_state.live_score = int(live["score"])
                if "issue" in live:
                    st.session_state.current_feedback = str(live["issue"])
            return

        if line.startswith("FINAL_SCORE,"):
            fin = parse_final_score_line(line)
            if fin:
                _touch_data_received()
                st.session_state.latest_final = fin
                st.session_state.current_state = "COMPLETE"
                if "total" in fin:
                    st.session_state.live_score = int(fin["total"])
                if "feedback" in fin:
                    st.session_state.current_feedback = str(fin["feedback"])
                if "trial" in fin:
                    st.session_state.current_trial = int(fin["trial"])
                upsert_completed_trial(fin)
                st.session_state.prev_score = int(fin.get("total", 0))
                st.session_state.prev_feedback = str(fin.get("feedback", ""))
                _save_trials_csv()
            return

        if " good/bad=" in line or line.startswith("calibration="):
            partial = parse_threshold_block([line])
            if partial:
                st.session_state.thresholds = {**st.session_state.thresholds, **partial}
            return

        cal = parse_calibration_line(line)
        if cal:
            st.session_state.calibration = {**st.session_state.calibration, **cal}
            return

        if line.startswith("# --- scoring thresholds"):
            st.session_state.threshold_buffer = [line]
            return
        if st.session_state.threshold_buffer and (
            line.startswith("#") or "good/bad=" in line or line.startswith("calibration=")
            or line.startswith("flow_") or line.startswith("apds_") or line.startswith("hover_")
            or line.startswith("dock_") or line.startswith("tilt ") or line.startswith("cal_")
        ):
            st.session_state.threshold_buffer.append(line)
            if "----------" in line and len(st.session_state.threshold_buffer) > 2:
                st.session_state.thresholds = parse_threshold_block(st.session_state.threshold_buffer)
                st.session_state.threshold_buffer = []
            return

    except Exception as exc:  # noqa: BLE001
        st.session_state.last_parse_error = str(exc)
        st.session_state.parse_error_count = int(st.session_state.get("parse_error_count", 0)) + 1


def upsert_completed_trial(fin: dict[str, Any]) -> None:
    trial_id = fin.get("trial")
    trials: list[dict[str, Any]] = st.session_state.completed_trials
    if trial_id is not None:
        for i, row in enumerate(trials):
            if row.get("trial") == trial_id:
                trials[i] = fin
                st.session_state.completed_trials = trials
                return
    trials.append(fin)
    st.session_state.completed_trials = trials


def _save_trials_csv() -> None:
    rows = st.session_state.completed_trials
    if not rows:
        return
    pd.DataFrame(rows).to_csv(SUMMARY_CSV, index=False)


def sync_message_counts() -> None:
    st.session_state.event_count = len(st.session_state.events)
    st.session_state.live_count = len(st.session_state.live_rows)
    st.session_state.final_count = len(st.session_state.completed_trials)


# ---------------------------------------------------------------------------
# Coaching notes
# ---------------------------------------------------------------------------
def generate_positive_notes(final: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    total = safe_int(final.get("total"))
    course = safe_int(final.get("course"))
    hover = safe_int(final.get("hover"))
    axis = safe_int(final.get("axis"))
    flow = safe_int(final.get("flow"))
    target = safe_int(final.get("target"))
    total_ms = safe_int(final.get("total_ms"))

    if course >= 28:
        notes.append("Course traversal was controlled.")
    if hover >= 24:
        notes.append("Stable hover was strong.")
    if axis >= 12:
        notes.append("Handle stayed well aligned.")
    if target >= 4:
        notes.append("Target coverage was consistent.")
    if flow >= 8 and FLOW_IDEAL_LO_S * 1000 <= total_ms <= FLOW_IDEAL_HI_S * 1000:
        notes.append("Timing was in the ideal range.")
    if total >= 80 and len(notes) < 2:
        notes.append("Strong complete run.")
    if not notes:
        notes.append("Completed trial — build on your strongest components.")
    return notes[:3]


def generate_improvement_notes(final: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    course = safe_int(final.get("course"))
    hover = safe_int(final.get("hover"))
    axis = safe_int(final.get("axis"))
    flow = safe_int(final.get("flow"))
    target = safe_int(final.get("target"))
    dock = safe_int(final.get("dock"))
    total_ms = safe_int(final.get("total_ms"))

    if course < 22:
        notes.append("Slow down around tube/poles and reduce abrupt rotations.")
    if hover < 20:
        notes.append("Hold the tool steadier once the target is covered.")
    if axis < 10:
        notes.append("Keep the handle closer to neutral through course and hover.")
    if flow < 7 and total_ms < 25000:
        notes.append("Trial was fast: slow slightly to improve control.")
    elif flow < 7 and total_ms > 45000:
        notes.append("Reduce pauses between course sections.")
    if target < 4:
        notes.append("Keep the APDS target consistently covered during hover.")
    if dock < 4:
        notes.append("Approach the red dock button more gently.")
    if not notes:
        notes.append("Solid trial — focus on the lowest component scores in the chart.")
    return notes[:3]


def classify_coach_cue(cue: str) -> str:
    c = (cue or "").lower()
    if any(w in c for w in ("lost", "jerky", "unstable", "rough", "harsh", "off-axis")):
        return "bad"
    if any(w in c for w in ("smooth", "stable", "active", "great", "good control", "controlled")):
        return "good"
    if any(w in c for w in ("fast", "hold", "level", "slow", "cover", "gentle")):
        return "warn"
    return "neutral"


def timing_interpretation(total_s: float) -> str:
    if total_s < FLOW_IDEAL_LO_S:
        return "Fast / rushed — aim for ~30 s total."
    if total_s <= FLOW_IDEAL_HI_S:
        return "Ideal timing (25–35 s band)."
    if total_s > 45:
        return "Slow / hesitant — reduce long pauses."
    return "Slightly outside ideal band — target ~30 s."


# ---------------------------------------------------------------------------
# Course diagram & connection
# ---------------------------------------------------------------------------
def course_step_status(state: str) -> list[str]:
    """Return CSS class per COURSE_STEPS: complete | current | future."""
    s = state.upper()
    n = len(COURSE_STEPS)
    statuses = ["phase-future"] * n
    if s == "IDLE":
        statuses[0] = "phase-current"
        return statuses
    if s == "APPROACH":
        statuses[0] = "phase-complete"
        statuses[1] = statuses[2] = "phase-current"
        return statuses
    if s == "HOVER":
        for i in range(4):
            statuses[i] = "phase-complete"
        statuses[3] = "phase-complete"
        statuses[4] = "phase-current"
        return statuses
    if s == "DOCK":
        for i in range(5):
            statuses[i] = "phase-complete"
        statuses[5] = "phase-current"
        return statuses
    if s == "COMPLETE":
        return ["phase-complete"] * n
    return statuses


def render_course_diagram(state: str) -> None:
    statuses = course_step_status(state)
    parts: list[str] = []
    for i, ((_, label, _), css) in enumerate(zip(COURSE_STEPS, statuses)):
        if i > 0:
            parts.append('<span class="course-arrow">&rarr;</span>')
        parts.append(f'<div class="course-step {css}">{label}</div>')
    st.markdown(f'<div class="course-map">{"".join(parts)}</div>', unsafe_allow_html=True)


_HAS_FRAGMENT = hasattr(st, "fragment")
_POLL_INTERVAL = timedelta(seconds=POLL_FRAGMENT_SEC)


def connection_health_label() -> tuple[str, str]:
    if not st.session_state.get("connected"):
        return "Disconnected", "conn-off"
    last = st.session_state.get("last_data_ts")
    if last is None or (time.time() - float(last)) > DATA_QUIET_SEC:
        return "Connected — quiet", "conn-warn"
    return "Receiving data", "conn-ok"


def render_connection_status() -> None:
    label, css = connection_health_label()
    port = st.session_state.get("serial_port") or "—"
    st.markdown(f"**Status:** <span class='{css}'>{label}</span>", unsafe_allow_html=True)
    st.caption(f"Port: `{port}` · {BAUD} baud")
    if st.session_state.get("last_serial_error"):
        st.warning(st.session_state.last_serial_error)
    c1, c2, c3 = st.columns(3)
    c1.metric("Events", st.session_state.event_count)
    c2.metric("LIVE", st.session_state.live_count)
    c3.metric("Finals", st.session_state.final_count)
    if st.session_state.get("last_parse_error"):
        st.caption(f"Last parse error: {st.session_state.last_parse_error}")
    st.caption(f"Parse errors: {st.session_state.parse_error_count}")


def list_serial_ports() -> list[str]:
    return sorted({p.device for p in serial.tools.list_ports.comports()})


def connect_serial(port: str) -> bool:
    disconnect_serial()
    try:
        ser = serial.Serial(port, BAUD, timeout=0)
        st.session_state.serial_conn = ser
        st.session_state.serial_port = port
        st.session_state.connected = True
        st.session_state.last_serial_error = ""
        return True
    except Exception as exc:  # noqa: BLE001
        st.session_state.last_serial_error = str(exc)
        st.session_state.connected = False
        st.session_state.serial_conn = None
        return False


def disconnect_serial() -> None:
    ser = st.session_state.get("serial_conn")
    if ser is not None:
        try:
            if getattr(ser, "is_open", False):
                ser.close()
        except Exception:  # noqa: BLE001
            pass
    st.session_state.serial_conn = None
    st.session_state.connected = False


def send_serial_command(cmd: str) -> None:
    ser = st.session_state.get("serial_conn")
    if not ser or not st.session_state.get("connected"):
        st.session_state.last_serial_error = "Not connected"
        return
    try:
        ser.write(cmd.encode("ascii"))
        ser.flush()
    except Exception as exc:  # noqa: BLE001
        st.session_state.last_serial_error = str(exc)


def _read_serial_nonblocking() -> None:
    ser = st.session_state.get("serial_conn")
    if not ser or not st.session_state.get("connected"):
        return
    try:
        while ser.in_waiting > 0:
            raw = ser.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="ignore").strip()
            if line:
                st.session_state.last_line = line[:120]
                st.session_state.lines_received = int(st.session_state.get("lines_received", 0)) + 1
                ingest_line(line)
    except Exception as exc:  # noqa: BLE001
        st.session_state.last_serial_error = str(exc)
        disconnect_serial()


def run_demo_trial() -> None:
    now = time.time()
    if st.session_state.get("demo_running") and st.session_state.current_state == "COMPLETE":
        if now - float(st.session_state.demo_phase_ts) > 4.0:
            st.session_state.demo_running = False
            st.session_state.demo_phase = 0
        return
    if not st.session_state.get("demo_running"):
        st.session_state.demo_running = True
        st.session_state.demo_phase = 0
        st.session_state.demo_phase_ts = now
        tid = safe_int(st.session_state.current_trial, 0) + 1
        st.session_state.current_trial = tid
    phase = int(st.session_state.demo_phase)
    elapsed = now - float(st.session_state.demo_phase_ts)
    tid = safe_int(st.session_state.current_trial, 1)
    if phase == 0 and elapsed >= 0.4:
        ingest_line(f"EVENT,trial={tid},t_ms=0,state=APPROACH,event=TRIAL_START,score=12")
        st.session_state.demo_phase = 1
        st.session_state.demo_phase_ts = now
    elif phase == 1 and elapsed >= 1.2:
        ingest_line(f"LIVE,trial={tid},state=APPROACH,score=38,issue=Move smoothly through course,gyro_rms=95.0,jerk_rms=620,spike_rate=0.8")
        st.session_state.demo_phase = 2
        st.session_state.demo_phase_ts = now
    elif phase == 2 and elapsed >= 1.0:
        ingest_line(f"EVENT,trial={tid},t_ms=5200,state=HOVER,event=HOVER_ENTER,score=52")
        st.session_state.demo_phase = 3
        st.session_state.demo_phase_ts = now
    elif phase == 3:
        prog = min(1.0, elapsed / 2.5)
        hms = int(HOVER_TARGET_MS_DEFAULT * prog)
        ingest_line(
            f"LIVE,trial={tid},state=HOVER,score={52 + int(20 * prog)},issue=Hold steady over target,"
            f"hover={hms}/{HOVER_TARGET_MS_DEFAULT},stable=1,occ=1"
        )
        if elapsed >= 2.6:
            ingest_line(f"EVENT,trial={tid},t_ms=9000,state=DOCK,event=HOVER_COMPLETE,score=72")
            st.session_state.demo_phase = 4
            st.session_state.demo_phase_ts = now
    elif phase == 4 and elapsed >= 1.0:
        ingest_line(f"LIVE,trial={tid},state=DOCK,score=78,issue=Press RED dock gently,dock_ms=900")
        st.session_state.demo_phase = 5
        st.session_state.demo_phase_ts = now
    elif phase == 5 and elapsed >= 0.8:
        ingest_line(
            f"FINAL_SCORE,trial={tid},total=84,course=30,hover=26,axis=13,flow=9,target=4,dock=2,"
            f"feedback=Great control,total_ms=30500,approach_ms=21000,hover_ms=7200,dock_ms=2300,"
            f"course_gyro_rms=180.0,course_jerk_rms=1400.0,course_spike_rate=2.5,tilt_rms=8.0,"
            f"tilt_max=15.0,tilt_over_limit_ms=0,hover_stable_pct=82.0,hover_occluded_pct=95.0,"
            f"dock_jerk_peak=4200,hover_resets=0,occlusion_losses=0"
        )
        ingest_line(f"EVENT,trial={tid},t_ms=30500,state=COMPLETE,event=DOCK_COMPLETE,score=84")
        st.session_state.demo_phase = 6
        st.session_state.demo_phase_ts = now


def _poll_serial_core() -> None:
    n_before = int(st.session_state.get("lines_received", 0))
    if st.session_state.get("demo_mode") and not st.session_state.get("connected"):
        run_demo_trial()
    else:
        _read_serial_nonblocking()
    st.session_state.last_poll_lines = int(st.session_state.get("lines_received", 0)) - n_before
    st.session_state.last_poll_time = datetime.now().strftime("%H:%M:%S")
    st.session_state.poll_tick = int(st.session_state.get("poll_tick", 0)) + 1
    sync_message_counts()


def init_session_state() -> None:
    defaults: dict[str, Any] = {
        "serial_port": None,
        "serial_conn": None,
        "connected": False,
        "last_serial_error": "",
        "raw_lines": [],
        "events": [],
        "live_rows": [],
        "completed_trials": [],
        "latest_event": None,
        "latest_live": None,
        "latest_final": None,
        "current_state": "IDLE",
        "current_trial": 0,
        "live_score": 0,
        "current_feedback": "",
        "prev_score": 0,
        "prev_feedback": "",
        "thresholds": {},
        "calibration": {},
        "threshold_buffer": [],
        "event_count": 0,
        "live_count": 0,
        "final_count": 0,
        "demo_mode": False,
        "parse_error_count": 0,
        "last_data_ts": None,
        "last_parse_error": "",
        "demo_running": False,
        "demo_phase": 0,
        "demo_phase_ts": 0.0,
        "show_radar_review": False,
        "lines_received": 0,
        "last_poll_lines": 0,
        "last_poll_time": "—",
        "last_line": "—",
        "poll_tick": 0,
        "polling_mode": "fragment" if _HAS_FRAGMENT else "fallback",
        "last_rerun_ts": 0.0,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val
    if not st.session_state.completed_trials and SUMMARY_CSV.exists():
        try:
            st.session_state.completed_trials = pd.read_csv(SUMMARY_CSV).to_dict("records")
        except Exception:  # noqa: BLE001
            pass
    sync_message_counts()


def render_sidebar_diagnostics() -> None:
    render_connection_status()
    st.markdown("### Polling")
    st.caption(f"Mode: **{st.session_state.polling_mode}**")
    st.caption(f"Last poll: {st.session_state.last_poll_time}")
    st.caption(f"Lines this poll: {st.session_state.last_poll_lines}")
    st.caption(f"Total lines: {st.session_state.lines_received}")
    st.caption(f"Poll ticks: {st.session_state.poll_tick}")
    last = st.session_state.get("last_line", "—")
    if last and last != "—":
        st.caption(f"Last line: {last[:72]}…" if len(str(last)) > 72 else f"Last line: {last}")
    b1, b2 = st.columns(2)
    if b1.button("Poll now", key="btn_poll_now", use_container_width=True):
        _poll_serial_core()
    if b2.button("Force rerun", key="btn_force_rerun", use_container_width=True):
        st.rerun()
    th = st.session_state.thresholds
    if th:
        st.caption(
            "Thresholds loaded"
            + (" (calibration active)" if safe_get(th, "calibration_active") else "")
        )


def _metric_html(label: str, value: str) -> str:
    return (
        f'<div class="metric-card"><div class="label">{label}</div>'
        f'<div class="value">{value}</div></div>'
    )


def motion_control_status(live: dict[str, Any]) -> tuple[str, str, str]:
    issue = str(safe_get(live, "issue", st.session_state.current_feedback) or "")
    gyro = safe_float(safe_get(live, "gyro_rms"))
    jerk = safe_float(safe_get(live, "jerk_rms"))
    low = issue.lower()
    if any(w in low for w in ("jerky", "rough", "spike")):
        return "Too jerky", "bad", f"gyro {gyro:.0f} · jerk {jerk:.0f}" if gyro or jerk else issue
    if gyro > 150 or jerk > 2000:
        return "Rough", "warn", f"gyro {gyro:.0f} · jerk {jerk:.0f}"
    if gyro or jerk:
        return "Smooth", "good", f"gyro {gyro:.0f} · jerk {jerk:.0f}"
    return "Waiting for LIVE", "neutral", issue or "—"


def hover_stability_status(live: dict[str, Any]) -> tuple[str, str, str]:
    stable = safe_get(live, "stable")
    h_ms = safe_int(safe_get(live, "hover_ms"))
    h_tgt = safe_int(safe_get(live, "hover_target_ms"), HOVER_TARGET_MS_DEFAULT)
    if stable is not None:
        label = "Stable" if int(stable) else "Hold still"
        tone = "good" if int(stable) else "warn"
        detail = f"{h_ms/1000:.1f} / {h_tgt/1000:.1f} s" if h_ms else "—"
        return label, tone, detail
    return "Waiting for LIVE", "neutral", "hover progress from firmware"


def axis_tilt_status(live: dict[str, Any]) -> tuple[str, str, str]:
    tilt = safe_get(live, "tilt")
    if tilt is not None:
        t = safe_float(tilt)
        if t > 25:
            return "Level handle", "warn", f"{t:.1f}°"
        return "Axis OK", "good", f"{t:.1f}°"
    fin = st.session_state.latest_final
    if fin and safe_get(fin, "tilt_rms") is not None:
        return "Axis OK", "good", f"tilt RMS {safe_float(fin.get('tilt_rms')):.1f}°"
    return "—", "neutral", "tilt from LIVE or final score"


def target_lock_status(live: dict[str, Any]) -> tuple[str, str, str]:
    occ = safe_get(live, "occ", safe_get(live, "occluded"))
    if occ is not None:
        active = int(occ) == 1
        return ("Target active" if active else "Target lost", "good" if active else "bad", "APDS covered")
    fin = st.session_state.latest_final
    if fin and safe_get(fin, "hover_occluded_pct") is not None:
        pct = safe_float(fin.get("hover_occluded_pct"))
        return ("Target active" if pct >= 80 else "Target lost", "good" if pct >= 80 else "warn", f"{pct:.0f}% hover cover")
    return "—", "neutral", "occlusion from LIVE"


def render_skill_meters() -> None:
    live = st.session_state.latest_live or {}
    cards = [
        ("Motion Control", motion_control_status(live)),
        ("Hover Stability", hover_stability_status(live)),
        ("Axis / Tilt", axis_tilt_status(live)),
        ("Target Lock", target_lock_status(live)),
    ]
    cols = st.columns(4)
    for col, (title, (label, tone, detail)) in zip(cols, cards):
        with col:
            st.markdown(
                f'<div class="skill-card"><h4>{title}</h4>'
                f'<p class="coach-{tone}" style="font-weight:700;margin:0">{label}</p>'
                f'<p style="font-size:0.8rem;opacity:0.8">{detail}</p></div>',
                unsafe_allow_html=True,
            )


def component_bar_figure(final: dict[str, Any], horizontal_pct: bool = True) -> go.Figure:
    labels, pcts, scores, maxes, colors = [], [], [], [], []
    for key, label, mx in COMPONENT_LABELS:
        s = safe_int(safe_get(final, key))
        pct = 100.0 * s / mx if mx else 0
        labels.append(f"{label} ({s}/{mx})")
        pcts.append(pct)
        scores.append(s)
        maxes.append(mx)
        colors.append(COMPONENT_COLORS[key])
    if horizontal_pct:
        fig = go.Figure(
            go.Bar(
                y=labels,
                x=pcts,
                orientation="h",
                marker_color=colors,
                text=[f"{p:.0f}%" for p in pcts],
                textposition="outside",
            )
        )
        fig.update_layout(
            title="Component scores (% of max)",
            xaxis=dict(range=[0, 105], title="%"),
            height=340,
            margin=dict(l=10, r=60, t=40, b=10),
        )
        return fig
    fig = go.Figure(
        go.Bar(
            x=[lbl.split(" (")[0] for lbl in labels],
            y=scores,
            marker_color=colors,
            text=[f"{s}/{m}" for s, m in zip(scores, maxes)],
            textposition="outside",
        )
    )
    fig.update_layout(yaxis_title="Points", yaxis_range=[0, max(maxes) + 5], height=360)
    return fig


def build_event_timeline(trial_id: Any) -> list[dict[str, Any]]:
    rows = [e for e in st.session_state.events if safe_get(e, "trial") == trial_id]
    if not rows:
        return []
    rows.sort(key=lambda e: safe_int(safe_get(e, "t_ms")))
    t0 = safe_int(safe_get(rows[0], "t_ms"))
    out: list[dict[str, Any]] = []
    for e in rows:
        t_ms = safe_int(safe_get(e, "t_ms"))
        out.append(
            {
                "relative_s": round((t_ms - t0) / 1000.0, 1),
                "event": safe_get(e, "event", "—"),
                "state": safe_get(e, "state", "—"),
            }
        )
    return out


def component_radar_figure(final: dict[str, Any]) -> go.Figure:
    labels = [lbl for _, lbl, _ in COMPONENT_LABELS]
    vals = [
        100.0 * safe_int(safe_get(final, k)) / mx if mx else 0
        for k, _, mx in COMPONENT_LABELS
    ]
    vals.append(vals[0])
    labels.append(labels[0])
    fig = go.Figure(
        data=go.Scatterpolar(r=vals, theta=labels, fill="toself", name="Trial")
    )
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 100])),
        height=380,
        margin=dict(t=40, b=40),
    )
    return fig


def phase_timing_figure(final: dict[str, Any]) -> go.Figure:
    approach = safe_int(safe_get(final, "approach_ms")) / 1000.0
    hover_t = safe_int(safe_get(final, "hover_ms")) / 1000.0
    dock_t = safe_int(safe_get(final, "dock_ms")) / 1000.0
    total_t = safe_int(safe_get(final, "total_ms")) / 1000.0
    fig = go.Figure(
        go.Bar(
            x=["Approach", "Hover", "Dock", "Total"],
            y=[approach, hover_t, dock_t, total_t],
            marker_color=["#3498db", "#2ecc71", "#e74c3c", "#9b59b6"],
        )
    )
    fig.add_hrect(
        y0=FLOW_IDEAL_LO_S,
        y1=FLOW_IDEAL_HI_S,
        annotation_text="Ideal total (25–35 s)",
        line_width=0,
        fillcolor="rgba(46, 204, 113, 0.12)",
    )
    fig.update_layout(yaxis_title="Seconds", height=300, margin=dict(t=30, b=40))
    return fig


def trials_dataframe() -> pd.DataFrame:
    rows = st.session_state.completed_trials
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def export_trial_bytes(final: dict[str, Any], fmt: str) -> bytes:
    if fmt == "csv":
        return pd.DataFrame([final]).to_csv(index=False).encode("utf-8")
    if fmt == "json":
        return json.dumps(final, indent=2).encode("utf-8")
    pos = generate_positive_notes(final)
    imp = generate_improvement_notes(final)
    total_s = safe_int(safe_get(final, "total_ms")) / 1000.0
    md = (
        f"# Trial {safe_get(final, 'trial')} — {safe_get(final, 'feedback')}\n\n"
        f"**Total score:** {safe_get(final, 'total')} / 100\n\n"
        f"**Timing:** {total_s:.1f} s — {timing_interpretation(total_s)}\n\n"
        "## Strengths\n"
        + "\n".join(f"- {n}" for n in pos)
        + "\n\n## Improvements\n"
        + "\n".join(f"- {n}" for n in imp)
        + "\n"
    )
    return md.encode("utf-8")


def render_live_coach_tab() -> None:
    state = str(st.session_state.current_state).upper()
    trial = safe_int(st.session_state.current_trial)
    score = safe_int(st.session_state.live_score)
    cue = st.session_state.current_feedback or "Connect hardware or enable demo mode."
    cue_class = classify_coach_cue(cue)
    trial_lbl = str(trial) if trial else "—"
    st.markdown(
        f'<div class="hero-card"><h1>MYOSA Laparoscopic Trainer</h1><p class="sub">'
        f"Live Coach · Trial {trial_lbl}</p></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="status-banner">{STATUS_BANNERS.get(state, "Follow on-screen cues")}</div>',
        unsafe_allow_html=True,
    )
    render_course_diagram(state)
    live = st.session_state.latest_live or {}
    t_ms = safe_int(safe_get(live, "t_ms") or safe_get(st.session_state.latest_event, "t_ms"))
    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(_metric_html("Score", str(score)), unsafe_allow_html=True)
    with m2:
        st.markdown(
            _metric_html("State", f'<span class="state-badge">{state}</span>'),
            unsafe_allow_html=True,
        )
    with m3:
        st.markdown(_metric_html("Elapsed", f"{t_ms / 1000:.1f}s" if t_ms else "—"), unsafe_allow_html=True)
    st.markdown(
        f'<div class="coach-card coach-{cue_class}">{cue}</div>',
        unsafe_allow_html=True,
    )
    render_skill_meters()
    if state == "HOVER":
        h_ms = safe_int(safe_get(live, "hover_ms"))
        h_tgt = safe_int(safe_get(live, "hover_target_ms"), HOVER_TARGET_MS_DEFAULT)
        raw_hover = str(safe_get(live, "hover", ""))
        if not h_ms and "/" in raw_hover:
            a, b = raw_hover.split("/", 1)
            h_ms = safe_int(a)
            h_tgt = safe_int(b, HOVER_TARGET_MS_DEFAULT)
        if h_ms and h_tgt:
            prog = min(1.0, h_ms / h_tgt)
            st.subheader("Hover dwell")
            st.progress(prog, text=f"{h_ms / 1000:.1f} / {h_tgt / 1000:.1f} s stable hover")
            t1, t2 = st.columns(2)
            occ = safe_get(live, "occ", safe_get(live, "occluded"))
            stable = safe_get(live, "stable")
            if occ is not None:
                t1.metric("Target lock", "Active" if int(occ) else "Lost")
            if stable is not None:
                t2.metric("Stability", "Stable" if int(stable) else "Hold still")
        else:
            st.info("Hovering: waiting for firmware LIVE hover progress data.")


def render_trial_review_tab() -> None:
    st.header("Trial Review")
    trials = st.session_state.completed_trials
    if not trials:
        st.info("Complete a trial to see the after-action report (GREEN START, then RED dock).")
        return
    pick = st.selectbox(
        "Trial",
        range(len(trials)),
        format_func=lambda i: (
            f"Trial {safe_get(trials[i], 'trial', i + 1)} - "
            f"{safe_get(trials[i], 'feedback', '')} ({safe_get(trials[i], 'total', 0)})"
        ),
    )
    final = trials[pick]
    total = safe_int(safe_get(final, "total"))
    st.markdown(
        f'<p class="report-score">{total}<span style="font-size:1rem"> / 100</span></p>',
        unsafe_allow_html=True,
    )
    st.caption(f"Feedback: **{safe_get(final, 'feedback', '—')}**")
    total_s = safe_int(safe_get(final, "total_ms")) / 1000.0
    st.write(timing_interpretation(total_s))
    st.plotly_chart(component_bar_figure(final), use_container_width=True)
    st.session_state.show_radar_review = st.checkbox(
        "Show radar chart", value=bool(st.session_state.show_radar_review)
    )
    if st.session_state.show_radar_review:
        st.plotly_chart(component_radar_figure(final), use_container_width=True)
    st.subheader("Phase timing")
    st.plotly_chart(phase_timing_figure(final), use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("What went well")
        for note in generate_positive_notes(final):
            st.success(note)
    with c2:
        st.subheader("Focus next")
        for note in generate_improvement_notes(final):
            st.warning(note)
    tid = safe_get(final, "trial")
    timeline = build_event_timeline(tid)
    if timeline:
        st.subheader("Event timeline")
        for row in timeline:
            st.markdown(f"- **+{row['relative_s']}s** — `{row['event']}` ({row['state']})")
    st.subheader("Export")
    base = f"trial_{tid}"
    e1, e2, e3 = st.columns(3)
    e1.download_button("CSV", export_trial_bytes(final, "csv"), f"{base}.csv", "text/csv")
    e2.download_button("JSON", export_trial_bytes(final, "json"), f"{base}.json", "application/json")
    e3.download_button("Markdown", export_trial_bytes(final, "md"), f"{base}.md", "text/markdown")


def render_history_tab() -> None:
    st.header("History")
    df = trials_dataframe()
    if df.empty:
        st.info("No completed trials yet.")
        return
    totals = df["total"].astype(int) if "total" in df.columns else pd.Series(dtype=int)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trials", len(df))
    c2.metric("Best score", int(totals.max()))
    c3.metric("Latest", int(totals.iloc[-1]))
    c4.metric("Average", f"{totals.mean():.1f}")
    if "trial" in df.columns and "total" in df.columns:
        fig = go.Figure(data=go.Scatter(x=df["trial"], y=df["total"], mode="lines+markers"))
        fig.update_layout(title="Score by trial", xaxis_title="Trial", yaxis_title="Total", height=320)
        st.plotly_chart(fig, use_container_width=True)
    comp_cols = [c[0] for c in COMPONENT_LABELS if c[0] in df.columns]
    if comp_cols and "trial" in df.columns:
        st.subheader("Component trends")
        st.line_chart(df.set_index("trial")[comp_cols], height=260)
    if "total_ms" in df.columns and "trial" in df.columns:
        tdf = df.copy()
        tdf["total_s"] = tdf["total_ms"] / 1000
        tfig = go.Figure(go.Scatter(x=tdf["trial"], y=tdf["total_s"], mode="lines+markers"))
        tfig.add_hrect(y0=25, y1=35, fillcolor="rgba(46,204,113,0.15)", line_width=0)
        tfig.update_layout(title="Total time trend", yaxis_title="Seconds", height=280)
        st.plotly_chart(tfig, use_container_width=True)
    if "feedback" in df.columns:
        st.subheader("Feedback frequency")
        freq = df["feedback"].value_counts().reset_index()
        freq.columns = ["feedback", "count"]
        st.plotly_chart(
            go.Figure(data=[go.Bar(x=freq["feedback"], y=freq["count"])]),
            use_container_width=True,
        )
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button(
        "Download all trials CSV",
        df.to_csv(index=False).encode("utf-8"),
        "trials_export.csv",
        "text/csv",
    )


def render_calibration_tab() -> None:
    st.header("Calibration / Tuning")
    st.warning("Close PlatformIO serial monitor before connecting. Only one app can own the COM port.")
    st.caption("For live demos, prefer **GREEN START** and **RED END / RETURN** on the trainer.")
    cmds = [
        ("z", "APDS baseline"),
        ("c", "Calibrate from last trial"),
        ("C", "Clear scoring calibration"),
        ("q", "Print thresholds"),
        ("p", "Print score breakdown"),
        ("x", "Toggle raw CSV"),
    ]
    cols = st.columns(3)
    for i, (ch, label) in enumerate(cmds):
        if cols[i % 3].button(label, key=f"cal_{ch}"):
            send_serial_command(ch)
            st.toast(f"Sent '{ch}'")
    cal = st.session_state.calibration
    if safe_get(cal, "type") == "CAL_SET":
        st.success("Last CAL_SET received")
        st.json({k: v for k, v in cal.items() if k != "type"})
    th = st.session_state.thresholds
    if th:
        st.subheader("Thresholds (from q)")
        st.write(f"Calibration active: **{safe_get(th, 'calibration_active', False)}**")


def reset_demo_trial() -> None:
    st.session_state.demo_running = False
    st.session_state.demo_phase = 0
    st.session_state.current_state = "IDLE"
    st.session_state.current_feedback = "Demo ready — press Run demo trial"
    st.session_state.live_score = 0


def render_debug_tab() -> None:
    st.header("Debug")
    st.write(f"Parse errors: **{st.session_state.parse_error_count}**")
    lines = list(st.session_state.raw_lines)[-RAW_LOG_MAX:]
    st.text_area("Raw serial log (last 200 lines)", "\n".join(lines), height=220)
    if st.session_state.events:
        st.subheader("Events")
        st.dataframe(pd.DataFrame(st.session_state.events), use_container_width=True, hide_index=True)
    if st.session_state.live_rows:
        st.subheader("LIVE rows")
        st.dataframe(pd.DataFrame(st.session_state.live_rows), use_container_width=True, hide_index=True)
    if st.session_state.completed_trials:
        st.subheader("FINAL_SCORE rows")
        st.dataframe(pd.DataFrame(st.session_state.completed_trials), use_container_width=True, hide_index=True)
    st.subheader("Serial commands")
    cmds = [
        ("z", "Baseline (z)"),
        ("p", "Print score (p)"),
        ("q", "Thresholds (q)"),
        ("c", "Calibrate (c)"),
        ("C", "Clear cal (C)"),
        ("x", "Raw CSV (x)"),
        ("r", "Reset (r)"),
        ("s", "Start (s)"),
        ("d", "Dock sim (d)"),
    ]
    cols = st.columns(3)
    for i, (ch, label) in enumerate(cmds):
        if cols[i % 3].button(label, key=f"dbg_{ch}"):
            send_serial_command(ch)


if _HAS_FRAGMENT:

    @st.fragment(run_every=_POLL_INTERVAL)
    def run_sidebar_poll_fragment() -> None:
        _poll_serial_core()
        render_sidebar_diagnostics()

    @st.fragment(run_every=_POLL_INTERVAL)
    def live_coach_panel_fragment() -> None:
        render_live_coach_tab()

    @st.fragment(run_every=_POLL_INTERVAL)
    def trial_review_panel_fragment() -> None:
        render_trial_review_tab()

    @st.fragment(run_every=_POLL_INTERVAL)
    def history_panel_fragment() -> None:
        render_history_tab()

    @st.fragment(run_every=_POLL_INTERVAL)
    def debug_panel_fragment() -> None:
        render_debug_tab()

else:

    def run_sidebar_poll_fragment() -> None:
        _poll_serial_core()
        render_sidebar_diagnostics()

    def live_coach_panel_fragment() -> None:
        render_live_coach_tab()

    def trial_review_panel_fragment() -> None:
        render_trial_review_tab()

    def history_panel_fragment() -> None:
        render_history_tab()

    def debug_panel_fragment() -> None:
        render_debug_tab()


def _fallback_autorerun() -> None:
    if not st.session_state.get("connected"):
        return
    now = time.time()
    if now - float(st.session_state.get("last_rerun_ts", 0)) >= POLL_FRAGMENT_SEC:
        st.session_state.last_rerun_ts = now
        _poll_serial_core()
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="MYOSA Lap Trainer",
        page_icon="🩺",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_session_state()
    inject_custom_css()

    with st.sidebar:
        st.header("Connection")
        ports = list_serial_ports()
        if not ports:
            st.warning("No COM ports detected.")
        idx = 0
        if ports and st.session_state.serial_port in ports:
            idx = ports.index(st.session_state.serial_port)
        port = st.selectbox("COM port", ports or ["—"], index=idx if ports else 0)
        c1, c2 = st.columns(2)
        if c1.button("Connect", disabled=not ports or port == "—"):
            if connect_serial(port):
                st.success(f"Connected to {port}")
            else:
                st.error(st.session_state.last_serial_error)
        if c2.button("Disconnect"):
            disconnect_serial()
            st.info("Disconnected")
        st.session_state.demo_mode = st.toggle(
            "Demo mode (no hardware)",
            value=bool(st.session_state.demo_mode),
            help="Simulates EVENT/LIVE/FINAL_SCORE when not connected",
        )
        if st.session_state.demo_mode and not st.session_state.connected:
            if st.button("Run demo trial", use_container_width=True):
                reset_demo_trial()
                st.session_state.demo_running = True
                st.rerun()
        if st.button("Reset session data"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            init_session_state()
            st.rerun()
        run_sidebar_poll_fragment()

    tab_live, tab_review, tab_hist, tab_cal, tab_dbg = st.tabs(
        ["Live Coach", "Trial Review", "History", "Calibration / Tuning", "Debug"]
    )
    with tab_live:
        live_coach_panel_fragment()
    with tab_review:
        trial_review_panel_fragment()
    with tab_hist:
        history_panel_fragment()
    with tab_cal:
        render_calibration_tab()
    with tab_dbg:
        debug_panel_fragment()

    if not _HAS_FRAGMENT:
        _fallback_autorerun()


if __name__ == "__main__":
    main()

