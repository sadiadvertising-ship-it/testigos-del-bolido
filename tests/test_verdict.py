from testigos.verdict import decide


def test_fast_is_natural():
    v = decide(40.4, 0.4)
    assert v.kind == 'natural'


def test_slow_and_long_is_reentry():
    assert decide(7.6, 0.2, duration_s=60).kind == 'reentry'


def test_slow_but_brief_is_inconclusive():
    assert decide(7.6, 0.2, duration_s=4).kind == 'inconclusive'


def test_wide_error_is_inconclusive():
    assert decide(10.0, 2.0).kind == 'inconclusive'


def test_meteorites_only_when_it_ends_low_and_slow():
    assert decide(17.5, 0.5, end_height_km=14.9, end_speed_kms=4.3).meteorites_possible
    assert not decide(40.4, 0.4, end_height_km=53.6, end_speed_kms=38.3).meteorites_possible
