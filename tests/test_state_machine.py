from capper_monitor.state_machine import AlarmState, AlarmStateMachine, DetectionDebouncer


def make_machine(on_delay_s=0.5, off_delay_s=1.0, blink_interval_s=0.4):
    debouncer = DetectionDebouncer(on_delay_s=on_delay_s, off_delay_s=off_delay_s)
    return AlarmStateMachine(debouncer, blink_interval_s=blink_interval_s)


def test_debouncer_requires_sustained_on_delay():
    d = DetectionDebouncer(on_delay_s=0.5, off_delay_s=1.0)
    assert d.update(True, now=0.0) is False
    assert d.update(True, now=0.3) is False
    assert d.update(True, now=0.6) is True


def test_debouncer_flicker_resets_pending_timer():
    d = DetectionDebouncer(on_delay_s=0.5, off_delay_s=1.0)
    assert d.update(True, now=0.0) is False
    assert d.update(False, now=0.3) is False
    assert d.update(True, now=0.4) is False
    assert d.update(True, now=0.85) is False
    assert d.update(True, now=0.95) is True


def test_debouncer_requires_sustained_off_delay():
    d = DetectionDebouncer(on_delay_s=0.5, off_delay_s=1.0)
    d.update(True, now=0.0)
    assert d.update(True, now=0.6) is True
    assert d.update(False, now=0.8) is True
    assert d.update(False, now=1.7) is True
    assert d.update(False, now=1.9) is False


def test_line_detected_transitions_to_steady_after_on_delay():
    m = make_machine()
    r = m.update(raw_line_visible=True, motion_detected=False, reset_requested=False, now=0.0)
    assert r.state == AlarmState.NORMAL
    assert r.output_on is False

    r = m.update(raw_line_visible=True, motion_detected=False, reset_requested=False, now=0.6)
    assert r.state == AlarmState.STEADY
    assert r.output_on is True
    assert r.transitioned is True
    assert r.reason == "line_detected"


def test_line_cleared_returns_to_normal_after_off_delay():
    m = make_machine()
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    assert m.state == AlarmState.STEADY

    r = m.update(False, False, False, now=0.7)
    assert r.state == AlarmState.STEADY

    r = m.update(False, False, False, now=1.8)
    assert r.state == AlarmState.NORMAL
    assert r.output_on is False
    assert r.reason == "line_cleared"


def test_motion_detected_switches_to_blink_while_line_visible():
    m = make_machine()
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    assert m.state == AlarmState.STEADY

    r = m.update(True, True, False, now=0.7)
    assert r.state == AlarmState.BLINK
    assert r.reason == "refill_in_progress"


def test_reset_forces_normal_immediately_even_before_off_delay():
    m = make_machine()
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    assert m.state == AlarmState.STEADY

    r = m.update(True, False, reset_requested=True, now=0.61)
    assert r.state == AlarmState.NORMAL
    assert r.output_on is False
    assert r.reason == "reset"


def test_reset_does_not_prevent_reassertion_if_line_still_visible():
    m = make_machine()
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    assert m.state == AlarmState.STEADY

    m.update(True, False, reset_requested=True, now=0.61)
    assert m.state == AlarmState.NORMAL

    r = m.update(True, False, reset_requested=False, now=0.62)
    assert r.state == AlarmState.STEADY
    assert r.output_on is True


def test_blink_toggles_output_over_time():
    m = make_machine(blink_interval_s=0.4)
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    r = m.update(True, True, False, now=0.7)
    assert r.state == AlarmState.BLINK
    assert r.output_on is True

    r = m.update(True, True, False, now=0.7 + 0.5)
    assert r.output_on is False

    r = m.update(True, True, False, now=0.7 + 0.9)
    assert r.output_on is True


def test_startup_state_is_normal_with_output_off():
    m = make_machine()
    r = m.update(False, False, False, now=0.0)
    assert r.state == AlarmState.NORMAL
    assert r.output_on is False
    assert r.transitioned is False
    assert r.reason == "no_change"
