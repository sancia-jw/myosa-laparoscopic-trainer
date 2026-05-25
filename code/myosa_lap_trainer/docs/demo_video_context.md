# MYOSA Laparoscopic Trainer — Demo Video & Presentation Context

**Purpose:** Paste this document into ChatGPT (or similar) to draft a demo video script, narration, judge Q&A, and slide explanations.  
**Source of truth:** Inspected `src/main.cpp`, `dashboard/app.py`, `dashboard/README.md`, `dashboard/requirements.txt`, `platformio.ini`, and `cursor_myosa_laparoscopic_trainer_build_spec.md` (May 2026).  
**Note:** Root `README.md` still describes older **proximity-based** hover logic; **current firmware uses APDS clear-channel occlusion**. Prefer this document and `src/main.cpp` over the root README for demo accuracy.

---

## 1. Project identity (IEEE MYOSA)

**Title (working):** Precision in Practice — MYOSA Laparoscopic Trainer  

**One-line pitch:** A modular MYOSA sensor stack turns a physical laparoscopic skills course into **objective, real-time coaching** — motion quality, target-zone control, timing, and docking — shown on-device (OLED) and on a laptop dashboard.

**What this is not:** A generic Arduino game or a position-tracking surgical robot. The course geometry (tube, poles, target, dock button) constrains the path; **electronics score how well** the user moves through that path.

**Competition framing:**
- Multiple MYOSA modules on one I2C chain (IMU, APDS, OLED) + ESP32 motherboard
- Real-time sensor fusion and phase-based scoring
- Engaging physical demo + polished local dashboard
- Biomedical / surgical skills training relevance
- Expandable (more checkpoints, users, analytics later)

---

## 2. Physical trainer (what the audience sees)

### Course layout (user path)

1. **GREEN START** — user presses green button to begin (from IDLE or after a completed trial).
2. **Tube / trocar entry** — laparoscopic-style tool enters a flat tube opening.
3. **Poles** — tool navigates over/under green pole obstacles (course segment).
4. **Purple APDS target** — tool moves to the purple target zone on the base; sensor detects **light occlusion** when the tool covers the target.
5. **Hover** — user holds steady over the target for a required dwell time.
6. **RED dock** — user presses the red button on the back board to complete docking.
7. **COMPLETE** — final score; **RED RETURN** (same red button) returns to IDLE for the next trial.

### Hardware on the rig

| Item | Role in project |
|------|-----------------|
| **MYOSA motherboard** | ESP32-based controller; USB serial to laptop; I2C bus for sensors/OLED |
| **MPU6050 IMU** (MYOSA AccelAndGyro lib) | Tool/handle motion: accel + gyro → smoothness, spikes, tilt |
| **APDS9960** (MYOSA LightProximityAndGesture lib) | **Ambient clear channel** for target-zone presence (not primary proximity mode) |
| **OLED** (SSD1306, MYOSA OLED lib) | Local state, score, hover progress, short feedback text |
| **GREEN START button** | GPIO **D4** (pin 4 if `D4` macro undefined) |
| **RED END / DOCK / RETURN button** | GPIO **D16** (pin 16 if `D16` macro undefined) |
| **Status LED** | GPIO **2** — ON after dock complete |
| **USB cable** | Power + serial @ **115200 baud** |
| **3D-printed handle/tool** | Carries or mounts IMU; user-facing lap trainer interface |
| **Physical course** | Tube, green poles, purple APDS target area, red dock button |

**TODO / VERIFY:** Optional buzzer is mentioned in root `README.md` but **not referenced in current `src/main.cpp`**. Do not demo buzzer unless hardware/firmware is added.

**TODO / VERIFY:** Exact OLED I2C address on your stack (library typically **0x3C**; confirm on board).

### I2C addresses (from MYOSA libraries)

| Device | Address (library default) |
|--------|---------------------------|
| MPU6050 | **0x69** (`AccelAndGyro`; AD0 high) |
| APDS9960 | **0x39** |
| OLED | **0x3C** (typical; verify on hardware) |

