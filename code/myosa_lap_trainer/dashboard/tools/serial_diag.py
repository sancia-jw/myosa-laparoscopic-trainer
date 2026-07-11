"""Standalone serial diagnostic — run with Streamlit stopped."""

from __future__ import annotations

import sys
import time

import serial
import serial.tools.list_ports

BAUD = 115200
LISTEN_SEC = 5.0


def main() -> int:
    ports = sorted({p.device for p in serial.tools.list_ports.comports()})
    print("=== Smooth Operator Serial Diagnostic ===")
    print(f"Available ports: {ports or '(none)'}")
    target = "COM11" if "COM11" in ports else (ports[0] if ports else None)
    if not target:
        print("ERROR: No COM ports found.")
        return 1
    print(f"Opening {target} @ {BAUD} ...")
    ser = None
    try:
        ser = serial.Serial(target, BAUD, timeout=0.5)
        print(f"OK: port opened ({target})")
        ser.reset_input_buffer()
        ser.write(b"r")
        ser.flush()
        print("Sent reset command (r)")
        deadline = time.time() + LISTEN_SEC
        lines = 0
        while time.time() < deadline:
            if ser.in_waiting > 0:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if line:
                    lines += 1
                    print(f"  [{lines}] {line[:160]}")
            else:
                time.sleep(0.05)
        print(f"Received {lines} line(s) in {LISTEN_SEC:.0f}s")
        return 0 if lines > 0 else 2
    except serial.SerialException as exc:
        print(f"SERIAL ERROR: {exc}")
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 4
    finally:
        if ser is not None:
            try:
                if ser.is_open:
                    ser.close()
                    print("Port closed.")
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
