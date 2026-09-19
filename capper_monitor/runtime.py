from __future__ import annotations

import fcntl
import os
import socket
from typing import Optional


class SingletonLock:
    """flockベースの多重起動防止ロック。GPIO/カメラの多重確保を防ぐ。"""

    def __init__(self, path: str):
        self._path = path
        self._fp = None

    def acquire(self) -> None:
        self._fp = open(self._path, "w")
        try:
            fcntl.flock(self._fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._fp.close()
            self._fp = None
            raise RuntimeError(
                f"別のインスタンスが既に起動しています (lock_file={self._path})"
            ) from exc

    def release(self) -> None:
        if self._fp is not None:
            try:
                fcntl.flock(self._fp, fcntl.LOCK_UN)
            finally:
                self._fp.close()
                self._fp = None


class WatchdogNotifier:
    """systemdのsd_notifyプロトコルを標準ライブラリのsocketのみで実装する（追加パッケージ不要）。

    $NOTIFY_SOCKET が未設定（systemd経由で起動していない）、または無効化されている場合は
    何もしない。
    """

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._address: Optional[str] = os.environ.get("NOTIFY_SOCKET")
        self._sock: Optional[socket.socket] = None
        if self._enabled and self._address:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    def _send(self, data: bytes) -> None:
        if self._sock is None or not self._address:
            return
        address = self._address
        if address.startswith("@"):
            address = "\0" + address[1:]
        try:
            self._sock.sendto(data, address)
        except OSError:
            pass

    def notify_ready(self) -> None:
        self._send(b"READY=1")

    def notify_watchdog(self) -> None:
        self._send(b"WATCHDOG=1")

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None