I2C clock in firmware `setup()`: **100 kHz** (`Wire.setClock(100000)`).

---

## 3. APDS design decision (critical talking point)

### What was tried first

Early MVP thinking (see `cursor_myosa_laparoscopic_trainer_build_spec.md`) used **APDS9960 proximity (IR reflection)** for “near target.” In practice, proximity was **weak or unreliable** for this mechanical setup.

### What the project uses now

**Ambient light — clear channel occlusion:**

- Firmware enables **ambient light sensor**; **disables proximity and gesture** (`initApds()`).
- Reads **clear + RGB** via burst I2C read (`readRgbClearBurst`).
- With a **baseline** captured while the target zone is **open** (`z` command / boot baseline attempt), **occlusion %** = how much the clear channel drops when the tool blocks light over the purple target.
- **Hysteresis** avoids flicker at the threshold edge:
  - **Enter occlusion:** `g_occlusion_enter_pct` default **15.0%**
  - **Exit occlusion:** `g_occlusion_exit_pct` default **8.0%**
  - Latched state `g_apds_occlusion_latched` until exit threshold crossed

**Scoring uses occlusion for target presence and hover gating**, not RGB color matching.

**RGB (r, g, b)** are read and can appear in **raw CSV** when enabled; they are **not** the primary scoring signal in current code.

**User-facing line:** “The purple target is detected when the tool **covers** the sensor zone — like blocking light over the target — not by measuring millimeter distance.”

---

## 4. Buttons and wiring

From `src/main.cpp` comments and logic:

- **Wiring:** Button to **GND**, **INPUT_PULLUP** → released = **HIGH**, pressed = **LOW**.
- **Debounce:** `kButtonDebounceMs` = **40 ms**
- **Action hold:** `kButtonActionHoldMs` = **80 ms** (stable press must last this long)
- **Level-based** detection with **consume latch** (release clears consumed flag so one press = one action)

| Button | Pin | When it works |
|--------|-----|----------------|
| **GREEN START** | D4 / GPIO4 | **IDLE** or **COMPLETE** → starts trial → **APPROACH** |
| **RED END** | D16 / GPIO16 | **DOCK** → **COMPLETE** (dock complete) |
| **RED RETURN** | D16 / GPIO16 | **COMPLETE** → **IDLE** (`RETURN_TO_IDLE` event) |

**Serial fallbacks (USB):** `s` start, `r` reset to IDLE, `d` simulate dock in DOCK (after `kDockIgnoreMs` = **100 ms** in DOCK).

**Demo tip:** Prefer **physical buttons** on camera; mention serial only as backup.

---

## 5. Firmware architecture (high level)

**File:** `src/main.cpp` only (PlatformIO env `esp32dev`, Arduino framework).

### `setup()`

- `Serial.begin(115200)`
- GPIO: buttons pull-up, status LED
- `Wire.begin()`, 100 kHz I2C
- Init **OLED**, **APDS** (ambient mode), **IMU** (`imu.begin(false)`)
- APDS baseline capture if APDS OK
- Boot messages: scoring enabled, APDS enter/exit %, CSV debug default OFF

### `loop()` (~25 Hz core sample)

- `kSamplePeriodMs` = **40 ms** → main metric accumulation ~**25 Hz**
- Debounce buttons → `handleButtons()`
- Poll APDS every **80 ms** (`kApdsPollMs`)
- Process event queue → metrics + `EVENT` / `FINAL_SCORE` lines
- Update OLED every **200 ms** (`kOledUpdateMs`)
- Read IMU, update tilt LPF, rolling windows
- Update state machine (APDS + stability)
- Print **LIVE** coaching line every **1500 ms** (`kLivePrintMs`) during active trial
- Optional **raw CSV** rows if `x` toggled ON (default OFF)

### Outputs

| Output | Role |
|--------|------|
| **EVENT** | State transitions + live score estimate |
| **LIVE** | Real-time coaching issue + phase metrics |
| **FINAL_SCORE** | Full breakdown after dock complete |
| **CAL_SET** | Scoring calibration updated (`c` command) |
| **Threshold block** | Human-readable lines from `q` |
| **Raw CSV** | High-rate debug stream when enabled |

