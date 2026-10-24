from app.ratelimit import SlidingWindowLimiter


def test_window_slides():
    lim = SlidingWindowLimiter(2, 10)
    assert lim.allow("a", 0) and lim.allow("a", 1)
    assert not lim.allow("a", 2)
    assert lim.allow("b", 2)
    assert lim.allow("a", 10.5)
