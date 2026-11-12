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
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="設定・権限・GPIO・カメラ・検知スコアを調べて問題箇所を表示する（サービスを止めてから実行）",
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

    if args.diagnose:
        from capper_monitor.diagnose import run_diagnosis

        return 1 if run_diagnosis(config, config_path=args.config) else 0

    setup_logging(config.logging)
    app = App(config, config_path=args.config)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
