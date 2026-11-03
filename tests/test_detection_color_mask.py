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


# --- 見本の色から範囲を学習する ---

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from capper_monitor.detection.color_mask import learn_hsv_range  # noqa: E402


def test_learn_range_from_red_sample_detects_red_and_rejects_silver():
    sample = make_frame(40, 40, color=(30, 30, 200))  # 赤テープ
    lower, upper = learn_hsv_range(sample)
    assert lower[0] > upper[0] or lower[0] <= upper[0]  # 範囲が作れる
    detector = ColorMaskDetector(roi=ROI, hsv_lower=lower, hsv_upper=upper, pixel_ratio_threshold=0.1)

    tape = make_frame(color=(190, 190, 195))
    x0, y0, x1, y1 = ROI.to_pixels(tape.shape)
    cv2.rectangle(tape, (x0, y0), (x1, y1), (30, 30, 200), -1)
    assert detector.detect(tape).line_visible is True
    assert detector.detect(make_frame(color=(190, 190, 195))).line_visible is False  # 銀色


def test_learn_range_is_tight_enough_to_reject_a_reddish_silver_cast():
    # 蛍光灯・ホワイトバランスで赤みを帯びた銀色: 色相は赤に近いが彩度が低い
    cast_silver = make_frame(color=(170, 175, 200))
    sample = make_frame(40, 40, color=(30, 30, 200))
    lower, upper = learn_hsv_range(sample)
    detector = ColorMaskDetector(roi=ROI, hsv_lower=lower, hsv_upper=upper, pixel_ratio_threshold=0.1)
    assert detector.detect(cast_silver).line_visible is False


def test_learn_range_handles_hue_wraparound_red():
    rng = np.random.default_rng(0)
    sample = np.zeros((30, 30, 3), dtype=np.uint8)
    sample[..., 2] = 200
    sample[..., 0] = rng.integers(0, 60, (30, 30))  # 色相が0側と180側の両方に散る赤
    sample[..., 1] = rng.integers(0, 20, (30, 30))
    lower, upper = learn_hsv_range(sample)
    assert lower[0] > upper[0]


def test_learn_range_rejects_a_sample_without_color():
    with pytest.raises(ValueError):
        learn_hsv_range(make_frame(40, 40, color=(200, 200, 200)))


def test_learn_range_rejects_a_mixed_sample():
    mixed = make_frame(40, 40, color=(30, 30, 200))
    mixed[:, :20] = (200, 30, 30)  # 赤と青が半分ずつ
    with pytest.raises(ValueError):
        learn_hsv_range(mixed)


# --- 映り込み・点状ノイズを数えない ---

def scattered_red_dots(frame):
    """ROI内に赤い点（2x2）を多数散らす。合計はしきい値を超えるが、まとまりはない。"""
    x0, y0, x1, y1 = ROI.to_pixels(frame.shape)
    for y in range(y0 + 1, y1 - 2, 5):
        for x in range(x0 + 1, x1 - 2, 5):
            frame[y:y + 2, x:x + 2] = (20, 20, 210)
    return frame


def make_clean_detector(open_kernel=3, min_blob_ratio=0.002):
    return ColorMaskDetector(
        roi=ROI, hsv_lower=WRAP_LOWER, hsv_upper=WRAP_UPPER, pixel_ratio_threshold=0.05,
        open_kernel=open_kernel, min_blob_ratio=min_blob_ratio,
    )


def test_scattered_reflection_dots_are_not_counted():
    frame = scattered_red_dots(make_frame(color=WHITE_BGR))
    assert make_clean_detector(0, 0.0).detect(frame).line_visible is True  # 従来は誤検知
    result = make_clean_detector().detect(frame)
    assert result.line_visible is False
    assert result.score == 0.0


def test_tape_band_is_still_detected_with_cleanup():
    frame = make_frame(color=WHITE_BGR)
    x0, y0, x1, y1 = ROI.to_pixels(frame.shape)
    cy = (y0 + y1) // 2
    cv2.rectangle(frame, (x0, cy - 4), (x1, cy + 4), RED_LOW_HUE_BGR, -1)
    assert make_clean_detector().detect(frame).line_visible is True


def test_mask_view_uses_the_cleaned_mask():
    frame = scattered_red_dots(make_frame(color=WHITE_BGR))
    x0, y0, x1, y1 = ROI.to_pixels(frame.shape)
    assert np.count_nonzero(make_clean_detector().mask_of(frame[y0:y1, x0:x1])) == 0


def test_learned_value_lower_bound_tolerates_darker_lighting():
    sample = make_frame(40, 40, color=(30, 30, 200))
    lower, upper = learn_hsv_range(sample)
    detector = ColorMaskDetector(roi=ROI, hsv_lower=lower, hsv_upper=upper, pixel_ratio_threshold=0.1)
    darker = make_frame(color=WHITE_BGR)
    x0, y0, x1, y1 = ROI.to_pixels(darker.shape)
    cv2.rectangle(darker, (x0, y0), (x1, y1), (17, 17, 115), -1)  # 照明が約6割に暗くなったテープ
    assert detector.detect(darker).line_visible is True
