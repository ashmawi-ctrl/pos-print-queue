import socket
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PrintReceipt:
    bytes_sent: int


class PrinterDeliveryError(RuntimeError):
    """Printer delivery failed.

    may_have_printed=True means the client cannot prove whether the printer
    already received enough bytes to produce output. Automatic retries should
    be avoided in that state because they may create a duplicate receipt.
    """

    def __init__(self, message: str, *, may_have_printed: bool) -> None:
        super().__init__(message)
        self.may_have_printed = may_have_printed


class PrinterClient(Protocol):
    def send(self, content: str) -> PrintReceipt:
        ...


class TcpRawPrinter:
    """Minimal raw TCP printer client, commonly used with port 9100 printers."""

    def __init__(
        self,
        host: str,
        port: int = 9100,
        *,
        timeout_seconds: float = 3.0,
        encoding: str = "utf-8",
    ) -> None:
        if not host:
            raise ValueError("host cannot be empty")
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")

        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.encoding = encoding

    def send(self, content: str) -> PrintReceipt:
        payload = content.encode(self.encoding)
        connected = False
        started_send = False

        try:
            with socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout_seconds,
            ) as sock:
                connected = True
                sock.settimeout(self.timeout_seconds)
                started_send = True
                sock.sendall(payload)
        except OSError as exc:
            may_have_printed = connected and started_send
            raise PrinterDeliveryError(
                str(exc),
                may_have_printed=may_have_printed,
            ) from exc

        return PrintReceipt(bytes_sent=len(payload))


class DryRunPrinter:
    """Printer implementation used for local demos and safe testing."""

    def __init__(self) -> None:
        self.printed: list[str] = []

    def send(self, content: str) -> PrintReceipt:
        self.printed.append(content)
        return PrintReceipt(bytes_sent=len(content.encode("utf-8")))
