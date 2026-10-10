from builder.agentic.tools.clock import Clock


def test_time_left_and_plan():
    t = [0.0]
    c = Clock(22, now=lambda: t[0])
    assert c.time_left()["minutes_left"] == 22 and c.time_left()["phase_now"] == "read"
    t[0] = 13 * 60
    assert c.time_left()["phase_now"] == "build" and c.time_left()["advice"] == "on budget"
    t[0] = 20 * 60
    assert c.time_left()["phase_now"] == "check_and_fix" and c.time_left()["advice"].startswith("finish now")
    assert c.plan()[-1]["by_minute"] == 22
    t[0] = 30 * 60
    assert c.time_left()["minutes_left"] == 0
