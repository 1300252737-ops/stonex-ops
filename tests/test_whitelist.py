"""Tests for remaining stonx command allowlist."""

import pytest

from stonex_ops.whitelist import Probe, StonxVersion, is_safe_identity


def test_probe_output_json_after_subcommand():
    cmd = Probe(tenant="t1")
    args = cmd.to_args("stonx", "main", "/opt/.stonex")
    pos_output = args.index("--output=json")
    pos_probe = args.index("probe")
    assert pos_output > pos_probe, "--output=json must come after probe"


def test_stonx_version_has_no_env_or_path_args():
    assert StonxVersion().to_args("stonx", "main", "/opt/.stonex") == ["stonx", "--version"]


def test_safe_identity_rejects_shell_chars():
    assert not is_safe_identity("; rm -rf /")
    assert not is_safe_identity("$(whoami)")
    assert not is_safe_identity("`cat /etc/passwd`")
    assert is_safe_identity("tenant-abc_123")


def test_no_shell_chars_in_probe_args():
    cmd = Probe(tenant="test")
    args = cmd.to_args("stonx", "test", "~/.stonex")
    for arg in args:
        assert ";" not in arg
        assert "|" not in arg
        assert "$" not in arg
        assert "`" not in arg


def test_rejects_invalid_tenant_identity():
    cmd = Probe(tenant="; drop table")
    with pytest.raises(ValueError, match="invalid tenant identity"):
        cmd.to_args("stonx", "test", "~/.stonex")
