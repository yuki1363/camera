from __future__ import annotations

import logging
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from capper_monitor.calibration import CalibrationError, CommandQueue, save_calibration, with_threshold
from capper_monitor.camera.factory import create_camera
from capper_monitor.config import AppConfig, ConfigError, RoiConfig
from capper_monitor.detection.baseline_diff import BaselineDiffDetector
from capper_monitor.detection.factory import (
    create_alignment_checker,
    create_detector,
    create_motion_detector,
    create_strategy,
)
from capper_monitor.detection.motion import MotionResult
from capper_monitor.detection.roi import RoiFractional
from capper_monitor.io.gpio import GpioResources, create_gpio_resources
from capper_monitor.logging_setup import log_event
from capper_monitor.runtime import SingletonLock, WatchdogNotifier
from capper_monitor.state_machine import AlarmStateMachine, DetectionDebouncer
from capper_monitor.web.frame_buffer import FrameBuffer

logger = logging.getLogger(__name__)

_NO_MOTION = MotionResult(motion_detected=False, ratio=0.0)

# 補充の動き量の「直近ピーク」を出す期間（秒）。しきい値を決める目安としてスマホ画面に出す
_MOTION_PEAK_WINDOW_S = 5.0

_POWEROFF_COMMAND = ["sudo", "-n", "/usr/bin/systemctl", "poweroff"]

_STRATEGY_LABELS = {"baseline_diff": "基準差分", "edge_density": "エッジ密度", "color_mask": "色マスク"}


