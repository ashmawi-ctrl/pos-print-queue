import pytest

from posqueue.printer import TcpRawPrinter


def test_printer_validates_port() -> None:
    with pytest.raises(ValueError):
        TcpRawPrinter("127.0.0.1", port=70000)


def test_printer_validates_timeout() -> None:
    with pytest.raises(ValueError):
        TcpRawPrinter("127.0.0.1", timeout_seconds=0)
