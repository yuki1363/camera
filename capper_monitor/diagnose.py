"""現場での切り分け用の自己診断（`python -m capper_monitor --diagnose`）。

サービスを止めた状態で実行し、設定・書き込み権限・GPIO・カメラ・検知スコアを順に調べて、
どこに問題があるかを1画面で示す。PLCへの出力は動かさない（OFFのまま）。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, List, Optional

import cv2
import numpy as np

from capper_monitor.camera.factory import create_camera
from capper_monitor.config import AppConfig
from capper_monitor.detection.factory import create_alignment_checker, create_detector, create_motion_detector
from capper_monitor.detection.roi import RoiFractional
from capper_monitor.io.gpio import create_gpio_resources
from capper_monitor.runtime import SingletonLock

_OK, _WARN, _NG = "OK", "注意", "NG"

# 診断で撮るフレーム数と、明るさ（0〜255の平均）の目安
_FRAME_COUNT = 30
_TOO_DARK = 30
_TOO_BRIGHT = 235


class Report:
    def __init__(self, out: Callable[[str], None] = print):
        self._out = out
        self.counts = {_OK: 0, _WARN: 0, _NG: 0}

    def add(self, level: str, title: str, detail: str = "") -> None:
        self.counts[level] += 1
        self._out(f"[{level}] {title}" + (f"\n      {detail}" if detail else ""))

    def section(self, name: str) -> None:
        self._out(f"\n■ {name}")


def _writable(path: Path) -> bool:
    """ファイルがあればそのファイル、無ければ作成先のフォルダに書き込めるか。"""
    target = path if path.exists() else path.parent
    while not target.exists() and target != target.parent:
        target = target.parent
    return os.access(target, os.W_OK)


def _check_files(config: AppConfig, config_path: Optional[str], report: Report) -> None:
    report.section("ファイルと権限")
    if config_path is not None:
        if _writable(Path(config_path)):
            report.add(_OK, f"設定ファイルに書き込めます: {config_path}")
        else:
            report.add(
                _NG,
                f"設定ファイルに書き込めません: {config_path}",
                "スマホ調整画面の「保存」が失敗します。サービスの実行ユーザーに書き込み権限を付けてください。",
            )
    if config.logging.file_path:
        if _writable(Path(config.logging.file_path)):
            report.add(_OK, f"ログを書き込めます: {config.logging.file_path}")
        else:
            report.add(_WARN, f"ログファイルに書き込めません: {config.logging.file_path}", "画面出力(journalctl)のみになります。")
    det = config.detection
    if det.alignment_check.enabled and not _writable(Path(det.alignment_check.reference_path)):
        report.add(_WARN, f"位置ズレ基準を保存できません: {det.alignment_check.reference_path}")
    if det.strategy == "baseline_diff" and not Path(det.baseline_diff.reference_path).is_file():
        report.add(
            _WARN,
            "基準フレームが未撮影です（baseline_diff）",
            f"{det.fallback_strategy} で代用して動きます。スマホ調整画面で基準フレームを撮影してください。",
        )


def _check_web(config: AppConfig, report: Report) -> None:
    report.section("スマホ画面")
    web = config.web
    if not web.enabled:
        report.add(_WARN, "スマホ画面は無効です（web.enabled: false）", "スマホからつなぐには true にして再起動してください。")
        return
    report.add(_OK, f"スマホ画面は有効です: http://<ラズパイのIP>:{web.port}/calibrate")
    if not web.calibration_enabled:
        report.add(_WARN, "調整機能は無効です（web.calibration_enabled: false）")


def _check_gpio(config: AppConfig, pin_factory, report: Report) -> None:
    report.section("GPIO（PLC出力・リセット入力）")
    try:
        gpio = create_gpio_resources(config.gpio, pin_factory=pin_factory)
    except Exception as exc:  # GPIOが開けない理由はOS・配線で様々なので、そのまま見せる
        report.add(_NG, "GPIOを開けません", f"{type(exc).__name__}: {exc}")
        return
    try:
        report.add(_OK, f"GPIOを開けました（出力 GPIO{config.gpio.alarm_output.pin} はOFFのまま）")
        for label, device, cfg in (
            ("リセットボタン", gpio.reset_button, config.gpio.reset_button),
            ("PLCリセット入力", gpio.plc_reset_input, config.gpio.plc_reset_input),
        ):
            if device.is_active:
                report.add(
                    _NG,
                    f"{label}（GPIO{cfg.pin}）が入ったままです",
                    "入っている間は常に「正常」へ戻され、ラインを検知しません。ボタン・PLCが本当に"
                    f"入っていないなら、配線か pull_up（今は {str(cfg.pull_up).lower()}）が逆です。",
                )
            else:
                report.add(_OK, f"{label}（GPIO{cfg.pin}）は入っていません")
    finally:
        gpio.close()


def _check_camera(config: AppConfig, camera, report: Report, sleep: Callable[[float], None]) -> None:
    report.section("カメラと検知")
    try:
        camera.open()
    except Exception as exc:
        report.add(_NG, "カメラを開けません", f"{type(exc).__name__}: {exc}")
        return
    try:
        frames: List[np.ndarray] = []
        failures = 0
        for _ in range(_FRAME_COUNT):
            frame = camera.read()
            if frame is None:
                failures += 1
            else:
                frames.append(frame)
            sleep(config.app.loop_interval_s)
    finally:
        camera.close()

    if not frames:
        report.add(_NG, "カメラから映像を取得できません", "ケーブル・camera.backend の設定を確認してください。")
        return
    if failures:
        report.add(_WARN, f"映像の取得に {failures}/{_FRAME_COUNT} 回失敗しました", "ケーブルの接触・電源容量を確認してください。")
    height, width = frames[-1].shape[:2]
    report.add(_OK, f"映像を取得できました（{width}x{height}）")

    brightness = float(np.mean(cv2.cvtColor(frames[-1], cv2.COLOR_BGR2GRAY)))
    if brightness < _TOO_DARK:
        report.add(_NG, f"映像が暗すぎます（明るさ {brightness:.0f}/255）", "照明・レンズキャップ・露出の固定値を確認してください。")
    elif brightness > _TOO_BRIGHT:
        report.add(_NG, f"映像が明るすぎます（明るさ {brightness:.0f}/255）", "白飛びすると赤が判定できません。照明の映り込みを確認してください。")
    else:
        report.add(_OK, f"明るさは適正です（{brightness:.0f}/255）")

    det = config.detection
    detector = create_detector(det)
    try:
        scores = [detector.detect(f).score for f in frames]
    except RuntimeError as exc:
        report.add(_NG, "検知処理がエラーになります", str(exc))
        scores = []
    if scores and getattr(detector, "threshold", None) is None:
        report.add(_OK, f"スコア {min(scores):.4f}〜{max(scores):.4f}（方式 {detector.strategy_name}）")
    elif scores:
        low, high = min(scores), max(scores)
        threshold = detector.threshold
        detail = f"方式 {detector.strategy_name} / スコア {low:.4f}〜{high:.4f} / しきい値 {threshold:.4f}"
        release = threshold * det.score_filter.release_ratio
        if low < threshold <= high or low < release <= high:
            report.add(
                _NG,
                "スコアがしきい値をまたいで揺れています（誤検知・未検知の原因）",
                detail + "。満杯時とライン露出時のスコアを見て、その間にしきい値を置き直してください。",
            )
        else:
            now_state = "ラインが見えている" if low >= threshold else "ラインは見えていない"
            report.add(_OK, f"今の判定: {now_state}", detail + "。実際の状態と合っているか確認してください。")
        hsv = cv2.cvtColor(RoiFractional(det.roi.x, det.roi.y, det.roi.w, det.roi.h).crop(frames[-1]), cv2.COLOR_BGR2HSV)
        if det.strategy == "color_mask" and hsv.size:
            sat, val = float(np.median(hsv[..., 1])), float(np.median(hsv[..., 2]))
            report.add(_OK, f"ROI内の色の中央値: 彩度 {sat:.0f} / 明度 {val:.0f}", "ROIが狙った場所にあるかはスマホ画面で確認してください。")

    if det.alignment_check.enabled:
        checker = create_alignment_checker(det)
        if not checker.is_ready:
            report.add(_OK, "位置ズレ基準は未撮影です（位置ズレ検知は働きません）")
        else:
            correlations = [checker.check(f).correlation for f in frames]
            worst = min(correlations)
            limit = det.alignment_check.correlation_threshold
            if worst < limit:
                report.add(
                    _NG,
                    f"位置ズレと判定されています（一致度 {worst:.2f} < {limit:.2f}）",
                    "この間はライン検知が止まり、出力は直前のまま変わりません。カメラが動いていないなら、"
                    "模様のある動かない場所に位置ズレ用の枠を置き、基準を撮り直してください"
                    "（無地の壁では一致度が安定しません）。",
                )
            else:
                report.add(_OK, f"位置ズレなし（一致度 {worst:.2f}〜{max(correlations):.2f}）")

    if det.refill_detection.enabled and len(frames) >= 2:
        motion = create_motion_detector(det)
        peak = max(motion.detect(f).ratio for f in frames)
        limit = det.refill_detection.motion_ratio
        where = "指定範囲" if det.refill_detection.roi is not None else "画面全体（範囲が未設定）"
        if peak >= limit:
            report.add(
                _WARN,
                f"何もしていなくても動きありと判定されます（動き量 {peak:.3f} ≥ {limit:.3f}）",
                f"見ている範囲: {where}。補充していないのに点滅する原因です。静止させた状態なら、"
                "スマホ調整画面で範囲としきい値を設定し直してください。",
            )
        else:
            report.add(_OK, f"静止時の動き量 {peak:.3f}（しきい値 {limit:.3f}、範囲: {where}）")
            if det.refill_detection.roi is None:
                report.add(_WARN, "補充の動きを見る範囲が未設定です", "人が横切るだけで点滅し、補充では点滅しにくくなります。")


def run_diagnosis(
    config: AppConfig,
    config_path: Optional[str] = None,
    camera=None,
    gpio_pin_factory=None,
    out: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """診断を実行し、NGの件数を返す。"""
    report = Report(out)
    out("capper-monitor 自己診断")

    lock = SingletonLock(config.app.lock_file_path)
    try:
        lock.acquire()
    except RuntimeError:
        report.add(
            _NG,
            "サービスが動作中のため診断できません",
            "`sudo systemctl stop capper-monitor` で止めてから、もう一度実行してください。",
        )
        return report.counts[_NG]
    try:
        _check_files(config, config_path, report)
        _check_web(config, report)
        _check_gpio(config, gpio_pin_factory, report)
        _check_camera(config, camera if camera is not None else create_camera(config.camera), report, sleep)
    finally:
        lock.release()

    out(f"\n結果: NG {report.counts[_NG]}件 / 注意 {report.counts[_WARN]}件 / OK {report.counts[_OK]}件")
    return report.counts[_NG]
