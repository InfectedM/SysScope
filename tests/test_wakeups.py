import json
from sysscope.collector import wakeups

TIMERS = json.dumps([
    {"next": 1784770740000000, "last": 1784768940128735, "left": 1800000000,
     "unit": "phpsessionclean.timer", "activates": "phpsessionclean.service"},
    {"next": None, "last": None, "left": None,
     "unit": "x.timer", "activates": "x.service"},
])


def test_parse_timers_micros_to_seconds():
    t = wakeups.parse_timers(TIMERS)
    assert t[0]["unit"] == "phpsessionclean.timer"
    assert t[0]["next"] == 1784770740          # micros -> segundos
    assert t[0]["activates"] == "phpsessionclean.service"
    assert t[1]["next"] == 0                    # None -> 0


def test_parse_timers_bad_json():
    assert wakeups.parse_timers("nope") == []


def test_read_cron(tmp_path):
    ct = tmp_path / "crontab"
    ct.write_text("# comentário\nSHELL=/bin/sh\n0 3 * * * root /x.sh\n\n")
    res = wakeups.read_cron([str(ct), str(tmp_path / "missing")])
    lines = [r["line"] for r in res]
    assert "0 3 * * * root /x.sh" in lines
    assert "# comentário" not in lines
    assert "" not in lines


def test_read_rtc(tmp_path):
    p = tmp_path / "wakealarm"; p.write_text("1784800000\n")
    assert wakeups.read_rtc_wakealarm(str(p)) == 1784800000
    empty = tmp_path / "empty"; empty.write_text("\n")
    assert wakeups.read_rtc_wakealarm(str(empty)) is None
    assert wakeups.read_rtc_wakealarm(str(tmp_path / "none")) is None


def test_read_cron_survives_non_utf8(tmp_path):
    p = tmp_path / "badenc"; p.write_bytes(b"\xff\xfe 0 3 * * * root /x.sh\n")
    res = wakeups.read_cron([str(p)])   # não deve lançar
    assert isinstance(res, list)