---

## 6. State machine (exact states)

Enum `TrialState`: **IDLE → APPROACH → HOVER → DOCK → COMPLETE** (then RED RETURN → IDLE).

Serial state names: `IDLE`, `APPROACH`, `HOVER`, `DOCK`, `COMPLETE`.

### State diagram (text)

```
IDLE ──(GREEN START)──► APPROACH ──(APDS occluded)──► HOVER
                                                      │
                           ◄──(HOVER_RESET if target lost >400ms)──┘
                                                      │
                           (dwell ≥ 2000 ms stable+occluded)
                                                      ▼
                                                    DOCK ──(RED END)──► COMPLETE ──(RED RETURN)──► IDLE
```

### Per-state detail

#### IDLE

| | |
|--|--|
| **User** | Prepare; press **GREEN START** to begin. After a trial, press **RED RETURN** from COMPLETE. |
| **Firmware** | Updates APDS baseline EMA when valid; no trial metrics. |
| **Next** | GREEN START (or serial `s`) → `TRIAL_START` → **APPROACH**. |
| **OLED** | `IDLE`, trial #, previous score/feedback if any, `GREEN START`. |
| **Dashboard** | Banner: “Ready: Press GREEN START”; course map highlights Start. |

#### APPROACH

| | |
|--|--|
| **User** | Move through tube and poles toward purple target. |
| **Firmware** | Accumulates **course** metrics (gyro/jerk RMS, spikes, pauses, approach time). `g_hover_ms` held at 0. |
| **Next** | When `apds_frame.is_occluded` → `HOVER_ENTER` → **HOVER**. |
| **OLED** | `APPROACH`, live issue text, occlusion %, “Cover target”. |
| **Dashboard** | APPROACH banner; LIVE may include `gyro_rms`, `jerk_rms`, `spike_rate`. |

#### HOVER

| | |
|--|--|
| **User** | Keep tool over target; hold **steady** until dwell completes. |
| **Firmware** | Dwell timer `g_hover_ms` increments only when **`is_occluded && imu_stable`**. Stability: gyro ≤ **80**, jerk ≤ **800**, and occluded if `USE_APDS_OCCLUSION_GATE` (true). If occluded lost ≥ **400 ms** (`kOcclusionLossResetMs`) → `HOVER_RESET`, timer cleared. Jerky motion does not accumulate dwell. |
| **Next** | `g_hover_ms` ≥ **2000 ms** (`kHoverDwellMs`) → `HOVER_COMPLETE` → **DOCK**. |
| **OLED** | `HOVER`, dwell progress bar, “Hold steady”. |
| **Dashboard** | Large hover progress `hover_ms / 2000`; target lock & stability metrics if LIVE present. |

#### DOCK

| | |
|--|--|
| **User** | Press **RED END** gently on dock button. |
| **Firmware** | Tracks dock-phase jerk/gyro peaks and dock duration. Ignores serial `d` for first **100 ms** in DOCK. |
| **Next** | RED END held ≥ **80 ms** → `DOCK_COMPLETE` → **COMPLETE** + `FINAL_SCORE` + final scoring. |
| **OLED** | `DOCK`, “RED END”, hover phase score hint. |
| **Dashboard** | “Press RED dock gently”. |

#### COMPLETE

| | |
|--|--|
| **User** | Read score; press **RED RETURN** for next trial. |
| **Firmware** | Final component scores frozen; status LED **ON**. |
| **Next** | RED RETURN → `RETURN_TO_IDLE` → **IDLE**. |
| **OLED** | `SCORE`, x/100, feedback, phase times, `RED RETURN`. |
| **Dashboard** | Trial Review / History update from `FINAL_SCORE`. |

### Event names (firmware queue)

`TRIAL_START`, `HOVER_ENTER`, `HOVER_RESET`, `HOVER_COMPLETE`, `DOCK_COMPLETE`, `RETURN_TO_IDLE`, `RESET`, `BASELINE_SET`, `GAIN_CHANGED`, `APDS_READ_WARN`.

