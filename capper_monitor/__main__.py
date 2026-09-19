from __future__ import annotations

import argparse
import sys

from capper_monitor.app import App
from capper_monitor.config import ConfigError, load_config
from capper_monitor.logging_setup import setup_logging


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="capper_monitor")
    parser.add_argument(
        "--config", default="/etc/capper-monitor/config.yaml", help="設定ファイルのパス"
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="設定ファイルを検証するだけで起動しない（systemctl restart前の事前確認用）",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"設定エラー: {exc}", file=sys.stderr)
        return 1

    if args.check_config:
        print("設定は正常です")
        return 0

    setup_logging(config.logging)
    app = App(config)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
