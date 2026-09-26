import pytest
from conftest import NativeApi, serve

from kimi_memory.cli import doctor
from kimi_memory.compatibility import HOST, check_host_version
from kimi_memory.errors import CompatibilityError
from kimi_memory.kimi import KimiClient


@pytest.mark.parametrize(
    "version", ["2.1.0", "2.1.1", "2.1.7", "2.2.9", "2.3.5", "3.0.0", "development"]
)
def test_newer_hosts_are_tried_not_blocked_by_a_whitelist(config, version):
    with serve(NativeApi([], version=version)) as (origin, _):
        client = KimiClient(origin, lambda: "test-native-token-never-log", config.api)
        client.handshake()
        assert client.sessions(since=0, limit=1) == []


@pytest.mark.parametrize("version", ["2.0.9", "1.99.9", "v2.0.0"])
def test_explicitly_unsupported_old_host_has_an_actionable_diagnostic(version):
    with pytest.raises(CompatibilityError, match="update Kimi yourself"):
        check_host_version(version)


def test_offline_diagnostics_describe_the_host_floor_and_pin(home):
    support = doctor(home)["host_support"]
    assert support["minimum_version"] == HOST["minimum_version"]
    assert support["tested_version"] == HOST["tested_version"]
    assert "actual APIs" in support["policy"]
