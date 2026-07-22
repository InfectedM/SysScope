from sysscope.common.config import Config, Disk
from sysscope.collector.disk_collector import DiskCollector

DISKS = [Disk("sde", "/dev/sde", "/media/HDD8TB", 8, 64)]


def make_cfg(**kw):
    base = dict(disks=DISKS, db_path=":x:", web_host="127.0.0.1", web_port=1,
                sample_interval=1.0, power_interval=1.0, idle_threshold=100.0,
                incident_window=6.0, retention_days=14)
    base.update(kw)
    return Config(**base)


def stats(reads):
    # linha de diskstats de sde com `reads` leituras
    return (f"   8      64 sde {reads} 0 {reads*8} 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n")


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def test_power_transition_triggers_spinup():
    clock = Clock()
    states = iter(["standby", "active"])
    power = type("P", (), {"read": lambda self, dev: next(states)})()
    reads = iter([stats(10), stats(20)])
    spinups, samples = [], []
    dc = DiskCollector(
        make_cfg(), power_reader=power,
        on_spinup=lambda ts, d, det: spinups.append((d, det)),
        on_sample=lambda ts, d, ps, r: samples.append((d, ps)),
        diskstats_reader=lambda: next(reads), clock=clock,
    )
    dc.poll()                 # standby, baseline
    clock.t += 1.0
    dc.poll()                 # active -> spin-up
    assert spinups == [("sde", "power")]
    assert len(samples) == 2


def test_no_spinup_when_staying_active():
    clock = Clock()
    power = type("P", (), {"read": lambda self, dev: "active"})()
    reads = iter([stats(10), stats(20), stats(30)])
    spinups = []
    dc = DiskCollector(
        make_cfg(), power_reader=power,
        on_spinup=lambda ts, d, det: spinups.append(d),
        on_sample=lambda *a: None,
        diskstats_reader=lambda: next(reads), clock=clock,
    )
    dc.poll(); clock.t += 1; dc.poll(); clock.t += 1; dc.poll()
    assert spinups == []


def test_inferred_spinup_when_power_unknown():
    clock = Clock()
    power = type("P", (), {"read": lambda self, dev: "unknown"})()
    # sem atividade por muito tempo, depois atividade
    reads = iter([stats(10), stats(10), stats(50)])
    spinups = []
    dc = DiskCollector(
        make_cfg(idle_threshold=1.5), power_reader=power,
        on_spinup=lambda ts, d, det: spinups.append((d, det)),
        on_sample=lambda *a: None,
        diskstats_reader=lambda: next(reads), clock=clock,
    )
    dc.poll()               # baseline, last_active=1000
    clock.t += 2.0          # 2s sem atividade (> idle_threshold)
    dc.poll()               # ainda sem atividade
    clock.t += 2.0
    dc.poll()               # atividade após inatividade -> inferido
    assert spinups == [("sde", "inferido")]