---

## 7. Scoring system (from code)

**Total: 0–100** = sum of six components (each clamped), then total clamped 0–100.

| Component | Max points | What it rewards |
|-----------|------------|-----------------|
| **Course** | **35** | Smooth controlled traversal during APPROACH (not “less motion”) |
| **Hover** | **30** | Stable occluded hover, few resets, reasonable hover duration |
| **Axis** | **15** | Handle/tool tilt vs baseline (accel gravity vector) |
| **Flow** | **10** | Total trial timing near **25–35 s** sweet spot |
| **Target** | **5** | APDS target coverage during hover; few occlusion losses |
| **Dock** | **5** | Gentle, timely dock press (small weight by design) |

**Important:** Final score is computed on **`DOCK_COMPLETE`** only (`computeFinalScore()` → `printScoreSummary()`). During trial, `EVENT`/`LIVE` show an **active estimate** (`computeActiveScoreEstimate()`).

### Course (35)

- Penalizes high **course gyro RMS**, **course jerk RMS**, **spike rate** vs good/bad thresholds (defaults or calibrated).
- Penalizes long **pause** time (gyro/jerk below pause thresholds for ≥ **1500 ms**).
- Penalizes very long approach time (> **40 s** bad, ramp from **16 s** good).
- **Does not** penalize motion merely for existing — user must move through the course.

Default good/bad references (when not calibrated): e.g. course gyro RMS good **130** / bad **260**; jerk good **1700** / bad **4200**; spike rate good **5.5** / bad **11.0** per second.

### Hover (30)

- Penalties: **hover resets** (6 pts each, cap 18), unstable fraction during hover, hover gyro/jerk RMS, very long hover phase.
- Bonuses: if hover completed with no resets and high occlusion fraction, floors hover score (e.g. min **24–25** in code paths).
- Dwell requirement: **2.0 s** accumulated stable+occluded time (not wall-clock only if user loses target).

### Axis (15)

- **Tilt** from low-pass filtered accel vs trial-start baseline.
- Penalizes tilt RMS (good **12°** / bad **40°**), time over warn tilt, max tilt.
- **Limitation (say honestly):** tilt from gravity vector is most meaningful during **slower/stable** segments; fast acceleration confounds “level handle” readings.

### Flow (10)

- Based on **total trial time** `total_ms` from trial start to dock complete.
- **Full 10 pts:** **25 000–35 000 ms** (25–35 s) — “ideal plateau.”
- Faster or slower trials lose points (see `scoreFlowTiming()` piecewise ramps).
- Related constants: fast band from **20 s**, slow band to **45 s**, min **15 s**, max **60 s**.

**Talking point:** “We want roughly **half a minute** per run — not rushed, not hesitant.”

### Target (5)

- Uses hover-phase **occluded sample fraction** and **occlusion loss** count (`HOVER_RESET` increments losses).
- Perfect path: hover complete, zero resets, ≥ **95%** occluded samples, zero losses → **5/5**.

### Dock (5)

- Small component: dock duration vs good **3 s** / bad **15 s**, dock jerk peak, dock gyro peak.
- **RED button confirms completion** — docking is necessary but not the main skill being trained.

### Feedback labels (`chooseFeedbackLabel`)

Examples from priority order in code:

- `Incomplete`, `Hover unstable`, `Lost target`, `Handle off-axis`
- `Course too jerky`, `Too much rotation`
- `Fast but controlled`, `Too fast`, `Too slow`
- `Dock too harsh`, `Great control`, `Good control`, `Improve hover`

Use the label shown on OLED/dashboard after a trial — do not invent a different label.

---

## 8. Calibration and tuning

### Why calibration matters

IMU scale and mounting, APDS lighting, and course layout change what “good” motion looks like. **Reference calibration** adapts scoring thresholds to a known-good trial on *your* rig.

### Serial / dashboard commands

