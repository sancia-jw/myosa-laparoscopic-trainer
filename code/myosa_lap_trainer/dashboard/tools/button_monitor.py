"""Live MYOSA button diagnostic — polls firmware 'b' command over serial."""
from __future__ import annotations

import sys
import time

import serial
import serial.tools.list_ports


def parse_button_line(line: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tok in line.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


def main() -> int:
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if not ports:
        print("ERROR: No COM port found. Plug in the MYOSA board.")
        return 1

    port = ports[0]
    duration = 20
    print(f"Port: {port}")
    print("Resetting firmware to IDLE...")
    ser = serial.Serial(port, 115200, timeout=0.2)
    time.sleep(0.3)
    ser.reset_input_buffer()
    ser.write(b"r")
    time.sleep(0.5)
    ser.reset_input_buffer()

    print()
    print(f"=== BUTTON MONITOR ({duration}s) ===")
    print("Press and HOLD each button for 1-2 seconds:")
    print("  GREEN START -> D4 / GPIO4")
    print("  RED END     -> D16 / GPIO16")
    print()

    start_seen = False
    end_seen = False
    deadline = time.time() + duration
    last_print = ""

    while time.time() < deadline:
        ser.write(b"b")
        time.sleep(0.12)
        chunk = ser.read(8192).decode("utf-8", errors="replace")
        start = end = None
        for line in chunk.splitlines():
            line = line.strip()
            if line.startswith("start raw="):
                start = parse_button_line(line.replace("start ", ""))
                if start.get("raw") == "1":
                    start_seen = True
            elif line.startswith("end raw="):
                end = parse_button_line(line.replace("end ", ""))
                if end.get("raw") == "1":
                    end_seen = True
        if start and end:
            msg = (
                f"START raw={start.get('raw')} stable={start.get('stable')} "
                f"ms={start.get('pressed_ms')} | "
                f"END raw={end.get('raw')} stable={end.get('stable')} "
                f"ms={end.get('pressed_ms')}"
            )
            if msg != last_print:
                print(msg)
                last_print = msg

    # Serial start test
    print()
    print("Testing serial fallback: sending 's' to start trial...")
    ser.write(b"s")
    time.sleep(0.4)
    chunk = ser.read(8192).decode("utf-8", errors="replace")
    trial_started = "TRIAL_START" in chunk or "state=APPROACH" in chunk
    for line in chunk.splitlines():
        if "EVENT" in line or "TRIAL_START" in line:
            print(" ", line.strip())
    ser.close()

    print()
    print("=== DIAGNOSIS ===")
    print(f"GREEN START press detected: {'YES' if start_seen else 'NO'}")
    print(f"RED END press detected:     {'YES' if end_seen else 'NO'}")
    print(f"Serial 's' starts trial:    {'YES' if trial_started else 'NO'}")

    if not start_seen and not end_seen and trial_started:
        print()
        print("Firmware works, but GPIO never saw a button press.")
        print("Check wiring: one leg -> GPIO pin, other leg -> GND (not 3.3V).")
    elif start_seen or end_seen:
        print()
        print("GPIO sees button presses. If trial still won't start:")
        print("- GREEN START only works in IDLE or COMPLETE (OLED must say IDLE/SCORE).")
        print("- Hold the button ~0.1s (80ms debounce).")
        print("- RED END only works in DOCK or COMPLETE.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
