from capper_monitor.detection.alignment_check import AlignmentChecker
from capper_monitor.detection.roi import RoiFractional
from tests.helpers import draw_fixed_clutter, make_frame

ROI = RoiFractional(0.0, 0.0, 0.2, 0.2)


def make_checker(threshold=0.6):
    return AlignmentChecker(roi=ROI, correlation_threshold=threshold)


def test_default_ok_when_no_reference_yet():
    checker = make_checker()
    frame = make_frame()
    result = checker.check(frame)
    assert result.ok is True


def test_identical_frame_has_high_correlation():
    checker = make_checker()
    frame = make_frame()
    draw_fixed_clutter(frame, center=(15, 15))
    checker.build_reference_from_frame(frame)

    result = checker.check(frame)
    assert result.ok is True
    assert result.correlation > 0.95


def test_misaligned_frame_has_low_correlation():
    checker = make_checker()
    reference_frame = make_frame()
    draw_fixed_clutter(reference_frame, center=(15, 15))
    checker.build_reference_from_frame(reference_frame)

    shifted_frame = make_frame()
    draw_fixed_clutter(shifted_frame, center=(35, 35))
    result = checker.check(shifted_frame)
    assert result.ok is False