| Key | Function |
|-----|----------|
| **z** | APDS baseline — target zone **open** (required before occlusion calib) |
| **o** / **v** | Record open / covered occlusion cal samples (~10 each) |
| **t** | Auto-tune APDS enter/exit from samples |
| **l** | Clear APDS occlusion calib samples |
| **g** | Cycle APDS ambient gain |
| **c** | **CAL_SET** — set scoring calibration from **last completed trial** |
| **C** | Clear scoring calibration to defaults |
| **q** | Print scoring **thresholds** block |
| **p** | Print score breakdown |
| **x** | Toggle **raw CSV** stream |
| **b** | Print button debug |
| **s** / **r** / **d** | Start / reset / dock simulate |

**Demo script tip:** After one smooth run, mention “press **c** on serial to teach the system your reference trial” (or Calibration tab in dashboard).

### APDS occlusion calibration workflow

1. `z` with target **open**
2. `o` × up to 10 (open samples)
3. `v` × up to 10 (covered samples)
4. `t` to apply enter/exit %

Boot defaults if not tuned: enter **15%**, exit **8%**.

---

## 9. Serial protocol (dashboard parses these)

**Baud:** 115200, 8N1 typical USB serial.

### `EVENT` (state / milestones)

Format (example):

```text
EVENT,trial=21,t_ms=895223,state=APPROACH,event=TRIAL_START,score=95
```

- `trial` — trial id (increments on start)
- `t_ms` — milliseconds since boot
- `state` — IDLE | APPROACH | HOVER | DOCK | COMPLETE
- `event` — e.g. TRIAL_START, HOVER_ENTER, HOVER_COMPLETE, DOCK_COMPLETE
- `score` — active total estimate during trial, or final-related value near complete

### `LIVE` (coaching ~1.5 s during trial)

Example:

```text
LIVE,trial=21,state=HOVER,score=82,issue=Hold steady,hover=1200/2000,stable=0,occ=1
```

APPROACH may add: `gyro_rms`, `jerk_rms`, `spike_rate`  
HOVER adds: `hover=ms/target_ms` or separate `hover_ms`, `stable`, `occ`/`occluded`, optional `tilt`  
DOCK may add: `dock_ms`

Dashboard maps `hover=a/b` into `hover_ms` and `hover_target_ms`.

### `FINAL_SCORE` (after dock)

One line with: `total`, `course`, `hover`, `axis`, `flow`, `target`, `dock`, `feedback`, `total_ms`, `approach_ms`, `hover_ms`, `dock_ms`, plus diagnostic fields (`course_gyro_rms`, `tilt_rms`, `hover_stable_pct`, `hover_occluded_pct`, `dock_jerk_peak`, `hover_resets`, `occlusion_losses`, …).

Example shape:

```text
FINAL_SCORE,trial=21,total=84,course=29,hover=26,axis=15,flow=7,target=5,dock=2,feedback=Fast but controlled,total_ms=30100,...
```

### `CAL_SET`

Emitted when scoring calibration succeeds after `c`:

```text
CAL_SET,course_gyro_rms=...,course_jerk_rms=...,course_spike_rate=...,hover_gyro_rms=...,hover_jerk_rms=...,dock_jerk_peak=...
```

### Thresholds (`q`)

Human-readable block starting with `# --- scoring thresholds ---` including `calibration=active|default`, good/bad pairs, `flow_target_ms=25000-35000`, `apds_enter/exit=15.0/8.0`, tilt good/warn/bad, dock jerk good/bad.

### Raw CSV (`x` toggle)

Header includes: IMU axes, `clear`, RGB, `occlusion_pct`, `is_occluded`, buttons, `hover_ms`, `event`.  
**Not required** for dashboard Live Coach; useful for Debug / research.

---

## 10. Laptop dashboard (Streamlit)

**Stack:** Python 3, Streamlit, PySerial, Pandas, Plotly — see `dashboard/requirements.txt`.

