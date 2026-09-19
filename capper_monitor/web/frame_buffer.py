from __future__ import annotations

import threading
from typing import Optional


class FrameBuffer:
    """メインループ→Web配信スレッドへ最新フレーム(JPEG)と状態をロック付きで共有する。

    カメラハードウェアへは常にメインループのみがアクセスし、Web配信スレッドは
    このバッファを読むだけにすることで、カメラの二重オープン・リソース競合を避ける。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._jpeg_bytes: Optional[bytes] = None
        self._status: dict = {"state": "normal", "reason": "startup", "timestamp": None}

    def update_frame(self, jpeg_bytes: bytes) -> None:
        with self._lock:
            self._jpeg_bytes = jpeg_bytes

    def get_frame(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg_bytes

    def update_status(self, state: str, reason: str, timestamp: Optional[float]) -> None:
        with self._lock:
            self._status = {"state": state, "reason": reason, "timestamp": timestamp}

    def get_status(self) -> dict:
        with self._lock:
            return dict(self._status)
