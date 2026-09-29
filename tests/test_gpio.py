from capper_monitor.config import GpioConfig, GpioInputConfig, GpioOutputConfig
import pytest

from capper_monitor.io.gpio import (
    AlarmOutput,
    DebouncedInput,
    GpioChipNotFoundError,
    build_pin_factory,
    create_gpio_resources,
    find_gpio_chip,
)


def test_alarm_output_starts_off_and_can_be_toggled(mock_pin_factory):
    output = AlarmOutput(pin=17, active_high=True, pin_factory=mock_pin_factory)
    try:
        assert output.is_on is False
        output.set(True)
        assert output.is_on is True
        output.set(False)
        assert output.is_on is False
    finally:
        output.close()


def test_alarm_output_respects_active_low_polarity(mock_pin_factory):
    output = AlarmOutput(pin=17, active_high=False, pin_factory=mock_pin_factory)
    try:
        pin = mock_pin_factory.pin(17)
        output.set(True)
        assert pin.state == 0
        output.set(False)
        assert pin.state == 1
    finally:
        output.close()


def test_debounced_input_reflects_pin_state(mock_pin_factory):
    input_ = DebouncedInput(pin=27, pull_up=True, bounce_time_s=0.0, pin_factory=mock_pin_factory)
    try:
        pin = mock_pin_factory.pin(27)
        pin.drive_high()
        assert input_.is_active is False
        pin.drive_low()
        assert input_.is_active is True
    finally:
        input_.close()


def test_create_gpio_resources_wires_all_devices(mock_pin_factory):
    cfg = GpioConfig(
        pin_factory="mock",
        alarm_output=GpioOutputConfig(pin=17, active_high=True),
        reset_button=GpioInputConfig(pin=27, pull_up=True, bounce_time_ms=0),
        plc_reset_input=GpioInputConfig(pin=22, pull_up=True, bounce_time_ms=0),
    )
    resources = create_gpio_resources(cfg, pin_factory=mock_pin_factory)
    try:
        assert resources.alarm_output.is_on is False
        assert resources.fault_output is None
    finally:
        resources.close()


def test_create_gpio_resources_with_fault_output(mock_pin_factory):
    cfg = GpioConfig(
        pin_factory="mock",
        alarm_output=GpioOutputConfig(pin=17, active_high=True),
        reset_button=GpioInputConfig(pin=27, pull_up=True, bounce_time_ms=0),
        plc_reset_input=GpioInputConfig(pin=22, pull_up=True, bounce_time_ms=0),
        fault_output=GpioOutputConfig(pin=23, active_high=True),
    )
    resources = create_gpio_resources(cfg, pin_factory=mock_pin_factory)
    try:
        assert resources.fault_output is not None
        assert resources.fault_output.is_on is False
    finally:
        resources.close()


# --- GPIOチップの自動判定（実機の /dev/gpiochip* の代わりに偽のラベル表を渡す） ---

# 実機（Raspberry Pi 5）で gpiochip0/4 が無く 11〜15 のみだった構成を模す（どれがRP1かは仮の割当て）
PI5_CHIPS_11_TO_15 = {
    11: "gpio-brcmstb@107d508500",
    12: "gpio-brcmstb@107d508520",
    13: "pinctrl-rp1",
    14: "gpio-brcmstb@107d517c00",
    15: "gpio-brcmstb@107d517c20",
}


def test_find_gpio_chip_picks_rp1_regardless_of_number():
    assert find_gpio_chip(PI5_CHIPS_11_TO_15, PI5_CHIPS_11_TO_15.get) == (13, "pinctrl-rp1")


def test_find_gpio_chip_falls_back_to_bcm_on_older_pi():
    chips = {0: "pinctrl-bcm2711", 1: "raspberrypi-exp-gpio"}
    assert find_gpio_chip(chips, chips.get) == (0, "pinctrl-bcm2711")


def test_find_gpio_chip_ignores_chips_that_cannot_be_opened():
    chips = {0: None, 4: "pinctrl-rp1"}
    assert find_gpio_chip(chips, chips.get) == (4, "pinctrl-rp1")


def test_find_gpio_chip_raises_with_found_labels_when_no_header_chip():
    chips = {11: "gpio-brcmstb@107d508500"}
    with pytest.raises(GpioChipNotFoundError, match="gpiochip11"):
        find_gpio_chip(chips, chips.get)


def test_lgpio_factory_opens_the_requested_chip_number(monkeypatch):
    """gpiozero 2.0.1 は chip 引数を無視して 0/4 を開くため、指定番号で開くことを確認する。"""
    lgpio = pytest.importorskip("lgpio")
    opened, closed = [], []
    monkeypatch.setattr(lgpio, "gpiochip_open", lambda chip: opened.append(chip) or 1000 + chip)
    monkeypatch.setattr(lgpio, "gpiochip_close", lambda handle: closed.append(handle))

    factory = build_pin_factory("lgpio", 15)
    try:
        assert opened == [15]
        assert factory.chip == 15
    finally:
        factory.close()
    assert closed == [1015]


def test_lgpio_factory_auto_uses_detected_chip(monkeypatch):
    lgpio = pytest.importorskip("lgpio")
    import capper_monitor.io.gpio as gpio_module

    monkeypatch.setattr(gpio_module, "_list_chip_numbers", lambda: [11, 15])
    monkeypatch.setattr(gpio_module, "_read_chip_label", {11: "gpio-brcmstb@107d517c00", 15: "pinctrl-rp1"}.get)
    opened = []
    monkeypatch.setattr(lgpio, "gpiochip_open", lambda chip: opened.append(chip) or 1)
    monkeypatch.setattr(lgpio, "gpiochip_close", lambda handle: None)

    factory = build_pin_factory("lgpio", "auto")
    factory.close()
    assert opened == [15]