**Runs locally** in browser (default http://localhost:8501). **No cloud.**

### Connection

- Sidebar: select COM port → **Connect**
- **Only one app** may own the port (close PlatformIO serial monitor first)
- Polls serial about every **0.4 s** (`POLL_FRAGMENT_SEC`); fragment mode refreshes Live Coach without tab switching
- Status: Receiving / Connected quiet / Disconnected
- **Demo mode:** simulates a full trial without hardware (`Run demo trial`)

### Tabs (current names)

#### Live Coach

- Hero + **course phase map** (Start → Tube → Poles → Target → Hover → Dock → Complete)
- Large **state**, **score**, **trial #**, **coaching cue** (color-coded)
- Four **skill meters** when LIVE data exists: Motion Control, Hover Stability, Axis/Tilt, Target Lock
- **Hover dwell** progress bar in HOVER (if `hover_ms` in LIVE)
- Still updates from **EVENT-only** firmware for state/score

#### Trial Review

- After-action report: final score, feedback, component **% bar chart**, optional radar
- Phase timing vs **25–35 s** ideal band
- “What went well” / “Focus next” bullets
- **Event timeline** with relative seconds
- Export: CSV, JSON, Markdown per trial

#### History

- Best / latest / average / trial count
- Score trend, component trends, timing trend, feedback frequency
- Download all trials CSV → `dashboard/data/summary/trials.csv`

#### Calibration / Tuning

- Buttons for `z`, `c`, `C`, `q`, `p`, `x`
- Shows last CAL_SET / thresholds when received

#### Debug

- Last **200** raw lines
- Parsed EVENT / LIVE / FINAL tables
- Parse error count
- Manual serial commands (`z`, `p`, `q`, `c`, `C`, `x`, `r`, `s`, `d`)

---

## 11. Terminal workflow (Windows)

### Firmware (PlatformIO)

Use VS Code + PlatformIO or CLI. Known PlatformIO path on this machine:

```powershell
Set-Location "C:\SanciaMJW\projects\MYOSA\myosa_lap_trainer"
C:\Users\Mary\.platformio\penv\Scripts\platformio.exe run
C:\Users\Mary\.platformio\penv\Scripts\platformio.exe run -t upload
```

Optional serial monitor (close before dashboard):

```powershell
C:\Users\Mary\.platformio\penv\Scripts\platformio.exe device monitor -b 115200 --filter send_on_enter
```

### Dashboard

```powershell
Set-Location "C:\SanciaMJW\projects\MYOSA\myosa_lap_trainer"
pip install -r dashboard\requirements.txt
streamlit run dashboard\app.py
```

**Rule:** PlatformIO monitor **or** dashboard Connect — **not both**.

---

## 12. Step-by-step demo procedure (live audience)

1. **Wide shot** — full rig: tube, poles, purple target, buttons, MYOSA board, laptop.
2. Explain **problem** — surgical skills need objective feedback, not just pass/fail.
3. **MYOSA stack** — one board, modular sensors, USB to laptop.
4. Open dashboard → **Connect** correct COM → show “Receiving data.”
5. **IDLE** on OLED/dashboard — press **GREEN START**.
6. **APPROACH** — narrate tube + poles; point at Live Coach state + “Smooth course” style cue.
7. Cover **purple target** — call out occlusion / “target active.”
8. **HOVER** — show dwell bar 0→2 s; “Hold still.”
9. **HOVER_COMPLETE** → **DOCK** — press **RED END** gently.
10. **COMPLETE** — OLED score + dashboard **FINAL_SCORE** / Trial Review.
11. Walk **component bars** — what cost points (course vs hover vs flow).
12. **History** — improvement across trials (or one good run + goal).
13. Optional: **Calibration / Tuning** tab — `c` after a reference trial.
14. Close with **architecture** slide / diagram and future sensors.

---

## 13. Demo video narration bullets

- **Problem:** Training boxes teach completion, not quality of movement.
- **Gap:** No continuous feedback on smoothness, alignment, timing, or target control.
- **Solution:** MYOSA modules + phase-based scoring + live dashboard coach.
- **Course:** Tube → poles → purple target → hover → red dock (physical constraints).
- **IMU:** How smooth and how level the tool moves.
- **APDS:** Target zone presence via light occlusion (reliable vs proximity).
- **Buttons:** Unambiguous start and dock events.
- **Firmware:** State machine + fair scoring + serial stream.
- **Dashboard:** Live coach for the athlete, trial review for the coach.
- **Value:** Modular, low-cost, expandable surgical skills lab for MYOSA / IEEE.

---

## 14. Architecture (for slides)

### Data flow (describe visually)

```
User + lap tool
    → IMU (motion/tilt) + APDS (occlusion) + buttons
        → ESP32 MYOSA firmware (state machine + scoring)
            → USB serial (EVENT / LIVE / FINAL_SCORE)
                → Streamlit dashboard (live + history + export)
```

Parallel path: **OLED** shows state/score at the rig without laptop.

### Scoring pipeline (describe visually)

```
Raw samples (25 Hz) + APDS (80 ms) + events
    → Phase metrics (course / hover / dock times, RMS, spikes, tilt, occlusion)
        → Component scores (35+30+15+10+5+5)
            → Total /100 + feedback label
```

---

## 15. Video shot list

| Shot | Content |
|------|---------|
| 1 | Full rig wide — course story in one frame |
| 2 | MYOSA board + I2C sensor chain close-up |
| 3 | IMU on 3D-printed handle / tool |
| 4 | GREEN START button finger press |
| 5 | Tool entering tube (side angle) |
| 6 | Tool weaving poles |
| 7 | Purple target + tool covering → occlusion |
| 8 | OLED during HOVER (progress bar) |
| 9 | RED dock press |
| 10 | OLED COMPLETE score |
| 11 | Laptop Live Coach during APPROACH/HOVER |
| 12 | Trial Review component chart + feedback |
| 13 | History trend (if multiple trials) |
| 14 | Architecture graphic or whiteboard |

---

## 16. Known limitations (honest for judges)

- **No global position tracking** — does not know XYZ in the box; infers phase from APDS + time + motion.
- **No automatic tube/pole collision detection** — unless extra sensors added later.
- **APDS = zone occlusion**, not distance in millimeters.
- **IMU tilt** can be wrong during aggressive acceleration.
- **Lighting changes** affect APDS — recalibrate baseline (`z`) if environment changes.
- **Scoring tuning** matters — defaults are forgiving but a reference trial (`c`) helps.
- **Single serial port** — wrong COM or monitor conflict breaks dashboard.
- Root `README.md` may be outdated vs current occlusion firmware — use this doc.

---

## 17. Future improvements (roadmap talking points)

- Contact switches on tube/poles for collision feedback
- Extra APDS/light-gate checkpoints mid-course
- Reed/magnet checkpoints
- Camera or UWB tracking for true path error
- Multi-user profiles and cloud/CSV analytics
- Score normalization across users and venues
- WiFi/BLE logging without USB tether
- Machine learning on labeled trials for skill classification

---

## 18. Quick reference constants (from `src/main.cpp`)

| Constant | Value |
|----------|-------|
| Serial baud | 115200 |
| Sample period | 40 ms (~25 Hz) |
| APDS poll | 80 ms |
| OLED refresh | 200 ms |
| LIVE print interval | 1500 ms |
| Hover dwell | 2000 ms |
| Occlusion loss reset | 400 ms |
| APDS enter / exit % | 15.0 / 8.0 (default) |
| Stable gyro max | 80 |
| Stable jerk max | 800 |
| Flow ideal total | 25–35 s (25000–35000 ms) |
| Button debounce | 40 ms |
| Button hold | 80 ms |
| Dashboard poll | 0.4 s |

---

## 19. Files to cite in conversation

| Path | Role |
|------|------|
| `src/main.cpp` | Firmware: state machine, scoring, serial, OLED |
| `dashboard/app.py` | Streamlit UI |
| `dashboard/README.md` | Run/connect/troubleshoot dashboard |
| `cursor_myosa_laparoscopic_trainer_build_spec.md` | Original MVP spec (partially superseded for APDS) |
| `docs/demo_video_context.md` | This document |

**No `references/` folder** was present in the repo at documentation time.

---

*End of demo context document.*
