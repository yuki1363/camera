from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Optional

import cv2
import numpy as np

from capper_monitor.camera.factory import create_camera
from capper_monitor.config import AppConfig
from capper_monitor.detection.factory import create_alignment_checker, create_detector, create_motion_detector
from capper_monitor.detection.motion import MotionResult
from capper_monitor.io.gpio import GpioResources, create_gpio_resources
from capper_monitor.logging_setup import log_event
from capper_monitor.runtime import SingletonLock, WatchdogNotifier
from capper_monitor.state_machine import AlarmStateMachine, DetectionDebouncer
from capper_monitor.web.frame_buffer import FrameBuffer

logger = logging.getLogger(__name__)

_NO_MOTION = MotionResult(motion_detected=False, ratio=0.0)


class App:
    def __init__(self, config: AppConfig, gpio_pin_factory=None):
        self.config = config
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

        self._lock = SingletonLock(config.app.lock_file_path)
        self._watchdog = WatchdogNotifier(enabled=config.app.watchdog_enabled)

        self._running = False
        self._consecutive_camera_failures = 0
        self._backoff_s = config.app.camera_retry.initial_backoff_s
        self._detection_error_active = False
        self._last_detection_error_log_at = 0.0

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
                frame = self._read_frame_with_retry()
                if frame is not None:
                    self._process_frame(frame)
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

    def _process_frame(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        reset_requested = self.gpio.reset_button.is_active or self.gpio.plc_reset_input.is_active

        if self.alignment_checker is not None and self.alignment_checker.is_ready:
            alignment = self.alignment_checker.check(frame)
            if not alignment.ok:
                log_event(
                    logger, logging.WARNING, "camera_misalignment_detected", correlation=f"{alignment.correlation:.3f}"
                )
                self._apply_reset_only(reset_requested, now)
                return

        try:
            detection_result = self.detector.detect(frame)
        except RuntimeError as exc:
            self._log_detection_error(str(exc))
            self._apply_reset_only(reset_requested, now)
            return
        self._clear_detection_error()

        motion_result = self.motion_detector.detect(frame) if self.motion_detector is not None else _NO_MOTION

        result = self.state_machine.update(
            raw_line_visible=detection_result.line_visible,
            motion_detected=motion_result.motion_detected,
            reset_requested=reset_requested,
            now=now,
        )
        self.gpio.alarm_output.set(result.output_on)

        if result.transitioned:
            log_event(
                logger,
                logging.INFO,
                "alarm_state_changed",
                state=result.state.value,
                reason=result.reason,
                score=f"{detection_result.score:.4f}",
                motion=motion_result.motion_detected,
            )

        if self.frame_buffer is not None:
            self._update_web_frame(frame, result.state.value, result.reason)

    def _apply_reset_only(self, reset_requested: bool, now: float) -> None:
        """検知結果を信用できないフレーム（位置ズレ・検知エラー）でも、リセットだけは
        常に独立して効かせる。デバウンサには触れずNORMALへ即座に強制する。"""
        if not reset_requested:
            return
        result = self.state_machine.force_normal(reason="reset")
        self.gpio.alarm_output.set(result.output_on)
        if result.transitioned:
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

    def _update_web_frame(self, frame: np.ndarray, state: str, reason: str) -> None:
        web_cfg = self.config.web
        resized = cv2.resize(frame, (web_cfg.stream_width, web_cfg.stream_height))
        ok, buf = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), web_cfg.jpeg_quality])
        if ok:
            self.frame_buffer.update_frame(buf.tobytes())
        self.frame_buffer.update_status(state=state, reason=reason, timestamp=time.time())

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

        app = create_app(self.frame_buffer, self.config.web)
        thread = threading.Thread(
            target=run_server,
            args=(app, self.config.web.host, self.config.web.port),
            daemon=True,
            name="capper-monitor-web",
        )
        thread.start()

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
