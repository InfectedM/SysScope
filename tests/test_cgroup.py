from sysscope.collector.cgroup import container_id_from_cgroup, ContainerResolver

CGROUP = "0::/system.slice/docker-5cc6d74a8b6cf71e46a3c54d3ca111f48effe94193d3e5b3ff572bf81636d09e.scope\n"
FULL = "5cc6d74a8b6cf71e46a3c54d3ca111f48effe94193d3e5b3ff572bf81636d09e"


def test_container_id_from_cgroup():
    assert container_id_from_cgroup(CGROUP) == FULL


def test_container_id_none_for_non_docker():
    assert container_id_from_cgroup("0::/user.slice/session-1.scope") is None


def test_resolver_maps_pid_to_name(tmp_path):
    proc = tmp_path / "proc" / "3181"
    proc.mkdir(parents=True)
    (proc / "cgroup").write_text(CGROUP)

    def fake_docker(argv):
        # docker ps --no-trunc --format '{{.ID}}|{{.Names}}'
        return f"{FULL}|jellyfin\ndeadbeef...|radarr\n"

    r = ContainerResolver(runner=fake_docker, proc_base=str(tmp_path / "proc"))
    r.refresh()
    assert r.name_for_pid(3181) == "jellyfin"


def test_resolver_returns_none_for_unknown_pid(tmp_path):
    (tmp_path / "proc").mkdir()
    r = ContainerResolver(runner=lambda a: "", proc_base=str(tmp_path / "proc"))
    r.refresh()
    assert r.name_for_pid(9999) is None
