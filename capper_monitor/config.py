from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import yaml


class ConfigError(Exception):
    pass


def _get(d: dict, key: str, path: str):
    if key not in d:
        raise ConfigError(f"設定に必須キーがありません: {path}.{key}")
    return d[key]


def _as_dict(value, path: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{path} はマッピング(dict)である必要があります")
    return value


@dataclass(frozen=True)
class RoiConfig:
    x: float
    y: float
    w: float
    h: float

    def validate(self, path: str) -> None:
        for name, value in (("x", self.x), ("y", self.y), ("w", self.w), ("h", self.h)):
            if not (0.0 <= value <= 1.0):
                raise ConfigError(f"{path}.{name} は0.0〜1.0の範囲で指定してください: {value}")
        if self.w <= 0 or self.h <= 0:
            raise ConfigError(f"{path}.w/h は正の値である必要があります")
        if self.x + self.w > 1.0 + 1e-9:
            raise ConfigError(f"{path}: x+w が1.0を超えています")
        if self.y + self.h > 1.0 + 1e-9:
            raise ConfigError(f"{path}: y+h が1.0を超えています")


@dataclass(frozen=True)
class OpenCvCameraConfig:
    device_index: int = 0
    width: int = 1280
    height: int = 720
    fourcc: Optional[str] = "MJPG"

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ConfigError("camera.opencv.width/height は正の値である必要があります")


@dataclass(frozen=True)
class Picamera2CameraConfig:
    width: int = 1280
    height: int = 720
    auto_exposure: bool = False
    auto_white_balance: bool = False
    autofocus_mode: str = "auto"
    lens_position: Optional[float] = None
    ae_awb_convergence_s: float = 1.5
    awb_mode: str = "auto"

    _VALID_AWB_MODES = ("auto", "tungsten", "fluorescent", "indoor", "daylight", "cloudy", "custom")

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ConfigError("camera.picamera2.width/height は正の値である必要があります")
        if self.ae_awb_convergence_s <= 0:
            raise ConfigError("camera.picamera2.ae_awb_convergence_s は正の値である必要があります")
        if self.awb_mode not in self._VALID_AWB_MODES:
            raise ConfigError(
                f"camera.picamera2.awb_mode は {self._VALID_AWB_MODES} のいずれかである"
                f"必要があります: {self.awb_mode!r}"
            )
        if self.autofocus_mode not in ("auto", "manual", "continuous"):
            raise ConfigError(
                "camera.picamera2.autofocus_mode は 'auto'/'manual'/'continuous' の"
                f"いずれかである必要があります: {self.autofocus_mode!r}"
            )
        if self.autofocus_mode == "manual" and self.lens_position is None:
            raise ConfigError(
                "camera.picamera2.autofocus_mode が 'manual' の場合は"
                "lens_position を指定してください"
            )


@dataclass(frozen=True)
class CameraConfig:
    backend: str = "opencv"
    opencv: OpenCvCameraConfig = field(default_factory=OpenCvCameraConfig)
    picamera2: Picamera2CameraConfig = field(default_factory=Picamera2CameraConfig)

    def validate(self) -> None:
        if self.backend not in ("opencv", "picamera2"):
            raise ConfigError(f"camera.backend は 'opencv' か 'picamera2' である必要があります: {self.backend!r}")
        self.opencv.validate()
        self.picamera2.validate()


@dataclass(frozen=True)
class DebounceConfig:
    on_delay_ms: int = 500
    off_delay_ms: int = 1000

    def validate(self) -> None:
        if self.on_delay_ms < 0 or self.off_delay_ms < 0:
            raise ConfigError("detection.debounce の値は0以上である必要があります")

    @property
    def on_delay_s(self) -> float:
        return self.on_delay_ms / 1000.0

    @property
    def off_delay_s(self) -> float:
        return self.off_delay_ms / 1000.0


@dataclass(frozen=True)
class EdgeDensityConfig:
    canny_low: int = 50
    canny_high: int = 150
    blur_kernel: int = 5
    density_threshold: float = 0.08
    adaptive: bool = True

    def validate(self) -> None:
        if self.blur_kernel < 1 or self.blur_kernel % 2 == 0:
            raise ConfigError("detection.edge_density.blur_kernel は正の奇数である必要があります")
        if not (0.0 < self.density_threshold < 1.0):
            raise ConfigError("detection.edge_density.density_threshold は0〜1の範囲で指定してください")
        if self.canny_low < 0 or self.canny_high <= self.canny_low:
            raise ConfigError("detection.edge_density.canny_low/canny_high の指定が不正です")


@dataclass(frozen=True)
class ColorMaskConfig:
    hsv_lower: tuple = (0, 0, 200)
    hsv_upper: tuple = (180, 40, 255)
    pixel_ratio_threshold: float = 0.10

    def validate(self) -> None:
        if len(self.hsv_lower) != 3 or len(self.hsv_upper) != 3:
            raise ConfigError("detection.color_mask.hsv_lower/hsv_upper は3要素である必要があります")
        for name, values in (("hsv_lower", self.hsv_lower), ("hsv_upper", self.hsv_upper)):
            h, s, v = values
            if not (0 <= h <= 180 and 0 <= s <= 255 and 0 <= v <= 255):
                raise ConfigError(
                    f"detection.color_mask.{name} は [H:0〜180, S:0〜255, V:0〜255] の範囲で指定してください: {list(values)}"
                )
        if self.hsv_lower[1] > self.hsv_upper[1] or self.hsv_lower[2] > self.hsv_upper[2]:
            raise ConfigError("detection.color_mask の彩度(S)・明度(V)は hsv_lower ≦ hsv_upper にしてください")
        if not (0.0 < self.pixel_ratio_threshold < 1.0):
            raise ConfigError("detection.color_mask.pixel_ratio_threshold は0〜1の範囲で指定してください")


@dataclass(frozen=True)
class BaselineDiffConfig:
    num_calibration_frames: int = 15
    dilate_kernel: int = 3
    canny_low: int = 50
    canny_high: int = 150
    blur_kernel: int = 5
    density_threshold: float = 0.05
    reference_path: str = "config/baseline_reference.npy"

    def validate(self) -> None:
        if self.num_calibration_frames < 1:
            raise ConfigError("detection.baseline_diff.num_calibration_frames は1以上である必要があります")
        if self.dilate_kernel < 1 or self.dilate_kernel % 2 == 0:
            raise ConfigError("detection.baseline_diff.dilate_kernel は正の奇数である必要があります")
        if self.blur_kernel < 1 or self.blur_kernel % 2 == 0:
            raise ConfigError("detection.baseline_diff.blur_kernel は正の奇数である必要があります")
        if not (0.0 < self.density_threshold < 1.0):
            raise ConfigError("detection.baseline_diff.density_threshold は0〜1の範囲で指定してください")
        if self.canny_low < 0 or self.canny_high <= self.canny_low:
            raise ConfigError("detection.baseline_diff.canny_low/canny_high の指定が不正です")


@dataclass(frozen=True)
class AlignmentCheckConfig:
    enabled: bool = True
    roi: RoiConfig = field(default_factory=lambda: RoiConfig(0.02, 0.02, 0.15, 0.15))
    correlation_threshold: float = 0.6
    reference_path: str = "config/alignment_reference.npy"

    def validate(self) -> None:
        self.roi.validate("detection.alignment_check.roi")
        if not (0.0 <= self.correlation_threshold <= 1.0):
            raise ConfigError("detection.alignment_check.correlation_threshold は0〜1の範囲で指定してください")


@dataclass(frozen=True)
class RefillDetectionConfig:
    enabled: bool = True
    motion_threshold: int = 25
    motion_ratio: float = 0.05
    blink_interval_ms: int = 400

    def validate(self) -> None:
        if not (0 <= self.motion_threshold <= 255):
            raise ConfigError("detection.refill_detection.motion_threshold は0〜255の範囲で指定してください")
        if not (0.0 < self.motion_ratio < 1.0):
            raise ConfigError("detection.refill_detection.motion_ratio は0〜1の範囲で指定してください")
        if self.blink_interval_ms <= 0:
            raise ConfigError("detection.refill_detection.blink_interval_ms は正の値である必要があります")


@dataclass(frozen=True)
class DetectionConfig:
    strategy: str = "baseline_diff"
    fallback_strategy: str = "edge_density"
    roi: RoiConfig = field(default_factory=lambda: RoiConfig(0.35, 0.40, 0.30, 0.20))
    edge_density: EdgeDensityConfig = field(default_factory=EdgeDensityConfig)
    color_mask: ColorMaskConfig = field(default_factory=ColorMaskConfig)
    baseline_diff: BaselineDiffConfig = field(default_factory=BaselineDiffConfig)
    debounce: DebounceConfig = field(default_factory=DebounceConfig)
    alignment_check: AlignmentCheckConfig = field(default_factory=AlignmentCheckConfig)
    refill_detection: RefillDetectionConfig = field(default_factory=RefillDetectionConfig)

    def validate(self) -> None:
        valid_strategies = ("edge_density", "color_mask", "baseline_diff")
        if self.strategy not in valid_strategies:
            raise ConfigError(f"detection.strategy が不正です: {self.strategy!r}")
        if self.fallback_strategy not in valid_strategies:
            raise ConfigError(f"detection.fallback_strategy が不正です: {self.fallback_strategy!r}")
        self.roi.validate("detection.roi")
        self.edge_density.validate()
        self.color_mask.validate()
        self.baseline_diff.validate()
        self.debounce.validate()
        self.alignment_check.validate()
        self.refill_detection.validate()


@dataclass(frozen=True)
class GpioOutputConfig:
    pin: int
    active_high: bool = True


@dataclass(frozen=True)
class GpioInputConfig:
    pin: int
    pull_up: bool = True
    bounce_time_ms: int = 100

    def validate(self, path: str) -> None:
        if self.bounce_time_ms < 0:
            raise ConfigError(f"{path}.bounce_time_ms は0以上である必要があります")

    @property
    def bounce_time_s(self) -> float:
        return self.bounce_time_ms / 1000.0


@dataclass(frozen=True)
class GpioConfig:
    pin_factory: str = "lgpio"
    chip: Union[str, int] = "auto"
    alarm_output: GpioOutputConfig = field(default_factory=lambda: GpioOutputConfig(pin=17))
    reset_button: GpioInputConfig = field(default_factory=lambda: GpioInputConfig(pin=27, bounce_time_ms=200))
    plc_reset_input: GpioInputConfig = field(default_factory=lambda: GpioInputConfig(pin=22, bounce_time_ms=50))
    fault_output: Optional[GpioOutputConfig] = None

    def validate(self) -> None:
        if self.pin_factory not in ("lgpio", "mock"):
            raise ConfigError(f"gpio.pin_factory は 'lgpio' か 'mock' である必要があります: {self.pin_factory!r}")
        if self.chip != "auto" and not (isinstance(self.chip, int) and not isinstance(self.chip, bool) and self.chip >= 0):
            raise ConfigError(f"gpio.chip は 'auto' か0以上の整数で指定してください: {self.chip!r}")
        self.reset_button.validate("gpio.reset_button")
        self.plc_reset_input.validate("gpio.plc_reset_input")

        pins = {
            "alarm_output": self.alarm_output.pin,
            "reset_button": self.reset_button.pin,
            "plc_reset_input": self.plc_reset_input.pin,
        }
        if self.fault_output is not None:
            pins["fault_output"] = self.fault_output.pin
        seen: dict = {}
        for role, pin in pins.items():
            if pin in seen:
                raise ConfigError(f"gpio: ピン番号が重複しています ({seen[pin]} と {role} が両方pin={pin})")
            seen[pin] = role


@dataclass(frozen=True)
class CameraRetryConfig:
    initial_backoff_ms: int = 200
    max_backoff_ms: int = 5000
    fault_after_failures: int = 20

    def validate(self) -> None:
        if self.initial_backoff_ms <= 0 or self.max_backoff_ms < self.initial_backoff_ms:
            raise ConfigError("app.camera_retry の backoff 設定が不正です")
        if self.fault_after_failures < 1:
            raise ConfigError("app.camera_retry.fault_after_failures は1以上である必要があります")

    @property
    def initial_backoff_s(self) -> float:
        return self.initial_backoff_ms / 1000.0

    @property
    def max_backoff_s(self) -> float:
        return self.max_backoff_ms / 1000.0


@dataclass(frozen=True)
class AppRuntimeConfig:
    loop_interval_ms: int = 100
    camera_retry: CameraRetryConfig = field(default_factory=CameraRetryConfig)
    lock_file_path: str = "/tmp/capper-monitor.lock"
    watchdog_enabled: bool = True

    def validate(self) -> None:
        if self.loop_interval_ms <= 0:
            raise ConfigError("app.loop_interval_ms は正の値である必要があります")
        self.camera_retry.validate()

    @property
    def loop_interval_s(self) -> float:
        return self.loop_interval_ms / 1000.0


@dataclass(frozen=True)
class WebConfig:
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    stream_width: int = 640
    stream_height: int = 360
    stream_fps: int = 8
    jpeg_quality: int = 70
    calibration_enabled: bool = True

    def validate(self) -> None:
        if not (1 <= self.port <= 65535):
            raise ConfigError("web.port は1〜65535の範囲で指定してください")
        if self.stream_width <= 0 or self.stream_height <= 0:
            raise ConfigError("web.stream_width/stream_height は正の値である必要があります")
        if self.stream_fps <= 0:
            raise ConfigError("web.stream_fps は正の値である必要があります")
        if not (1 <= self.jpeg_quality <= 100):
            raise ConfigError("web.jpeg_quality は1〜100の範囲で指定してください")


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    console: bool = True
    file_path: Optional[str] = "/var/log/capper-monitor/capper-monitor.log"
    max_bytes: int = 1_048_576
    backup_count: int = 3

    def validate(self) -> None:
        if self.level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ConfigError(f"logging.level が不正です: {self.level!r}")


@dataclass(frozen=True)
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    gpio: GpioConfig = field(default_factory=GpioConfig)
    app: AppRuntimeConfig = field(default_factory=AppRuntimeConfig)
    web: WebConfig = field(default_factory=WebConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def validate(self) -> None:
        self.camera.validate()
        self.detection.validate()
        self.gpio.validate()
        self.app.validate()
        self.web.validate()
        self.logging.validate()


def _roi_from_dict(d: dict, path: str) -> RoiConfig:
    d = _as_dict(d, path)
    return RoiConfig(
        x=float(_get(d, "x", path)),
        y=float(_get(d, "y", path)),
        w=float(_get(d, "w", path)),
        h=float(_get(d, "h", path)),
    )


def _resolve_path(value: str, base_dir: Path) -> str:
    """相対パスは設定ファイルのあるディレクトリ基準で解決する（CWD依存を避けるため）。"""
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)
    return str((base_dir / candidate).resolve())


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"設定ファイルが見つかりません: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"設定ファイルのYAML構文エラー: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("設定ファイルのトップレベルはマッピング(dict)である必要があります")

    try:
        config = _build_config(raw, base_dir=path.resolve().parent)
    except ConfigError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ConfigError(f"設定ファイルの読み込みに失敗しました: {exc}") from exc

    config.validate()
    return config


def _build_config(raw: dict, base_dir: Path) -> AppConfig:
    camera_raw = _as_dict(raw.get("camera", {}), "camera")
    opencv_raw = _as_dict(camera_raw.get("opencv", {}), "camera.opencv")
    picamera2_raw = _as_dict(camera_raw.get("picamera2", {}), "camera.picamera2")
    camera = CameraConfig(
        backend=camera_raw.get("backend", "opencv"),
        opencv=OpenCvCameraConfig(
            device_index=int(opencv_raw.get("device_index", 0)),
            width=int(opencv_raw.get("width", 1280)),
            height=int(opencv_raw.get("height", 720)),
            fourcc=opencv_raw.get("fourcc", "MJPG"),
        ),
        picamera2=Picamera2CameraConfig(
            width=int(picamera2_raw.get("width", 1280)),
            height=int(picamera2_raw.get("height", 720)),
            auto_exposure=bool(picamera2_raw.get("auto_exposure", False)),
            auto_white_balance=bool(picamera2_raw.get("auto_white_balance", False)),
            autofocus_mode=picamera2_raw.get("autofocus_mode", "auto"),
            lens_position=(
                float(picamera2_raw["lens_position"]) if "lens_position" in picamera2_raw else None
            ),
            ae_awb_convergence_s=float(picamera2_raw.get("ae_awb_convergence_s", 1.5)),
            awb_mode=picamera2_raw.get("awb_mode", "auto"),
        ),
    )

    detection_raw = _as_dict(raw.get("detection", {}), "detection")
    roi = _roi_from_dict(detection_raw.get("roi", {"x": 0.35, "y": 0.40, "w": 0.30, "h": 0.20}), "detection.roi")

    ed_raw = _as_dict(detection_raw.get("edge_density", {}), "detection.edge_density")
    edge_density = EdgeDensityConfig(
        canny_low=int(ed_raw.get("canny_low", 50)),
        canny_high=int(ed_raw.get("canny_high", 150)),
        blur_kernel=int(ed_raw.get("blur_kernel", 5)),
        density_threshold=float(ed_raw.get("density_threshold", 0.08)),
        adaptive=bool(ed_raw.get("adaptive", True)),
    )

    cm_raw = _as_dict(detection_raw.get("color_mask", {}), "detection.color_mask")
    color_mask = ColorMaskConfig(
        hsv_lower=tuple(cm_raw.get("hsv_lower", [0, 0, 200])),
        hsv_upper=tuple(cm_raw.get("hsv_upper", [180, 40, 255])),
        pixel_ratio_threshold=float(cm_raw.get("pixel_ratio_threshold", 0.10)),
    )

    bd_raw = _as_dict(detection_raw.get("baseline_diff", {}), "detection.baseline_diff")
    baseline_diff = BaselineDiffConfig(
        num_calibration_frames=int(bd_raw.get("num_calibration_frames", 15)),
        dilate_kernel=int(bd_raw.get("dilate_kernel", 3)),
        canny_low=int(bd_raw.get("canny_low", 50)),
        canny_high=int(bd_raw.get("canny_high", 150)),
        blur_kernel=int(bd_raw.get("blur_kernel", 5)),
        density_threshold=float(bd_raw.get("density_threshold", 0.05)),
        reference_path=_resolve_path(
            bd_raw.get("reference_path", "config/baseline_reference.npy"), base_dir
        ),
    )

    debounce_raw = _as_dict(detection_raw.get("debounce", {}), "detection.debounce")
    debounce = DebounceConfig(
        on_delay_ms=int(debounce_raw.get("on_delay_ms", 500)),
        off_delay_ms=int(debounce_raw.get("off_delay_ms", 1000)),
    )

    ac_raw = _as_dict(detection_raw.get("alignment_check", {}), "detection.alignment_check")
    alignment_check = AlignmentCheckConfig(
        enabled=bool(ac_raw.get("enabled", True)),
        roi=_roi_from_dict(ac_raw.get("roi", {"x": 0.02, "y": 0.02, "w": 0.15, "h": 0.15}), "detection.alignment_check.roi"),
        correlation_threshold=float(ac_raw.get("correlation_threshold", 0.6)),
        reference_path=_resolve_path(
            ac_raw.get("reference_path", "config/alignment_reference.npy"), base_dir
        ),
    )

    rd_raw = _as_dict(detection_raw.get("refill_detection", {}), "detection.refill_detection")
    refill_detection = RefillDetectionConfig(
        enabled=bool(rd_raw.get("enabled", True)),
        motion_threshold=int(rd_raw.get("motion_threshold", 25)),
        motion_ratio=float(rd_raw.get("motion_ratio", 0.05)),
        blink_interval_ms=int(rd_raw.get("blink_interval_ms", 400)),
    )

    detection = DetectionConfig(
        strategy=detection_raw.get("strategy", "baseline_diff"),
        fallback_strategy=detection_raw.get("fallback_strategy", "edge_density"),
        roi=roi,
        edge_density=edge_density,
        color_mask=color_mask,
        baseline_diff=baseline_diff,
        debounce=debounce,
        alignment_check=alignment_check,
        refill_detection=refill_detection,
    )

    gpio_raw = _as_dict(raw.get("gpio", {}), "gpio")
    alarm_raw = _as_dict(gpio_raw.get("alarm_output", {"pin": 17}), "gpio.alarm_output")
    reset_btn_raw = _as_dict(gpio_raw.get("reset_button", {"pin": 27}), "gpio.reset_button")
    plc_reset_raw = _as_dict(gpio_raw.get("plc_reset_input", {"pin": 22}), "gpio.plc_reset_input")
    fault_raw = gpio_raw.get("fault_output")

    gpio = GpioConfig(
        pin_factory=gpio_raw.get("pin_factory", "lgpio"),
        chip=gpio_raw.get("chip", "auto"),
        alarm_output=GpioOutputConfig(
            pin=int(_get(alarm_raw, "pin", "gpio.alarm_output")),
            active_high=bool(alarm_raw.get("active_high", True)),
        ),
        reset_button=GpioInputConfig(
            pin=int(_get(reset_btn_raw, "pin", "gpio.reset_button")),
            pull_up=bool(reset_btn_raw.get("pull_up", True)),
            bounce_time_ms=int(reset_btn_raw.get("bounce_time_ms", 200)),
        ),
        plc_reset_input=GpioInputConfig(
            pin=int(_get(plc_reset_raw, "pin", "gpio.plc_reset_input")),
            pull_up=bool(plc_reset_raw.get("pull_up", True)),
            bounce_time_ms=int(plc_reset_raw.get("bounce_time_ms", 50)),
        ),
        fault_output=(
            GpioOutputConfig(
                pin=int(_get(_as_dict(fault_raw, "gpio.fault_output"), "pin", "gpio.fault_output")),
                active_high=bool(fault_raw.get("active_high", True)),
            )
            if fault_raw is not None
            else None
        ),
    )

    app_raw = _as_dict(raw.get("app", {}), "app")
    retry_raw = _as_dict(app_raw.get("camera_retry", {}), "app.camera_retry")
    app_runtime = AppRuntimeConfig(
        loop_interval_ms=int(app_raw.get("loop_interval_ms", 100)),
        camera_retry=CameraRetryConfig(
            initial_backoff_ms=int(retry_raw.get("initial_backoff_ms", 200)),
            max_backoff_ms=int(retry_raw.get("max_backoff_ms", 5000)),
            fault_after_failures=int(retry_raw.get("fault_after_failures", 20)),
        ),
        lock_file_path=app_raw.get("lock_file_path", "/tmp/capper-monitor.lock"),
        watchdog_enabled=bool(app_raw.get("watchdog_enabled", True)),
    )

    web_raw = _as_dict(raw.get("web", {}), "web")
    web = WebConfig(
        enabled=bool(web_raw.get("enabled", False)),
        host=web_raw.get("host", "0.0.0.0"),
        port=int(web_raw.get("port", 8080)),
        stream_width=int(web_raw.get("stream_width", 640)),
        stream_height=int(web_raw.get("stream_height", 360)),
        stream_fps=int(web_raw.get("stream_fps", 8)),
        jpeg_quality=int(web_raw.get("jpeg_quality", 70)),
        calibration_enabled=bool(web_raw.get("calibration_enabled", True)),
    )

    logging_raw = _as_dict(raw.get("logging", {}), "logging")
    logging_cfg = LoggingConfig(
        level=logging_raw.get("level", "INFO"),
        console=bool(logging_raw.get("console", True)),
        file_path=logging_raw.get("file_path", "/var/log/capper-monitor/capper-monitor.log"),
        max_bytes=int(logging_raw.get("max_bytes", 1_048_576)),
        backup_count=int(logging_raw.get("backup_count", 3)),
    )

    return AppConfig(
        camera=camera,
        detection=detection,
        gpio=gpio,
        app=app_runtime,
        web=web,
        logging=logging_cfg,
    )
