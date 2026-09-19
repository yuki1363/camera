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
