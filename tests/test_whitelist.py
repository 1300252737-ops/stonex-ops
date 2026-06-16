"""Tests for command allowlist and input validation."""

import pytest

from stonex_ops.whitelist import (
    Probe,
    TenantList,
    TenantShow,
    WorkerJobList,
    is_safe_identity,
)


def test_output_json_after_subcommand():
    """--output=json must appear after the ctl subcommand."""
    cmd = TenantList()
    args = cmd.to_args("stonx", "test", "~/.stonex")
    pos_ctl = args.index("ctl")
    pos_output = args.index("--output=json")
    assert pos_output > pos_ctl, "--output=json must come after ctl subcommand"

    cmd = Probe(tenant="t1")
    args = cmd.to_args("stonx", "main", "/opt/.stonex")
    pos_output = args.index("--output=json")
    pos_probe = args.index("probe")
    assert pos_output > pos_probe, "--output=json must come after probe"


def test_safe_identity_rejects_shell_chars():
    assert not is_safe_identity("; rm -rf /")
    assert not is_safe_identity("$(whoami)")
    assert not is_safe_identity("`cat /etc/passwd`")
    assert is_safe_identity("tenant-abc_123")


def test_no_shell_chars_in_args():
    cmd = TenantShow(tenant="test")
    args = cmd.to_args("stonx", "test", "~/.stonex")
    for arg in args:
        assert ";" not in arg
        assert "|" not in arg
        assert "$" not in arg
        assert "`" not in arg


def test_rejects_invalid_tenant_identity():
    cmd = TenantShow(tenant="; drop table")
    with pytest.raises(ValueError, match="invalid tenant identity"):
        cmd.to_args("stonx", "test", "~/.stonex")


def test_rejects_invalid_job_status():
    cmd = WorkerJobList(status="hacked")
    with pytest.raises(ValueError, match="invalid job status"):
        cmd.to_args("stonx", "test", "~/.stonex")


def test_rejects_limit_out_of_range():
    with pytest.raises(ValueError, match="limit out of range"):
        WorkerJobList(limit=0).to_args("stonx", "test", "~/.stonex")
    with pytest.raises(ValueError, match="limit out of range"):
        WorkerJobList(limit=501).to_args("stonx", "test", "~/.stonex")
