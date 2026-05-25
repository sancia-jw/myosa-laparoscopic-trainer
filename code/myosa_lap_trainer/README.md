# Precision in Practice — MYOSA Laparoscopic Trainer

IEEE MYOSA competition MVP: sensorized laparoscopic skills trainer with ESP32 firmware, USB serial streaming, and a Python/Streamlit dashboard for logging and prototype scoring.

## Hardware chain

```
MYOSA motherboard → MPU6050 IMU (0x69) → APDS9960 proximity (0x39) → OLED (0x3C)
```

Optional: **START** and **DOCK** buttons (INPUT_PULLUP, pressed = LOW), optional buzzer, MYOSA blue LED on GPIO2.

## Firmware states

| State | Description |
|-------|-------------|
| `IDLE` | Wait for START; OLED: PRESS START |
| `APPROACH` | Trial running; move tool toward hover target |
| `HOVER` | Proximity in band; hold stable for dwell (default 2 s) |
| `DOCK` | Press recessed dock target |
| `COMPLETE` | Trial done; stream continues |

**Serial fallback (USB):** `s` = start trial, `r` = reset to IDLE, `d` = simulate dock (in DOCK only).

## Serial protocol

Baud **115200**. After brief startup lines, firmware prints one CSV header:

```text
trial_id,sample,t_ms,state,ax,ay,az,gx,gy,gz,acc_mag,gyro_mag,jerk_proxy,prox,start_btn,dock_btn,is_stable,hover_ms,event
```

Rows at ~**25 Hz**. `state` is `IDLE`, `APPROACH`, `HOVER`, `DOCK`, or `COMPLETE`. `event` is usually empty; on transitions: `TRIAL_START`, `HOVER_ENTER`, `HOVER_RESET`, `HOVER_COMPLETE`, `DOCK_COMPLETE`, `RESET`.

## Build / upload / monitor (VS Code + PlatformIO)

Use **VS Code with PlatformIO**, not Cursor’s PlatformIO integration.

1. Open this folder in VS Code.
2. **Build:** PlatformIO → Build, or `pio run`.
3. **Upload:** PlatformIO → Upload, or `pio run -t upload`.
4. **Monitor:** PlatformIO → Monitor, or `pio device monitor -b 115200`.

## Threshold tuning (`src/main.cpp`)

Edit constants at the top of `main.cpp`:

| Constant | Purpose |
|----------|---------|
| `HOVER_PROX_MIN` / `HOVER_PROX_MAX` | Proximity band for hover (counts 0–255) |
| `STABLE_GYRO_MAX` | Max gyro magnitude (deg/s) while accumulating hover time |
| `STABLE_JERK_MAX` | Max jerk proxy while stable |
| `HOVER_DWELL_MS` | Required stable hover duration (default 2000) |
| `START_BUTTON_PIN` / `DOCK_BUTTON_PIN` | GPIO pins (TODO: match your wiring) |

**Proximity:** Many boards read **~0–5** at distance and higher when close. Default band is **2–40**; increase `HOVER_PROX_MIN` if hover never triggers.

**IMU baseline:** MYOSA `AccelAndGyro` reports **cm/s²**. At rest, `acc_mag` may read **~1900–2050** (~2× 1 g) due to library scaling — use **relative** jerk/gyro for stability, not absolute 980.

## APDS9960 ID 0x9E

Some MYOSA boards return chip ID **0x9E** at register `0x92`. The local `LightProximityAndGesture` library accepts `0x9E` in addition to the original IDs.

## Dashboard

```bash
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

Enter serial port (e.g. `COM8`), connect, run trials. Raw CSV → `data/raw/`, summaries → `data/summary/`.

Scoring in the dashboard is a **prototype index** (penalties for hover resets, motion, time) — **not** clinically validated.

## Project layout

- `src/main.cpp` — firmware state machine and CSV stream
- `lib/` — MYOSA sensor libraries
- `dashboard/` — Streamlit app
- `cursor_myosa_laparoscopic_trainer_build_spec.md` — full build spec

## License / competition

Built for the MYOSA laparoscopic trainer demo. See official MYOSA documentation for hardware details.
