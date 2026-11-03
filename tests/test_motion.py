import cv2

from capper_monitor.detection.motion import MotionDetector
from tests.helpers import make_frame


def make_detector():
    return MotionDetector(motion_threshold=25, motion_ratio=0.05)


def test_first_frame_has_no_motion():
    detector = make_detector()
    result = detector.detect(make_frame())
    assert result.motion_detected is False


def test_identical_frames_have_no_motion():
    detector = make_detector()
    frame = make_frame()
    detector.detect(frame)
    result = detector.detect(frame.copy())
    assert result.motion_detected is False


def test_sustained_change_is_detected_as_motion():
    detector = make_detector()
    frame = make_frame()
    detector.detect(frame)

    last_result = None
    for i in range(4):
        moving_frame = make_frame()
        cv2.rectangle(moving_frame, (10 + i * 30, 10), (90 + i * 30, 90), (0, 0, 0), -1)
        last_result = detector.detect(moving_frame)
    assert last_result.motion_detected is True


def test_single_flicker_frame_does_not_trigger_motion():
    detector = make_detector()
    frame = make_frame()
    detector.detect(frame)
    detector.detect(frame.copy())

    flicker_frame = make_frame()
    cv2.rectangle(flicker_frame, (10, 10), (90, 90), (0, 0, 0), -1)
    result = detector.detect(flicker_frame)
    assert result.motion_detected is False


# --- 動きを見る範囲（ROI） ---

from capper_monitor.detection.roi import RoiFractional  # noqa: E402


def _drive(detector, draw_rect, step=10):
    """動く四角を描いたフレームを数枚流し、最後の結果を返す。"""
    detector.detect(make_frame())
    result = None
    for i in range(4):
        frame = make_frame()
        cv2.rectangle(frame, (draw_rect[0] + i * step, draw_rect[1]), (draw_rect[2] + i * step, draw_rect[3]), (0, 0, 0), -1)
        result = detector.detect(frame)
    return result


def test_motion_outside_roi_is_ignored():
    detector = MotionDetector(motion_threshold=25, motion_ratio=0.05, roi=RoiFractional(0.6, 0.6, 0.35, 0.35))
    result = _drive(detector, (5, 5, 60, 60))  # 左上だけで動く（ROIは右下）
    assert result.motion_detected is False
    assert result.ratio == 0.0


def test_motion_inside_roi_is_detected():
    detector = MotionDetector(motion_threshold=25, motion_ratio=0.05, roi=RoiFractional(0.0, 0.0, 0.5, 0.5))
    result = _drive(detector, (5, 5, 60, 60))
    assert result.motion_detected is True


def test_without_roi_motion_anywhere_counts():
    detector = make_detector()
    assert _drive(detector, (20, 120, 80, 180), step=20).motion_detected is True


def test_motion_ratio_can_be_changed_at_runtime():
    detector = make_detector()
    detector.motion_ratio = 0.9
    assert detector.motion_ratio == 0.9
    assert _drive(detector, (5, 5, 60, 60)).motion_detected is False
