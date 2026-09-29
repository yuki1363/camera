from __future__ import annotations

import glob
import logging
import re
from typing import Callable, Iterable, Optional, Union

from gpiozero import Button, DigitalOutputDevice

logger = logging.getLogger(__name__)

# 40ピンヘッダのGPIOを持つチップのラベル（優先順）。Pi 5はRP1、Pi 4以前はBCM。
_HEADER_CHIP_LABELS = ("pinctrl-rp1", "pinctrl-bcm2711", "pinctrl-bcm2835")


class GpioChipNotFoundError(RuntimeError):
    pass


def find_gpio_chip(chip_numbers: Iterable[int], get_label: Callable[[int], Optional[str]]) -> tuple[int, str]:
    """ラベルで40ピンヘッダのGPIOチップを探す。

    ラズパイ5のチップ番号はOS・カーネルの版で変わる（0, 4, 10番台など）ため、
    番号を決め打ちせずラベルで判定する。get_label が None を返すチップ（開けない等）は無視する。
    """
    labels = {}
    for number in sorted(chip_numbers):
        label = get_label(number)
        if label is not None:
            labels[number] = label
    for wanted in _HEADER_CHIP_LABELS:
        for number, label in labels.items():
            if label == wanted:
                return number, label
    found = ", ".join(f"gpiochip{n}={label!r}" for n, label in labels.items()) or "なし"
    raise GpioChipNotFoundError(
        "40ピンヘッダのGPIOチップが見つかりません（見つかったチップ: "
        f"{found}）。`gpiodetect` の結果を確認し、config.yaml の gpio.chip に番号を指定してください。"
    )


def _list_chip_numbers() -> list[int]:
    numbers = []
    for path in glob.glob("/dev/gpiochip*"):
        m = re.fullmatch(r"/dev/gpiochip(\d+)", path)
        if m:
            numbers.append(int(m.group(1)))
    return numbers


def _read_chip_label(number: int) -> Optional[str]:
    import lgpio

    try:
        handle = lgpio.gpiochip_open(number)
    except lgpio.error:
        return None
    try:
        _status, _lines, _name, label = lgpio.gpio_get_chip_info(handle)
        return label
    except lgpio.error:
        return None
    finally:
        lgpio.gpiochip_close(handle)


def _create_lgpio_factory(chip: int):
    """指定したgpiochipを開くLGPIOFactoryを作る。

    gpiozero 2.0 / 2.0.1（Raspberry Pi OSのaptパッケージ版）の LGPIOFactory.__init__ は
    chip 引数を無視して常に gpiochip4（Pi 5）か gpiochip0 を開く不具合がある
    （2.0.1.post3 で修正）。チップ番号が 0/4 以外になるOSでも動くよう、初期化を自前で行う。
    """
    import lgpio
    from gpiozero.pins.lgpio import LGPIOFactory, LGPIOPin
    from gpiozero.pins.local import LocalPiFactory

    class _ChipLGPIOFactory(LGPIOFactory):
        def __init__(self, chip_number: int):
            LocalPiFactory.__init__(self)
            self._handle = lgpio.gpiochip_open(chip_number)
            self._chip = chip_number
            self.pin_class = LGPIOPin

    return _ChipLGPIOFactory(chip)


def build_pin_factory(name: str, chip: Union[str, int] = "auto"):
    if name == "lgpio":
        if chip == "auto":
            number, label = find_gpio_chip(_list_chip_numbers(), _read_chip_label)
            logger.info("GPIOチップ gpiochip%d (%s) を使用します", number, label)
        else:
            number = int(chip)
            logger.info("GPIOチップ gpiochip%d を使用します（gpio.chip で指定）", number)
        return _create_lgpio_factory(number)
    if name == "mock":
        from gpiozero.pins.mock import MockFactory

        return MockFactory()
    raise ValueError(f"未知のpin_factoryです: {name!r}")


class AlarmOutput:
    """PLCへのリレー出力（絶縁モジュール経由）。起動時は必ず安全側=OFFで初期化する。"""

    def __init__(self, pin: int, active_high: bool, pin_factory=None):
        self._device = DigitalOutputDevice(
            pin, active_high=active_high, initial_value=False, pin_factory=pin_factory
        )

    def set(self, on: bool) -> None:
        if on:
            self._device.on()
        else:
            self._device.off()

    @property
    def is_on(self) -> bool:
        return bool(self._device.value)

    def close(self) -> None:
        self._device.close()


class DebouncedInput:
    """物理リセットボタン・PLCリセット信号の両方に共通利用する、デバウンス付きGPIO入力。"""

    def __init__(self, pin: int, pull_up: bool, bounce_time_s: float, pin_factory=None):
        self._button = Button(
            pin,
            pull_up=pull_up,
            bounce_time=bounce_time_s if bounce_time_s > 0 else None,
            pin_factory=pin_factory,
        )

    @property
    def is_active(self) -> bool:
        return self._button.is_active

    def close(self) -> None:
        self._button.close()


class GpioResources:
    """アプリのGPIOリソース一式をまとめて生成・解放するコンテナ。"""

    def __init__(
        self,
        alarm_output: AlarmOutput,
        reset_button: DebouncedInput,
        plc_reset_input: DebouncedInput,
        fault_output: Optional[AlarmOutput] = None,
    ):
        self.alarm_output = alarm_output
        self.reset_button = reset_button
        self.plc_reset_input = plc_reset_input
        self.fault_output = fault_output

    def close(self) -> None:
        self.alarm_output.close()
        self.reset_button.close()
        self.plc_reset_input.close()
        if self.fault_output is not None:
            self.fault_output.close()

    def __enter__(self) -> "GpioResources":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def create_gpio_resources(gpio_config, pin_factory=None) -> GpioResources:
    if pin_factory is None:
        pin_factory = build_pin_factory(gpio_config.pin_factory, gpio_config.chip)

    alarm_output = AlarmOutput(
        gpio_config.alarm_output.pin, gpio_config.alarm_output.active_high, pin_factory=pin_factory
    )
    reset_button = DebouncedInput(
        gpio_config.reset_button.pin,
        gpio_config.reset_button.pull_up,
        gpio_config.reset_button.bounce_time_s,
        pin_factory=pin_factory,
    )
    plc_reset_input = DebouncedInput(
        gpio_config.plc_reset_input.pin,
        gpio_config.plc_reset_input.pull_up,
        gpio_config.plc_reset_input.bounce_time_s,
        pin_factory=pin_factory,
    )
    fault_output = None
    if gpio_config.fault_output is not None:
        fault_output = AlarmOutput(
            gpio_config.fault_output.pin, gpio_config.fault_output.active_high, pin_factory=pin_factory
        )

    return GpioResources(
        alarm_output=alarm_output,
        reset_button=reset_button,
        plc_reset_input=plc_reset_input,
        fault_output=fault_output,
    )
