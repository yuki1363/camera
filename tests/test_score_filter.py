from capper_monitor.detection.score_filter import ScoreFilter


def feed(f, scores, threshold=0.1):
    return [f.update(s, threshold).line_visible for s in scores]


def test_single_outlier_does_not_switch():
    f = ScoreFilter(window=5, release_ratio=0.6)
    assert feed(f, [0.0, 0.0, 0.5, 0.0, 0.0]) == [False] * 5
    f = ScoreFilter(window=5, release_ratio=0.6)
    feed(f, [0.3] * 5)
    assert feed(f, [0.0, 0.3, 0.3]) == [True, True, True]


def test_scores_wobbling_around_the_threshold_do_not_flip():
    f = ScoreFilter(window=5, release_ratio=0.6)
    feed(f, [0.12] * 5)  # 見える
    wobble = [0.09, 0.11, 0.08, 0.10, 0.09, 0.11, 0.08] * 5  # しきい値0.1の上下を往復
    assert all(feed(f, wobble))


def test_release_below_release_threshold():
    f = ScoreFilter(window=1, release_ratio=0.6)
    assert feed(f, [0.12, 0.07, 0.061, 0.059]) == [True, True, True, False]


def test_window_1_and_ratio_1_is_the_old_behavior():
    f = ScoreFilter(window=1, release_ratio=1.0)
    assert feed(f, [0.05, 0.1, 0.09, 0.2, 0.0]) == [False, True, False, True, False]


def test_smoothed_score_and_release_threshold_are_reported():
    f = ScoreFilter(window=3, release_ratio=0.5)
    f.update(0.1, 0.2)
    f.update(0.3, 0.2)
    r = f.update(0.2, 0.2)
    assert abs(r.score - 0.2) < 1e-9
    assert abs(r.release_threshold - 0.1) < 1e-9


def test_clear_forgets_history_and_state():
    f = ScoreFilter(window=3, release_ratio=0.6)
    feed(f, [0.5, 0.5, 0.5])
    f.clear()
    assert f.update(0.0, 0.1).line_visible is False
