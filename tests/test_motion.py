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
