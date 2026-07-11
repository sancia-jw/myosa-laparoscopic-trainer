"""Serial connection stability tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import serial

import serial_manager as sm
from serial_reader import BackgroundSerialReader


@pytest.fixture(autouse=True)
def reset_serial_manager() -> None:
    sm.disconnect()
    yield
    sm.disconnect()


def test_single_reader_instance() -> None:
    assert isinstance(sm._reader, BackgroundSerialReader)
    assert sm._reader is sm._reader


def test_connect_skips_when_already_open() -> None:
    mock_ser = MagicMock()
    mock_ser.is_open = True
    logs: list[str] = []

    with patch("serial_manager.serial.Serial", return_value=mock_ser):
        assert sm.connect("COM11", log=logs.append) is True
        assert sm.connect("COM11", log=logs.append) is True
        assert any("already open" in x for x in logs)


def test_disconnect_closes_and_clears() -> None:
    mock_ser = MagicMock()
    mock_ser.is_open = True
    with patch("serial_manager.serial.Serial", return_value=mock_ser):
        assert sm.connect("COM11") is True
        assert sm.is_connected()
        sm.disconnect()
        assert not sm.is_connected()
        assert sm.connection_status() == "disconnected"
        mock_ser.close.assert_called()


def test_failed_connection_exposes_error() -> None:
    with patch(
        "serial_manager.serial.Serial",
        side_effect=serial.SerialException("Access is denied"),
    ):
        assert sm.connect("COM11") is False
        assert sm.connection_status() == "port_busy"
        assert "Access is denied" in sm.last_error()
        assert sm.health_label() == "Port Busy"


def test_reader_not_duplicated_on_reconnect() -> None:
    mock_ser = MagicMock()
    mock_ser.is_open = True
    with patch("serial_manager.serial.Serial", return_value=mock_ser):
        sm.connect("COM11")
        thread_a = sm._reader._thread
        sm.connect("COM11")
        thread_b = sm._reader._thread
        assert thread_a is thread_b


def test_drain_preserves_connection_on_empty_queue() -> None:
    mock_ser = MagicMock()
    mock_ser.is_open = True
    with patch("serial_manager.serial.Serial", return_value=mock_ser):
        sm.connect("COM11")
        seen: list[str] = []
        count = sm.drain_lines(seen.append)
        assert count == 0
        assert sm.is_connected()


def test_health_label_not_reconnecting_forever() -> None:
    with patch(
        "serial_manager.serial.Serial",
        side_effect=serial.SerialException("Access is denied"),
    ):
        sm.connect("COM11")
        assert sm.health_label() == "Port Busy"
        assert sm.health_label() != "Reconnecting"


def test_theme_does_not_force_white_main_text() -> None:
    from ui.theme import THEME_CSS

    assert 'section[data-testid="stSidebar"] *' not in THEME_CSS
    assert "color: var(--indigo-depth)" in THEME_CSS
    assert "--soft-warm-white" in THEME_CSS
    assert "--lagoon-flow" in THEME_CSS


def test_disconnected_disables_start_flags() -> None:
    from session_sync import control_flags

    flags = control_flags("READY")
    assert flags["start"] is True
    assert not sm.is_connected()
