"""Single authoritative serial connection for the dashboard (survives Streamlit reruns)."""

from __future__ import annotations

import time
from typing import Any, Callable

import serial

from serial_reader import BackgroundSerialReader

BAUD = 115200

_reader = BackgroundSerialReader()
_conn: serial.Serial | None = None
_port: str | None = None
_status: str = "disconnected"
_last_error: str = ""
_first_line_at: float | None = None
_connect_lock_ts: float = 0.0

LogFn = Callable[[str], None]


def _noop_log(_msg: str) -> None:
    pass


def selected_port() -> str | None:
    return _port


def connection_status() -> str:
    return _status


def last_error() -> str:
    return _last_error


def first_line_received() -> bool:
    return _first_line_at is not None


def get_serial() -> serial.Serial | None:
    if _conn is None:
        return None
    is_open = getattr(_conn, "is_open", False)
    if callable(is_open):
        try:
            is_open = bool(is_open())
        except Exception:  # noqa: BLE001
            return None
    return _conn if is_open else None


def is_connected() -> bool:
    ser = get_serial()
    if ser is None:
        return False
    thread = _reader._thread
    return thread is not None and thread.is_alive()


def reader_error() -> str:
    return _reader.last_error


def note_line_received() -> None:
    global _first_line_at
    if _first_line_at is None:
        _first_line_at = time.time()


def connect(port: str, *, log: LogFn | None = None) -> bool:
    """Open port once and start the background reader."""
    global _conn, _port, _status, _last_error, _first_line_at, _connect_lock_ts

    log = log or _noop_log

    if is_connected() and _port == port:
        log(f"connect skipped already open port={port}")
        _status = "connected"
        return True

    now = time.time()
    if now - _connect_lock_ts < 0.35:
        log(f"connect throttled port={port}")
        return is_connected()

    disconnect(log=log)
    _status = "connecting"
    _connect_lock_ts = now
    _last_error = ""
    log(f"connect requested port={port}")

    try:
        ser = serial.Serial(port, BAUD, timeout=0)
        _conn = ser
        _port = port
        _first_line_at = None
        _reader.start(ser)
        _status = "connected"
        log(f"port opened port={port}")
        log("reader started")
        return True
    except serial.SerialException as exc:
        _conn = None
        _port = None
        _status = _classify_serial_exception(exc)
        _last_error = str(exc)
        log(f"connect exception port={port} err={exc}")
        return False
    except Exception as exc:  # noqa: BLE001
        _conn = None
        _port = None
        _status = "failed"
        _last_error = str(exc)
        log(f"connect exception port={port} err={exc}")
        return False


def disconnect(*, log: LogFn | None = None) -> None:
    global _conn, _port, _status, _last_error, _first_line_at, _connect_lock_ts

    log = log or _noop_log
    if _conn is None and _status == "disconnected":
        return

    log("disconnect requested")
    _reader.stop()
    ser = _conn
    if ser is not None:
        try:
            if getattr(ser, "is_open", False):
                ser.close()
                log("port closed")
        except Exception as exc:  # noqa: BLE001
            log(f"port close exception {exc}")
    _conn = None
    _port = None
    _status = "disconnected"
    _last_error = ""
    _first_line_at = None
    _connect_lock_ts = 0.0
    log("reader stopped")


def write_command(cmd: str, *, log: LogFn | None = None) -> bool:
    log = log or _noop_log
    ser = get_serial()
    if ser is None:
        _set_lost("write while disconnected")
        log("write failed not connected")
        return False
    try:
        ser.write(cmd.encode("ascii"))
        ser.flush()
        return True
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)
        _status = "device_lost"
        log(f"write exception {exc}")
        return False


def drain_lines(handler: Callable[[str], None]) -> int:
    """Drain queued lines; update health from reader/port state."""
    global _status, _last_error

    if not is_connected():
        return 0

    err = _reader.last_error
    ser = get_serial()
    if ser is None:
        _set_lost("serial port closed")
        return 0

    count = _reader.drain(handler)
    if count > 0:
        note_line_received()
        return count

    thread = _reader._thread
    if thread is None or not thread.is_alive():
        _set_lost("reader thread stopped")
        return 0

    if err and not getattr(ser, "is_open", False):
        _last_error = err
        _status = "device_lost"
    return count


def health_label() -> str:
    if _status == "connecting":
        return "Connecting…"
    if _status == "port_busy":
        return "Port Busy"
    if _status == "failed":
        return "Connection Failed"
    if _status == "device_lost":
        return "Device Lost"
    if is_connected():
        if _first_line_at is not None:
            return "Device Connected"
        return "Device Connected"
    if _last_error:
        if _status == "port_busy":
            return "Port Busy"
        return "Connection Failed"
    return "Disconnected"


def sync_session_connection_state(state: dict[str, Any]) -> None:
    """Mirror module connection metadata into Streamlit session_state."""
    state["connected"] = is_connected()
    state["serial_port"] = _port
    state["connection_status"] = _status
    state["last_serial_error"] = _last_error
    state["serial_conn"] = get_serial()


def _set_lost(reason: str) -> None:
    global _status, _last_error
    _status = "device_lost"
    _last_error = reason


def _classify_serial_exception(exc: Exception) -> str:
    msg = str(exc).lower()
    if "access is denied" in msg or "permission" in msg or "busy" in msg:
        return "port_busy"
    return "failed"
