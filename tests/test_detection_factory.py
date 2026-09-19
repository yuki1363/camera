from capper_monitor.config import DetectionConfig
from capper_monitor.detection.edge_density import EdgeDensityDetector
from capper_monitor.detection.factory import create_alignment_checker, create_detector, create_motion_detector


def test_create_detector_falls_back_when_baseline_not_ready(tmp_path):
    cfg = DetectionConfig()
    cfg.baseline_diff.reference_path == cfg.baseline_diff.reference_path  # no-op sanity
    object.__setattr__(cfg.baseline_diff, "reference_path", str(tmp_path / "missing.npy"))

    detector = create_detector(cfg)
    assert isinstance(detector, EdgeDensityDetector)


def test_create_alignment_checker_and_motion_detector_do_not_raise():
    cfg = DetectionConfig()
    checker = create_alignment_checker(cfg)
    motion = create_motion_detector(cfg)
    assert checker is not None
    assert motion is not None
