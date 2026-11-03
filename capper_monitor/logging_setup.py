from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from capper_monitor.config import LoggingConfig

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(config: LoggingConfig) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.level))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_FORMAT)

    if config.console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    if config.file_path:
        try:
            path = Path(config.file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                path, maxBytes=config.max_bytes, backupCount=config.backup_count, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            logging.getLogger(__name__).warning(
                "ログファイル %s を作成できませんでした。コンソール出力のみ続行します。",
                config.file_path,
            )


def log_event(logger: logging.Logger, level: int, event: str, **fields) -> None:
    if fields:
        message = event + " " + " ".join(f"{key}={value}" for key, value in fields.items())
    else:
        message = event
    logger.log(level, message)
