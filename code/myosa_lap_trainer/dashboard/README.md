# MYOSA Laparoscopic Trainer — Streamlit Dashboard

Product-style local dashboard for the IEEE MYOSA lap trainer. Connects to the ESP32 over USB serial (115200 baud). **Close PlatformIO serial monitor** before connecting — only one program can own the COM port.

## Install

```powershell
cd C:\SanciaMJW\projects\MYOSA\myosa_lap_trainer
pip install -r dashboard/requirements.txt
```

## Run

```powershell
streamlit run dashboard/app.py
```

Opens in the browser (usually http://localhost:8501).

## Connect

1. Upload firmware if needed (`pio run -t upload`).
2. Sidebar: select **COM port** → **Connect**.
3. Status should show **Receiving data** after `EVENT` / `LIVE` / `FINAL_SCORE` lines arrive.
4. Sidebar **Polling** shows last poll time and line counts (~0.4 s auto-poll).

## Physical controls

| Control | Action |
|--------|--------|
| **GREEN START** | Start trial from IDLE or COMPLETE |
| **RED END** | Complete dock in DOCK |
| **RED RETURN** | Return to IDLE from COMPLETE |

Prefer these buttons for live demos. Serial commands are available under **Calibration / Tuning** and **Debug**.

## Tabs

### Live Coach

Main training screen: course phase map (GREEN START → Tube → Poles → Target → Hover → RED Dock → Complete), large state/score/cue, four live skill meters (when `LIVE` lines are present), and prominent hover dwell progress in HOVER.

Works with **EVENT-only** firmware (state/score from events); **LIVE** unlocks meters and hover progress.

### Trial Review

After-action report: final score, feedback, horizontal component chart (% of max), optional radar chart, phase timing vs 25–35 s ideal band, “what went well” / “focus next”, event timeline, CSV/JSON/Markdown export.

### History

Best / latest / average scores, score and component trends, timing trend with ideal band, feedback frequency chart, full trials table, CSV download.

### Calibration / Tuning

Send `z`, `c`, `C`, `q`, `p`, `x` to firmware when connected.

### Debug

Last 200 raw serial lines, parsed EVENT/LIVE/FINAL tables, parse error count, manual commands (`z`, `p`, `q`, `c`, `C`, `x`, `r`, `s`, `d`).

## Demo mode

Sidebar **Demo mode (no hardware)** simulates a full trial when not connected. Click **Run demo trial** to play through APPROACH → HOVER → DOCK → COMPLETE with sample scores. Does not interfere with a real serial connection.

## Scoring components (total /100)

Course /35 · Hover /30 · Axis /15 · Flow /10 · Target /5 · Dock /5

## Data files

Completed trials: `dashboard/data/summary/trials.csv` (auto-saved on each `FINAL_SCORE`; duplicate trial IDs are updated, not duplicated).

## Troubleshooting

| Problem | Fix |
|--------|-----|
| Permission denied on COM | Close PlatformIO monitor, Arduino serial, other tools |
| Connected but quiet (>5 s) | Wrong port; reset board; press GREEN START |
| Garbled text | Confirm 115200 baud; try another USB cable/port |
| UI frozen on one tab | Restart Streamlit; check sidebar **Poll ticks** increasing |
| Raw lines but no UI update | Ensure **Mode: fragment** or fallback rerun; use **Poll now** |
| Demo works, hardware does not | Connect correct COM; firmware must print EVENT/LIVE/FINAL_SCORE |

## Offline use

No cloud required after Python packages are installed.
