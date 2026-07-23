from sysscope.common.config import Config, Disk
from sysscope.collector.disk_collector import DiskCollector

DISKS = [Disk("sde", "/dev/sde", "/media/HDD8TB", 8, 64)]


def make_cfg(**kw):
    base = dict(disks=DISKS, db_path=":x:", web_host="127.0.0.1", web_port=1,
                sample_interval=1.0, power_interval=1.0, services_interval=1.0,
                idle_threshold=5.0, incident_window=6.0, retention_days=14)
    base.update(kw)
    return Config(**base)


def stats(reads):
    # linha de diskstats de sde com `reads` leituras
    return (f"   8      64 sde {reads} 0 {reads*8} 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n")


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def make_dc(reads_iter, clock, on_spinup=None, on_sample=None, **cfg_kw):
    spinups = [] if on_spinup is None else None
    samples = [] if on_sample is None else None
    dc = DiskCollector(
        make_cfg(**cfg_kw),
        on_spinup=(lambda ts, d, det: spinups.append((d, det))) if spinups is not None else on_spinup,
        on_sample=(lambda ts, d, ps, r: samples.append((d, ps))) if samples is not None else on_sample,
        diskstats_reader=lambda: next(reads_iter), clock=clock,
    )
    return dc, spinups, samples


def test_no_spinup_on_first_poll_even_if_active():
    clock = Clock()
    reads = iter([stats(10)])
    dc, spinups, samples = make_dc(reads, clock)
    dc.poll()                 # baseline, sem estado anterior -> nunca dispara
    assert spinups == []
    assert len(samples) == 1


def test_idle_to_active_fires_spinup_after_idle_threshold():
    clock = Clock()
    # baseline ativo, depois inatividade >= idle_threshold, depois atividade
    reads = iter([stats(10), stats(10), stats(20)])
    dc, spinups, samples = make_dc(reads, clock, idle_threshold=5.0)
    dc.poll()                 # baseline, last_active=1000
    clock.t += 6.0            # 6s sem I/O (>= idle_threshold de 5.0)
    dc.poll()                 # ainda sem atividade
    clock.t += 1.0
    dc.poll()                 # atividade após inatividade -> spin-up
    assert spinups == [("sde", "atividade")]


def test_continuous_activity_does_not_refire():
    clock = Clock()
    reads = iter([stats(10), stats(20), stats(30), stats(40)])
    dc, spinups, samples = make_dc(reads, clock, idle_threshold=5.0)
    dc.poll()
    clock.t += 1; dc.poll()
    clock.t += 1; dc.poll()
    clock.t += 1; dc.poll()
    assert spinups == []


def test_on_sample_reports_active_then_standby_after_recent_window():
    clock = Clock()
    reads = iter([stats(10), stats(20), stats(20)])
    dc, spinups, samples = make_dc(reads, clock, idle_threshold=5.0)
    dc.poll()                 # baseline
    clock.t += 1.0
    dc.poll()                 # active (I/O just happened)
    assert samples[-1] == ("sde", "active")
    clock.t += 25.0           # muito além de _DISPLAY_RECENT (20s)
    dc.poll()                 # sem I/O nova
    assert samples[-1] == ("sde", "standby")
