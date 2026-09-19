from capper_monitor.config import GpioConfig, GpioInputConfig, GpioOutputConfig
from capper_monitor.io.gpio import AlarmOutput, DebouncedInput, create_gpio_resources


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
