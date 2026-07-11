"""End-to-end serial_manager verification against real COM11."""

from __future__ import annotations

import time

import serial.tools.list_ports

import serial_manager as sm


def main() -> int:
    ports = sorted({p.device for p in serial.tools.list_ports.comports()})
    print("=== serial_manager hardware check ===")
    print("Ports:", ports)
    if "COM11" not in ports:
        print("COM11 not available")
        return 1

    logs: list[str] = []

    def log(msg: str) -> None:
        logs.append(msg)
        print("LOG:", msg)

    ok = sm.connect("COM11", log=log)
    print("connect:", ok, "status:", sm.connection_status(), "label:", sm.health_label())
    if not ok:
        print("error:", sm.last_error())
        return 2

    sm.write_command("r", log=log)
    lines: list[str] = []

    def on_line(line: str) -> None:
        lines.append(line)
        print("RX:", line[:160])

    deadline = time.time() + 4.0
    while time.time() < deadline and len(lines) < 3:
        sm.drain_lines(on_line)
        time.sleep(0.05)

    print("lines:", len(lines), "first_line:", sm.first_line_received())
    sm.disconnect(log=log)
    print("after disconnect connected:", sm.is_connected())
    return 0 if lines else 3


if __name__ == "__main__":
    raise SystemExit(main())
