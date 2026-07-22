from sysscope.collector.power import parse_hdparm_c, is_spun_down, PowerReader

ACTIVE = "/dev/sde:\n drive state is:  active/idle\n"
STANDBY = "/dev/sdb:\n drive state is:  standby\n"
SLEEP = "/dev/sdc:\n drive state is:  sleeping\n"
UNKNOWN = "/dev/sdd:\n drive state is:  unknown\n"


def test_parse_states():
    assert parse_hdparm_c(ACTIVE) == "active"
    assert parse_hdparm_c(STANDBY) == "standby"
    assert parse_hdparm_c(SLEEP) == "sleeping"
    assert parse_hdparm_c(UNKNOWN) == "unknown"


def test_is_spun_down():
    assert is_spun_down("standby") is True
    assert is_spun_down("sleeping") is True
    assert is_spun_down("active") is False
    assert is_spun_down("unknown") is False


def test_power_reader_ok():
    pr = PowerReader(runner=lambda argv: STANDBY)
    assert pr.read("/dev/sdb") == "standby"


def test_power_reader_failure_returns_unknown():
    def boom(argv):
        raise RuntimeError("hdparm em falta")
    pr = PowerReader(runner=boom)
    assert pr.read("/dev/sdb") == "unknown"
