#!/usr/bin/env python3
"""現場でのROI・検知しきい値・基準フレーム調整ツール。

USBカメラのプレビュー(cv2.imshow)を使うため、requirements.txtの
opencv-python-headlessではなく、本スクリプトを実行する環境にのみ
GUI対応版の`opencv-python`を追加でインストールするか、別PC/VNC経由で
実行してください（README.md参照）。

キー操作:
  r : ROIを選択し直す
  b : 基準フレーム(baseline_diff用)を複数枚撮影する（キャップ満杯状態で実行すること）
  a : カメラ位置ズレ検知の基準フレームを1枚撮影する
  s : 現在のROI・基準画像・設定値を保存する
  q : 終了
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capper_monitor.camera.factory import create_camera
from capper_monitor.config import load_config
from capper_monitor.detection.alignment_check import AlignmentChecker
from capper_monitor.detection.baseline_diff import BaselineDiffDetector
from capper_monitor.detection.edge_density import EdgeDensityDetector
from capper_monitor.detection.roi import RoiFractional
from capper_monitor.state_machine import AlarmState, AlarmStateMachine, DetectionDebouncer

WINDOW_MAIN = "capper-monitor calibrate (r:ROI b:baseline a:alignment-ref s:save q:quit)"
WINDOW_DEBUG = "detection debug"
WINDOW_ROI_SELECT = "ROI selector"

STATE_COLORS = {
    AlarmState.NORMAL: (0, 200, 0),
    AlarmState.STEADY: (0, 220, 220),
    AlarmState.BLINK: (0, 220, 220),
}
BLINK_OFF_COLOR = (60, 60, 60)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml", help="設定ファイルのパス")
    return parser.parse_args(argv)


def load_yaml_roundtrip(path: Path):
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.preserve_quotes = True
    with path.open("r", encoding="utf-8") as f:
        data = yaml.load(f)
    return yaml, data


def save_yaml_roundtrip(yaml, data, path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f)


def make_baseline_detector(roi: RoiFractional, bd_cfg, reference_edges=None) -> BaselineDiffDetector:
    return BaselineDiffDetector(
        roi=roi,
        dilate_kernel=bd_cfg.dilate_kernel,
        canny_low=bd_cfg.canny_low,
        canny_high=bd_cfg.canny_high,
        blur_kernel=bd_cfg.blur_kernel,
        density_threshold=bd_cfg.density_threshold,
        reference_edges=reference_edges,
    )


def make_fallback_detector(roi: RoiFractional, ed_cfg) -> EdgeDensityDetector:
    return EdgeDensityDetector(
        roi=roi,
        canny_low=ed_cfg.canny_low,
        canny_high=ed_cfg.canny_high,
        blur_kernel=ed_cfg.blur_kernel,
        density_threshold=ed_cfg.density_threshold,
        adaptive=ed_cfg.adaptive,
    )


def main(argv=None) -> int:
    args = parse_args(argv)
    config_path = Path(args.config)
    config = load_config(config_path)
    yaml, raw = load_yaml_roundtrip(config_path)

    camera = create_camera(config.camera)
    camera.open()

    roi = RoiFractional(
        config.detection.roi.x, config.detection.roi.y, config.detection.roi.w, config.detection.roi.h
    )
    bd_cfg = config.detection.baseline_diff
    ed_cfg = config.detection.edge_density
    ac_cfg = config.detection.alignment_check

    baseline_detector = make_baseline_detector(
        roi, bd_cfg, BaselineDiffDetector.load_reference(bd_cfg.reference_path)
    )
    fallback_detector = make_fallback_detector(roi, ed_cfg)

    alignment_checker = AlignmentChecker(
        roi=RoiFractional(ac_cfg.roi.x, ac_cfg.roi.y, ac_cfg.roi.w, ac_cfg.roi.h),
        correlation_threshold=ac_cfg.correlation_threshold,
        reference_gray=AlignmentChecker.load_reference(ac_cfg.reference_path),
    )

    debouncer = DetectionDebouncer(config.detection.debounce.on_delay_s, config.detection.debounce.off_delay_s)
    blink_interval_s = config.detection.refill_detection.blink_interval_ms / 1000.0
    state_machine = AlarmStateMachine(debouncer, blink_interval_s)

    try:
        cv2.namedWindow(WINDOW_MAIN)
    except cv2.error:
        print(
            "cv2.imshow が使用できません。GUI対応版の opencv-python が必要です。"
            "README.md の現場調整ツールの注意事項を確認してください。",
            file=sys.stderr,
        )
        camera.close()
        return 1

    print(__doc__)

    try:
        while True:
            frame = camera.read()
            if frame is None:
                time.sleep(0.05)
                continue

            detector = baseline_detector if baseline_detector.is_ready else fallback_detector
            result = detector.detect(frame)
            sm_result = state_machine.update(result.line_visible, False, False, now=time.monotonic())

            display = frame.copy()
            x0, y0, x1, y1 = roi.to_pixels(frame.shape)
            cv2.rectangle(display, (x0, y0), (x1, y1), (255, 0, 0), 2)

            color = STATE_COLORS[sm_result.state]
            if sm_result.state == AlarmState.BLINK and not sm_result.output_on:
                color = BLINK_OFF_COLOR
            cv2.circle(display, (30, 30), 15, color, -1)

            cv2.putText(
                display,
                f"{sm_result.state.value.upper()} score={result.score:.4f} detector={type(detector).__name__}",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

            if alignment_checker.is_ready:
                align_result = alignment_checker.check(frame)
                cv2.putText(
                    display,
                    f"alignment corr={align_result.correlation:.3f} ok={align_result.ok}",
                    (10, 85),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                )
            else:
                cv2.putText(
                    display,
                    "位置ズレ基準未取得 (aキーで取得)",
                    (10, 85),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 0, 255),
                    1,
                )

            cv2.imshow(WINDOW_MAIN, display)
            if result.debug_frame is not None:
                cv2.imshow(WINDOW_DEBUG, result.debug_frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

            elif key == ord("r"):
                x, y, w, h = cv2.selectROI(WINDOW_ROI_SELECT, frame, showCrosshair=True)
                cv2.destroyWindow(WINDOW_ROI_SELECT)
                if w > 0 and h > 0:
                    height, width = frame.shape[0], frame.shape[1]
                    roi = RoiFractional(x / width, y / height, w / width, h / height)
                    baseline_detector = make_baseline_detector(roi, bd_cfg)
                    fallback_detector = make_fallback_detector(roi, ed_cfg)
                    raw["detection"]["roi"] = {"x": roi.x, "y": roi.y, "w": roi.w, "h": roi.h}
                    print(f"ROIを更新しました: x={roi.x:.3f} y={roi.y:.3f} w={roi.w:.3f} h={roi.h:.3f}")
                    print("ROIサイズが変わったため基準画像は破棄されました。bキーで基準フレームを再取得してください。")

            elif key == ord("b"):
                print(f"基準フレームを{bd_cfg.num_calibration_frames}枚撮影します。キャップ満杯状態にしてください...")
                frames = []
                for _ in range(bd_cfg.num_calibration_frames):
                    f = camera.read()
                    if f is not None:
                        frames.append(f)
                    time.sleep(0.05)
                if frames:
                    baseline_detector.build_reference_from_frames(frames)
                    print("基準フレームを取得しました。sキーで保存してください。")
                else:
                    print("カメラからフレームを取得できませんでした。")

            elif key == ord("a"):
                f = camera.read()
                if f is not None:
                    alignment_checker.build_reference_from_frame(f)
                    print("位置ズレ検知の基準フレームを取得しました。sキーで保存してください。")

            elif key == ord("s"):
                if baseline_detector.is_ready:
                    baseline_detector.save_reference(bd_cfg.reference_path)
                    print(f"基準画像を保存しました: {bd_cfg.reference_path}")
                if alignment_checker.is_ready:
                    alignment_checker.save_reference(ac_cfg.reference_path)
                    print(f"位置ズレ基準画像を保存しました: {ac_cfg.reference_path}")
                save_yaml_roundtrip(yaml, raw, config_path)
                print(f"設定を保存しました: {config_path}")
    finally:
        camera.close()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
