from __future__ import annotations

from typing import Optional

from gpiozero import Button, DigitalOutputDevice


def build_pin_factory(name: str):
    if name == "lgpio":
        from gpiozero.pins.lgpio import LGPIOFactory

        return LGPIOFactory()
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
        pin_factory = build_pin_factory(gpio_config.pin_factory)

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
