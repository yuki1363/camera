from capper_monitor.detection.baseline_diff import BaselineDiffDetector
from capper_monitor.detection.roi import RoiFractional
from tests.helpers import add_noise, draw_fixed_clutter, draw_line_in_roi, make_frame, shift_brightness

ROI = RoiFractional(0.3, 0.4, 0.4, 0.2)


def make_detector(**overrides):
    defaults = dict(
        roi=ROI,
        dilate_kernel=3,
        canny_low=50,
        canny_high=150,
        blur_kernel=5,
        density_threshold=0.05,
    )
    defaults.update(overrides)
    return BaselineDiffDetector(**defaults)


def make_reference_frames(n=10, clutter=False, seed=0):
    frames = []
    for i in range(n):
        frame = make_frame()
        if clutter:
            draw_fixed_clutter(frame, center=(60, 90))
        frame = add_noise(frame, sigma=3.0, seed=seed + i)
        frames.append(frame)
    return frames


def test_not_ready_until_reference_built():
    detector = make_detector()
    assert detector.is_ready is False


def test_no_line_after_calibration_is_not_detected():
    detector = make_detector()
    detector.build_reference_from_frames(make_reference_frames())
    assert detector.is_ready is True

    frame = add_noise(make_frame(), sigma=3.0, seed=99)
    result = detector.detect(frame)
    assert result.line_visible is False


def test_line_after_calibration_is_detected():
    detector = make_detector()
    detector.build_reference_from_frames(make_reference_frames())

    frame = add_noise(make_frame(), sigma=3.0, seed=99)
    frame = draw_line_in_roi(frame, ROI, thickness=4)
    result = detector.detect(frame)
    assert result.line_visible is True


def test_brightness_shift_without_line_does_not_false_positive():
    detector = make_detector()
    detector.build_reference_from_frames(make_reference_frames())

    frame = add_noise(make_frame(), sigma=3.0, seed=99)
    frame = shift_brightness(frame, delta=30)
    result = detector.detect(frame)
    assert result.line_visible is False


def test_line_still_detected_under_brightness_shift():
    detector = make_detector()
    detector.build_reference_from_frames(make_reference_frames())

    frame = add_noise(make_frame(), sigma=3.0, seed=99)
    frame = draw_line_in_roi(frame, ROI, thickness=4)
    frame = shift_brightness(frame, delta=30)
    result = detector.detect(frame)
    assert result.line_visible is True


def test_fixed_background_clutter_in_reference_does_not_false_positive():
    detector = make_detector()
    detector.build_reference_from_frames(make_reference_frames(clutter=True))

    frame = make_frame()
    draw_fixed_clutter(frame, center=(60, 90))
    frame = add_noise(frame, sigma=3.0, seed=99)
    result = detector.detect(frame)
    assert result.line_visible is False


def test_save_and_load_reference_roundtrip(tmp_path):
    detector = make_detector()
    detector.build_reference_from_frames(make_reference_frames())
    path = tmp_path / "baseline_reference.npy"
    detector.save_reference(path)

    loaded = BaselineDiffDetector.load_reference(path)
    assert loaded is not None

    other = make_detector(reference_edges=loaded)
    frame = add_noise(make_frame(), sigma=3.0, seed=99)
    frame = draw_line_in_roi(frame, ROI, thickness=4)
    result = other.detect(frame)
    assert result.line_visible is True
