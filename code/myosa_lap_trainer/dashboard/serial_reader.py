"""Background serial reader — decouples ingestion from Streamlit rendering."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

READ_SLEEP_IDLE_SEC = 0.005
READ_SLEEP_ERROR_SEC = 0.05


class BackgroundSerialReader:
    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue(maxsize=1000)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ser: Any = None
        self.lines_read = 0
        self.last_error = ""

    def start(self, ser: Any) -> None:
        self.stop()
        self._ser = ser
        self._stop.clear()
        self.last_error = ""
        self._thread = threading.Thread(target=self._loop, name="myosa-serial", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        self._thread = None
        self._ser = None
        self.last_error = ""
        self._discard_queue()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _discard_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _loop(self) -> None:
        while not self._stop.is_set():
            ser = self._ser
            if ser is None or not getattr(ser, "is_open", False):
                time.sleep(READ_SLEEP_ERROR_SEC)
                continue
            try:
                if ser.in_waiting > 0:
                    raw = ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    self.lines_read += 1
                    self.last_error = ""
                    try:
                        self._queue.put_nowait(line)
                    except queue.Full:
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            pass
                        self._queue.put_nowait(line)
                else:
                    time.sleep(READ_SLEEP_IDLE_SEC)
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                time.sleep(READ_SLEEP_ERROR_SEC)

    def drain(self, handler: Callable[[str], None]) -> int:
        count = 0
        while True:
            try:
                line = self._queue.get_nowait()
            except queue.Empty:
                break
            handler(line)
            count += 1
        return count
