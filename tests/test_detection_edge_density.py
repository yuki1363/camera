from capper_monitor.detection.edge_density import EdgeDensityDetector
from capper_monitor.detection.roi import RoiFractional
from tests.helpers import draw_line_in_roi, make_frame

ROI = RoiFractional(0.3, 0.4, 0.4, 0.2)


def make_detector(**overrides):
    defaults = dict(
        roi=ROI,
        canny_low=50,
        canny_high=150,
        blur_kernel=5,
        density_threshold=0.08,
        adaptive=False,
    )
    defaults.update(overrides)
    return EdgeDensityDetector(**defaults)


def test_blank_frame_has_no_line():
    detector = make_detector()
    frame = make_frame()
    result = detector.detect(frame)
    assert result.line_visible is False


def test_line_inside_roi_is_detected():
    detector = make_detector(density_threshold=0.03)
    frame = make_frame()
    frame = draw_line_in_roi(frame, ROI, thickness=6)
    result = detector.detect(frame)
    assert result.line_visible is True
    assert result.score > 0.03


def test_line_outside_roi_is_not_detected():
    detector = make_detector()
    frame = make_frame()
    outside_roi = RoiFractional(0.0, 0.0, 0.1, 0.1)
    frame = draw_line_in_roi(frame, outside_roi, thickness=4)
    result = detector.detect(frame)
    assert result.line_visible is False


def test_adaptive_mode_runs_without_error():
    detector = make_detector(adaptive=True)
    frame = make_frame()
    frame = draw_line_in_roi(frame, ROI, thickness=6)
    result = detector.detect(frame)
    assert isinstance(result.score, float)
