import cv2

from capper_monitor.detection.color_mask import ColorMaskDetector
from capper_monitor.detection.roi import RoiFractional
from tests.helpers import make_frame

ROI = RoiFractional(0.3, 0.4, 0.4, 0.2)

RED_BGR = (0, 0, 255)
RED_HSV_LOWER = (0, 100, 100)
RED_HSV_UPPER = (10, 255, 255)


def make_detector():
    return ColorMaskDetector(
        roi=ROI,
        hsv_lower=RED_HSV_LOWER,
        hsv_upper=RED_HSV_UPPER,
        pixel_ratio_threshold=0.10,
    )


def test_no_matching_color_is_not_detected():
    detector = make_detector()
    frame = make_frame(color=(200, 200, 200))
    result = detector.detect(frame)
    assert result.line_visible is False


def test_matching_color_inside_roi_is_detected():
    detector = make_detector()
    frame = make_frame(color=(200, 200, 200))
    x0, y0, x1, y1 = ROI.to_pixels(frame.shape)
    cv2.rectangle(frame, (x0, y0), (x1, y1), RED_BGR, -1)
    result = detector.detect(frame)
    assert result.line_visible is True


def test_matching_color_outside_roi_is_not_detected():
    detector = make_detector()
    frame = make_frame(color=(200, 200, 200))
    cv2.rectangle(frame, (0, 0), (10, 10), RED_BGR, -1)
    result = detector.detect(frame)
    assert result.line_visible is False


# --- 白キャップ＋赤ライン（色相が0/180をまたぐ赤の範囲指定） ---

WRAP_LOWER = (170, 80, 60)
WRAP_UPPER = (10, 255, 255)
WHITE_BGR = (235, 235, 235)
# OpenCVのHSVで色相が 0 付近の赤と 175 付近の赤（マゼンタ寄り）
RED_LOW_HUE_BGR = (20, 30, 200)
RED_HIGH_HUE_BGR = (60, 0, 200)


def make_wrap_detector():
    return ColorMaskDetector(
        roi=ROI,
        hsv_lower=WRAP_LOWER,
        hsv_upper=WRAP_UPPER,
        pixel_ratio_threshold=0.02,
    )


def draw_white_caps(frame):
    """白いキャップがぎっしり詰まった状態を模す（影のある白い円を敷き詰める）。"""
    frame[:] = (90, 90, 90)
    h, w = frame.shape[:2]
    for y in range(10, h, 22):
        for x in range(10, w, 22):
            cv2.circle(frame, (x, y), 10, WHITE_BGR, -1)
            cv2.circle(frame, (x, y), 10, (150, 150, 155), 1)
    return frame


def test_hue_wraparound_range_detects_both_ends_of_red():
    detector = make_wrap_detector()
    for bgr in (RED_LOW_HUE_BGR, RED_HIGH_HUE_BGR):
        frame = make_frame(color=WHITE_BGR)
        x0, y0, x1, y1 = ROI.to_pixels(frame.shape)
        cy = (y0 + y1) // 2
        cv2.rectangle(frame, (x0, cy - 3), (x1, cy + 3), bgr, -1)
        result = detector.detect(frame)
        assert result.line_visible is True, bgr
        assert 0.02 <= result.score < 1.0


def test_hue_wraparound_range_ignores_non_red_colors():
    detector = make_wrap_detector()
    for bgr in ((0, 200, 0), (200, 0, 0), (0, 200, 200)):  # 緑・青・黄
        frame = make_frame(color=bgr)
        assert detector.detect(frame).line_visible is False, bgr


def test_white_caps_are_not_detected_as_red_line():
    detector = make_wrap_detector()
    frame = draw_white_caps(make_frame())
    result = detector.detect(frame)
    assert result.line_visible is False
    assert result.score == 0.0


def test_red_line_between_white_caps_is_detected():
    detector = make_wrap_detector()
    frame = draw_white_caps(make_frame())
    x0, y0, x1, y1 = ROI.to_pixels(frame.shape)
    cy = (y0 + y1) // 2
    cv2.rectangle(frame, (x0, cy - 3), (x1, cy + 3), RED_LOW_HUE_BGR, -1)
    assert detector.detect(frame).line_visible is True


def test_red_outside_roi_is_ignored_with_wraparound_range():
    detector = make_wrap_detector()
    frame = draw_white_caps(make_frame())
    cv2.rectangle(frame, (0, 0), (40, 40), RED_HIGH_HUE_BGR, -1)
    assert detector.detect(frame).line_visible is False