class App:
    def __init__(self, config: AppConfig, gpio_pin_factory=None, config_path: Optional[str | Path] = None):
        self.config = config
        self._config_path = config_path
        # スマホからの調整で書き換わる検知設定（config自体はfrozenなので別に持つ）
        self._detection_cfg = config.detection
        self.camera = create_camera(config.camera)
        self.detector = create_detector(config.detection)
        self.alignment_checker = (
            create_alignment_checker(config.detection) if config.detection.alignment_check.enabled else None
        )
        self.motion_detector = (
            create_motion_detector(config.detection) if config.detection.refill_detection.enabled else None
        )

        debouncer = DetectionDebouncer(
            config.detection.debounce.on_delay_s, config.detection.debounce.off_delay_s
        )
        blink_interval_s = config.detection.refill_detection.blink_interval_ms / 1000.0
        self.state_machine = AlarmStateMachine(debouncer, blink_interval_s)

        self.gpio: GpioResources = create_gpio_resources(config.gpio, pin_factory=gpio_pin_factory)
        self.frame_buffer: Optional[FrameBuffer] = FrameBuffer() if config.web.enabled else None
        self._calibration_enabled = config.web.enabled and config.web.calibration_enabled
        self._shutdown_enabled = config.web.enabled and config.web.shutdown_enabled
        self._commands: Optional[CommandQueue] = (
            CommandQueue() if self._calibration_enabled or self._shutdown_enabled else None
        )
        self._poweroff = _run_poweroff

        self._lock = SingletonLock(config.app.lock_file_path)
        self._watchdog = WatchdogNotifier(enabled=config.app.watchdog_enabled)

        self._running = False
        self._consecutive_camera_failures = 0
        self._backoff_s = config.app.camera_retry.initial_backoff_s
        self._detection_error_active = False
        self._last_detection_error_log_at = 0.0
        self._last_reason = "startup"
        self._last_score: Optional[float] = None
        self._last_correlation: Optional[float] = None
        self._last_motion: MotionResult = _NO_MOTION
        self._motion_history: deque = deque()

    def run(self, install_signal_handlers: bool = True) -> None:
        self._lock.acquire()
        try:
            self._run_locked(install_signal_handlers)
        finally:
            self._lock.release()

    def _run_locked(self, install_signal_handlers: bool) -> None:
        previous_sigint = previous_sigterm = None
        if install_signal_handlers:
            previous_sigint = signal.signal(signal.SIGINT, self._handle_stop_signal)
            previous_sigterm = signal.signal(signal.SIGTERM, self._handle_stop_signal)
        try:
            self.camera.open()
            if self.frame_buffer is not None:
                self._start_web_server()

            self._watchdog.notify_ready()
            logger.info("capper_monitor 起動しました")
            self._running = True
            while self._running:
                loop_start = time.monotonic()
                self._tick()
                self._watchdog.notify_watchdog()
                elapsed = time.monotonic() - loop_start
                remaining = self.config.app.loop_interval_s - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        finally:
            if install_signal_handlers:
                signal.signal(signal.SIGINT, previous_sigint)
                signal.signal(signal.SIGTERM, previous_sigterm)
            self._shutdown()

    def _handle_stop_signal(self, signum, frame) -> None:
        self._running = False

    def _tick(self) -> None:
        frame = self._read_frame_with_retry()
        if frame is None:
            return
        self._process_frame(frame)
        if self._commands is not None:
            self._commands.drain(lambda name, **kwargs: self._handle_command(name, frame, **kwargs))

    def _process_frame(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        reset_requested = self.gpio.reset_button.is_active or self.gpio.plc_reset_input.is_active

        if self.alignment_checker is not None and self.alignment_checker.is_ready:
            alignment = self.alignment_checker.check(frame)
            self._last_correlation = alignment.correlation
            if not alignment.ok:
                log_event(
                    logger, logging.WARNING, "camera_misalignment_detected", correlation=f"{alignment.correlation:.3f}"
                )
                self._apply_reset_only(reset_requested, now)
                # 映像は止めない（スマホで見ながら位置ズレ基準を撮り直せるように）
                self._publish(frame, "camera_misalignment")
                return

        try:
            detection_result = self.detector.detect(frame)
        except RuntimeError as exc:
            self._log_detection_error(str(exc))
            self._apply_reset_only(reset_requested, now)
            self._publish(frame, "detection_error")
            return
        self._clear_detection_error()
        self._last_score = detection_result.score

        motion_result = self.motion_detector.detect(frame) if self.motion_detector is not None else _NO_MOTION
        self._record_motion(motion_result, now)

        result = self.state_machine.update(
            raw_line_visible=detection_result.line_visible,
            motion_detected=motion_result.motion_detected,
            reset_requested=reset_requested,
            now=now,
        )
        self.gpio.alarm_output.set(result.output_on)

        if result.transitioned:
            self._last_reason = result.reason
            log_event(
                logger,
                logging.INFO,
                "alarm_state_changed",
                state=result.state.value,
                reason=result.reason,
                score=f"{detection_result.score:.4f}",
                motion=motion_result.motion_detected,
            )

        self._publish(frame, self._last_reason)

    def _apply_reset_only(self, reset_requested: bool, now: float) -> None:
        """検知結果を信用できないフレーム（位置ズレ・検知エラー）でも、リセットだけは
        常に独立して効かせる。デバウンサには触れずNORMALへ即座に強制する。"""
        if not reset_requested:
            return
        result = self.state_machine.force_normal(reason="reset")
        self.gpio.alarm_output.set(result.output_on)
        if result.transitioned:
            self._last_reason = result.reason
            log_event(
                logger, logging.INFO, "alarm_state_changed", state=result.state.value, reason=result.reason
            )

    def _log_detection_error(self, message: str) -> None:
        now = time.monotonic()
        if not self._detection_error_active:
            log_event(logger, logging.ERROR, "detection_error", message=message)
            self._detection_error_active = True
            self._last_detection_error_log_at = now
        elif now - self._last_detection_error_log_at >= 30.0:
            log_event(logger, logging.ERROR, "detection_error_persisting", message=message)
            self._last_detection_error_log_at = now

    def _clear_detection_error(self) -> None:
        if self._detection_error_active:
            log_event(logger, logging.INFO, "detection_error_cleared")
            self._detection_error_active = False

    def _record_motion(self, result: MotionResult, now: float) -> None:
        self._last_motion = result
        self._motion_history.append((now, result.ratio))
        while self._motion_history and now - self._motion_history[0][0] > _MOTION_PEAK_WINDOW_S:
            self._motion_history.popleft()

    def _motion_peak(self) -> float:
        return max((ratio for _, ratio in self._motion_history), default=0.0)

    def _publish(self, frame: np.ndarray, reason: str) -> None:
        if self.frame_buffer is None:
            return
        web_cfg = self.config.web
        resized = cv2.resize(frame, (web_cfg.stream_width, web_cfg.stream_height))
        self._draw_overlay(resized)
        ok, buf = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), web_cfg.jpeg_quality])
        if ok:
            self.frame_buffer.update_frame(buf.tobytes())

        cfg = self._detection_cfg
        self.frame_buffer.update_status(
            state=self.state_machine.state.value,
            reason=reason,
            timestamp=time.time(),
            score=self._last_score,
            threshold=getattr(self.detector, "threshold", None),
            detector=getattr(self.detector, "strategy_name", type(self.detector).__name__),
            configured_strategy=cfg.strategy,
            baseline_ready=isinstance(self.detector, BaselineDiffDetector) and self.detector.is_ready,
            alignment_ready=self.alignment_checker is not None and self.alignment_checker.is_ready,
            alignment_correlation=self._last_correlation,
            calibration_enabled=self._calibration_enabled,
            shutdown_enabled=self._shutdown_enabled,
            roi={"x": cfg.roi.x, "y": cfg.roi.y, "w": cfg.roi.w, "h": cfg.roi.h},
            motion_enabled=self.motion_detector is not None,
            motion_ratio=self._last_motion.ratio,
            motion_peak=self._motion_peak(),
            motion_threshold=cfg.refill_detection.motion_ratio,
            motion_detected=self._last_motion.motion_detected,
            motion_roi=_roi_dict(cfg.refill_detection.roi),
        )

    def _draw_overlay(self, image: np.ndarray) -> None:
        cfg = self._detection_cfg
        _draw_roi(image, cfg.roi, (255, 200, 0), "ROI")
        if self.alignment_checker is not None:
            _draw_roi(image, cfg.alignment_check.roi, (255, 0, 255), "ALIGN")
        if self.motion_detector is not None and cfg.refill_detection.roi is not None:
            _draw_roi(image, cfg.refill_detection.roi, (0, 200, 0), "MOTION")

    def _handle_command(self, name: str, frame: np.ndarray, **kwargs) -> dict:
        handlers = {
            "set_roi": self._cmd_set_roi,
            "set_threshold": self._cmd_set_threshold,
            "set_motion_roi": self._cmd_set_motion_roi,
            "set_motion_ratio": self._cmd_set_motion_ratio,
            "capture_baseline": self._cmd_capture_baseline,
            "capture_alignment": self._cmd_capture_alignment,
            "save": self._cmd_save,
        }
        if name == "shutdown":
            if not self._shutdown_enabled:
                raise CalibrationError("シャットダウン機能は無効です（web.shutdown_enabled: false）")
            return self._cmd_shutdown(frame)
        handler = handlers.get(name)
        if handler is None:
            raise CalibrationError(f"未知の操作です: {name}")
        if not self._calibration_enabled:
            raise CalibrationError("調整機能は無効です（web.calibration_enabled: false）")
        return handler(frame, **kwargs)

    def _cmd_set_motion_roi(self, frame: np.ndarray, x: float, y: float, w: float, h: float) -> dict:
        if self.motion_detector is None:
            raise CalibrationError("補充の動き検知（detection.refill_detection）が無効です")
        roi = RoiConfig(x=x, y=y, w=w, h=h)
        try:
            roi.validate("roi")
        except ConfigError as exc:
            raise CalibrationError(str(exc)) from exc
        refill = replace(self._detection_cfg.refill_detection, roi=roi)
        self._detection_cfg = replace(self._detection_cfg, refill_detection=refill)
        self.motion_detector = create_motion_detector(self._detection_cfg)
        self._motion_history.clear()
        log_event(logger, logging.INFO, "calibration_motion_roi_updated", x=f"{x:.3f}", y=f"{y:.3f}", w=f"{w:.3f}", h=f"{h:.3f}")
        return {"message": "補充の動きを見る範囲を更新しました。「保存」で確定してください。"}

    def _cmd_set_motion_ratio(self, frame: np.ndarray, value: float) -> dict:
        if self.motion_detector is None:
            raise CalibrationError("補充の動き検知（detection.refill_detection）が無効です")
        if not (0.0 < value < 1.0):
            raise CalibrationError("動きのしきい値は0より大きく1より小さい値にしてください")
        refill = replace(self._detection_cfg.refill_detection, motion_ratio=value)
        self._detection_cfg = replace(self._detection_cfg, refill_detection=refill)
        self.motion_detector.motion_ratio = value
        log_event(logger, logging.INFO, "calibration_motion_ratio_updated", value=f"{value:.4f}")
        return {"message": f"動きのしきい値を {value:.4f} にしました。「保存」で確定してください。"}

    def _cmd_shutdown(self, frame: np.ndarray) -> dict:
        # 停止中にPLCへ「キャップ減少」を出しっぱなしにしないよう、先に出力をOFFにする
        self.gpio.alarm_output.set(False)
        log_event(logger, logging.WARNING, "shutdown_requested")
        self._poweroff()
        return {
            "message": "シャットダウンを開始しました。約20秒後、ラズパイの緑LEDが消えてから電源を抜いてください。"
        }

    def _cmd_set_roi(self, frame: np.ndarray, x: float, y: float, w: float, h: float) -> dict:
        roi = RoiConfig(x=x, y=y, w=w, h=h)
        try:
            roi.validate("roi")
        except ConfigError as exc:
            raise CalibrationError(str(exc)) from exc
        self._detection_cfg = replace(self._detection_cfg, roi=roi)
        # 保存済みの基準画像は旧ROIのサイズなので読み込まない
        self.detector = create_detector(self._detection_cfg, load_reference=False)
        log_event(logger, logging.INFO, "calibration_roi_updated", x=f"{x:.3f}", y=f"{y:.3f}", w=f"{w:.3f}", h=f"{h:.3f}")
        message = "ROIを更新しました。"
        if self._detection_cfg.strategy == "baseline_diff":
            message += "キャップ満杯の状態で「基準フレーム撮影」を押してください。"
        return {"message": message}

    def _cmd_set_threshold(self, frame: np.ndarray, value: float) -> dict:
        if not (0.0 < value < 1.0):
            raise CalibrationError("しきい値は0より大きく1より小さい値にしてください")
        name = self.detector.strategy_name
        self._detection_cfg = with_threshold(self._detection_cfg, name, value)
        self.detector.threshold = value
        log_event(logger, logging.INFO, "calibration_threshold_updated", detector=name, value=f"{value:.4f}")
        return {"message": f"しきい値を {value:.4f} にしました（{_STRATEGY_LABELS.get(name, name)}）"}

    def _cmd_capture_baseline(self, frame: np.ndarray) -> dict:
        cfg = self._detection_cfg
        if cfg.strategy != "baseline_diff":
            raise CalibrationError("detection.strategy が baseline_diff ではないため、基準フレームは使いません")
        count = cfg.baseline_diff.num_calibration_frames
        frames = [frame]
        for _ in range(count * 3):
            if len(frames) >= count:
                break
            next_frame = self.camera.read()
            if next_frame is not None:
                frames.append(next_frame)
        detector = create_strategy("baseline_diff", cfg, load_reference=False)
        detector.build_reference_from_frames(frames)
        self.detector = detector
        log_event(logger, logging.INFO, "calibration_baseline_captured", frames=len(frames))
        return {"message": f"基準フレームを{len(frames)}枚撮影しました。「保存」で確定してください。"}

    def _cmd_capture_alignment(self, frame: np.ndarray) -> dict:
        if self.alignment_checker is None:
            raise CalibrationError("位置ズレ検知（detection.alignment_check）が無効です")
        self.alignment_checker.build_reference_from_frame(frame)
        log_event(logger, logging.INFO, "calibration_alignment_captured")
        return {"message": "位置ズレ検知の基準を撮影しました。「保存」で確定してください。"}

    def _cmd_save(self, frame: np.ndarray) -> dict:
        if self._config_path is None:
            raise CalibrationError("設定ファイルの場所が分からないため保存できません")
        cfg = self._detection_cfg
        if cfg.strategy == "baseline_diff":
            if not (isinstance(self.detector, BaselineDiffDetector) and self.detector.is_ready):
                raise CalibrationError(
                    "基準フレームが未撮影です。キャップ満杯の状態で「基準フレーム撮影」を押してから保存してください。"
                )
            self.detector.save_reference(cfg.baseline_diff.reference_path)
        if self.alignment_checker is not None and self.alignment_checker.is_ready:
            self.alignment_checker.save_reference(cfg.alignment_check.reference_path)
        save_calibration(
            self._config_path,
            roi=cfg.roi,
            thresholds={
                "edge_density": cfg.edge_density.density_threshold,
                "baseline_diff": cfg.baseline_diff.density_threshold,
                "color_mask": cfg.color_mask.pixel_ratio_threshold,
            },
            motion_roi=cfg.refill_detection.roi,
            motion_ratio=cfg.refill_detection.motion_ratio,
        )
        log_event(logger, logging.INFO, "calibration_saved", path=self._config_path)
        return {"message": "保存しました。再起動後もこの設定で動作します。"}

    def _read_frame_with_retry(self) -> Optional[np.ndarray]:
        frame = self.camera.read()
        retry_cfg = self.config.app.camera_retry

        if frame is not None:
            if self._consecutive_camera_failures >= retry_cfg.fault_after_failures:
                log_event(logger, logging.INFO, "camera_recovered")
                if self.gpio.fault_output is not None:
                    self.gpio.fault_output.set(False)
            self._consecutive_camera_failures = 0
            self._backoff_s = retry_cfg.initial_backoff_s
            return frame

        self._consecutive_camera_failures += 1
        if self._consecutive_camera_failures == retry_cfg.fault_after_failures:
            log_event(
                logger, logging.CRITICAL, "camera_fault", consecutive_failures=self._consecutive_camera_failures
            )
            if self.gpio.fault_output is not None:
                self.gpio.fault_output.set(True)
        else:
            log_event(
                logger,
                logging.WARNING,
                "camera_read_failed",
                backoff_s=f"{self._backoff_s:.2f}",
                consecutive_failures=self._consecutive_camera_failures,
            )

        time.sleep(self._backoff_s)
        self._backoff_s = min(self._backoff_s * 2, retry_cfg.max_backoff_s)
        return None

    def _start_web_server(self) -> None:
        from capper_monitor.web.server import create_app, run_server

        app = create_app(self.frame_buffer, self.config.web, commands=self._commands)
        thread = threading.Thread(
            target=run_server,
            args=(app, self.config.web.host, self.config.web.port),
            daemon=True,
            name="capper-monitor-web",
        )
        thread.start()
        log_event(
            logger,
            logging.INFO,
            "web_server_started",
            port=self.config.web.port,
            calibration_enabled=self._commands is not None,
        )

    def _shutdown(self) -> None:
        try:
            self.gpio.alarm_output.set(False)
            if self.gpio.fault_output is not None:
                self.gpio.fault_output.set(False)
        finally:
            self.camera.close()
            self.gpio.close()
            self._watchdog.close()
        logger.info("capper_monitor を安全に終了しました")


def _draw_roi(image: np.ndarray, roi_cfg, color, label: str) -> None:
    x0, y0, x1, y1 = RoiFractional(roi_cfg.x, roi_cfg.y, roi_cfg.w, roi_cfg.h).to_pixels(image.shape)
    cv2.rectangle(image, (x0, y0), (x1 - 1, y1 - 1), color, 2)
    cv2.putText(image, label, (x0 + 3, max(y0 - 6, 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)


def _roi_dict(roi) -> Optional[dict]:
    return None if roi is None else {"x": roi.x, "y": roi.y, "w": roi.w, "h": roi.h}


def _run_poweroff() -> None:
    """sudoers で許可された `systemctl poweroff` だけを、パスワードなしで実行する。"""
    hint = "README の「シャットダウン用の sudo 設定」を行ったか確認してください。"
    try:
        result = subprocess.run(_POWEROFF_COMMAND, capture_output=True, text=True, timeout=10)
    except FileNotFoundError as exc:
        raise CalibrationError(f"sudo が見つかりません。{hint}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CalibrationError("シャットダウンの実行が時間内に終わりませんでした。") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise CalibrationError(f"シャットダウンを実行できませんでした（{detail}）。{hint}")
