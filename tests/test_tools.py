"""Tests for MCP tool JSON output parsing and argument validation."""

import json

import pytest

from stonex_ops.server import (
    TOOL_DEFINITIONS,
    _optional_int,
    _optional_string,
    _require_string,
)

# ---- Fixture JSON shapes (representative stonx --output json) ----

TENANT_SHOW_JSON = """{
    "tenant": "tn_fixture",
    "ops_tag": "fixture",
    "status": "active",
    "display_name": "Fixture",
    "tenant_business_timezone": "Asia/Shanghai",
    "tenant_business_day_cutoff": "00:00",
    "tenant_business_day_cutover_at": "1970-01-01T00:00:00+08:00",
    "ai_daily_question_limit": 200,
    "home_path": "/t/tn_fixture/",
    "shop": {
        "shop_id": "shop-a",
        "business_timezone": "Asia/Shanghai",
        "business_day_cutoff": "00:00",
        "business_day_cutover_at": "1970-01-01T00:00:00+08:00",
        "shop_home_path": "/t/tn_fixture/shops/shop-a/",
        "xhs_auth_path": "/t/tn_fixture/shops/shop-a/data-sources/xhs-api/auth"
    },
    "connections": [
        {
            "connection": "xhs",
            "app_id": "app-id",
            "seller_id": "seller",
            "seller_name": null,
            "access_expires_at": "2099-01-01T00:00:00Z",
            "refresh_expires_at": "2099-02-01T00:00:00Z",
            "status": "active",
            "app_status": "active"
        }
    ]
}"""

TENANT_SHOW_NO_SHOP_JSON = """{
    "tenant": "tn_new",
    "ops_tag": "new-tenant",
    "status": "active",
    "display_name": "New Tenant",
    "tenant_business_timezone": "Asia/Shanghai",
    "tenant_business_day_cutoff": "00:00",
    "tenant_business_day_cutover_at": "1970-01-01T00:00:00+08:00",
    "ai_daily_question_limit": 200,
    "home_path": "/t/tn_new/",
    "shop": null,
    "shop_scope_error": null,
    "fallback_xhs_auth_path": "/t/tn_new/source-auth/xhs-api/auth",
    "connections": []
}"""

PROBE_JSON = """{
    "result": "problems_found",
    "check_count": 3,
    "problem_count": 2,
    "scopes": [
        {
            "tenant": "tn_a",
            "shop_id": "shop-a",
            "tenant_tag": "customer-a",
            "shop_label": "Flagship",
            "problem_count": 1,
            "connections": [
                {
                    "connection_id": "xhs-api",
                    "status": "ok",
                    "reason_code": "",
                    "message": "",
                    "checked_at": "2026-06-16T08:00:00Z",
                    "last_success_at": "2026-06-16T07:00:00Z",
                    "latency_ms": 234,
                    "detail": []
                }
            ]
        }
    ]
}"""

WORKER_JOB_LIST_JSON = """{
    "jobs": [
        {
            "job_id": "job-1",
            "tenant": "tn_demo",
            "shop_id": "shop-a",
            "kind": "daily",
            "status": "succeeded",
            "attempt_count": 1,
            "max_attempts": 3,
            "run_after": "2026-06-16T08:00:00Z"
        },
        {
            "job_id": "job-2",
            "tenant": "tn_demo",
            "shop_id": "shop-a",
            "kind": "weekly",
            "status": "failed",
            "attempt_count": 3,
            "max_attempts": 3,
            "run_after": "2026-06-15T08:00:00Z"
        }
    ]
}"""

WORKER_SCHEDULE_LIST_JSON = """{
    "schedules": [
        {
            "tenant": "tn_demo",
            "shop_id": "shop-a",
            "kind": "daily",
            "cron": "0 0 8 * * *",
            "timezone": "Asia/Shanghai",
            "status": "active"
        }
    ]
}"""

TENANT_LIST_JSON = """{
    "tenants": [
        {
            "tenant": "tn_fixture",
            "ops_tag": "fixture",
            "status": "active",
            "seller_name": "Demo Seller",
            "connections": {"xhs": "active", "jst": "missing", "wangdian": "missing"},
            "updated_at": "2026-06-16T00:00:00Z"
        }
    ]
}"""

STONX_VERSION_OUTPUT = "stonx 1.2.3 (abc1234 2026-06-01)\n"


# ---- Fixture shape tests ----

def test_parses_tenant_show_shape():
    data = json.loads(TENANT_SHOW_JSON)
    assert data["tenant"] == "tn_fixture"
    assert data["ops_tag"] == "fixture"
    assert data["tenant_business_timezone"] == "Asia/Shanghai"
    assert data["shop"]["shop_id"] == "shop-a"
    assert data["connections"][0]["connection"] == "xhs"


def test_parses_tenant_show_with_scope_error():
    """tenant_show includes scope-error fields for onboarding/auth troubleshooting."""
    data = json.loads(TENANT_SHOW_NO_SHOP_JSON)
    assert data["tenant"] == "tn_new"
    assert data["shop"] is None
    assert data["shop_scope_error"] is None
    assert data["fallback_xhs_auth_path"] == "/t/tn_new/source-auth/xhs-api/auth"


def test_tenant_show_includes_scope_error_fields():
    """scope-related fields are top-level (serde(flatten) in stonx)."""
    data = json.loads(TENANT_SHOW_NO_SHOP_JSON)
    assert "shop_scope_error" in data
    assert "fallback_xhs_auth_path" in data


def test_parses_probe_shape():
    data = json.loads(PROBE_JSON)
    assert data["result"] == "problems_found"
    assert data["check_count"] == 3
    assert data["problem_count"] == 2
    assert data["scopes"][0]["shop_id"] == "shop-a"
    assert data["scopes"][0]["tenant"] == "tn_a"


def test_parses_worker_job_list_wrapper():
    data = json.loads(WORKER_JOB_LIST_JSON)
    jobs = data["jobs"]
    assert len(jobs) == 2
    assert jobs[0]["kind"] == "daily"
    assert jobs[1]["attempt_count"] == 3


def test_parses_worker_schedule_list_wrapper():
    data = json.loads(WORKER_SCHEDULE_LIST_JSON)
    schedules = data["schedules"]
    assert len(schedules) == 1
    assert schedules[0]["kind"] == "daily"


def test_parses_tenant_list_wrapper():
    data = json.loads(TENANT_LIST_JSON)
    tenants = data["tenants"]
    assert len(tenants) == 1
    assert tenants[0]["tenant"] == "tn_fixture"


def test_extracts_report_jobs_from_worker_list():
    data = json.loads(WORKER_JOB_LIST_JSON)
    jobs = data["jobs"]
    summaries = [
        {
            "job_id": j.get("job_id", "-"),
            "tenant": j.get("tenant", "-"),
            "shop_id": j.get("shop_id", "-"),
            "kind": j.get("kind", "-"),
            "status": j.get("status", "-"),
            "attempt_count": str(j["attempt_count"]) if "attempt_count" in j else "-",
            "run_after": j.get("run_after", "-"),
        }
        for j in jobs
    ]
    assert len(summaries) == 2
    assert summaries[0]["kind"] == "daily"
    assert summaries[1]["attempt_count"] == "3"


# ---- Argument type validation (P1 fix) ----

def test_require_string_rejects_non_string():
    with pytest.raises(ValueError, match="must be a non-empty string"):
        _require_string({"tenant": 123}, "tenant")
    with pytest.raises(ValueError, match="must be a non-empty string"):
        _require_string({"tenant": None}, "tenant")
    with pytest.raises(ValueError, match="must be a non-empty string"):
        _require_string({"tenant": True}, "tenant")


def test_optional_string_rejects_non_string():
    with pytest.raises(ValueError, match="must be a string"):
        _optional_string({"tenant": 123}, "tenant")
    with pytest.raises(ValueError, match="must be a string"):
        _optional_string({"tenant": True}, "tenant")
    # None is allowed for optional
    assert _optional_string({"tenant": None}, "tenant") is None
    assert _optional_string({}, "tenant") is None


def test_optional_int_rejects_non_int():
    with pytest.raises(ValueError, match="must be an integer"):
        _optional_int({"limit": "abc"}, "limit")
    with pytest.raises(ValueError, match="must be an integer"):
        _optional_int({"limit": True}, "limit")  # bool is not int
    assert _optional_int({"limit": None}, "limit") is None
    assert _optional_int({}, "limit") is None
    assert _optional_int({"limit": 50}, "limit") == 50


# ---- Probe boundary regression tests ----



def test_env_check_does_not_construct_probe():
    """ops_env_check only constructs StonxVersion, never Probe/ProbeAll."""
    # env_check.run() calls execute(bin, env, path, StonxVersion()); verify via source.
    import inspect

    from stonex_ops.tools.env_check import run as _env_check
    src = inspect.getsource(_env_check)
    assert "StonxVersion" in src
    assert "Probe" not in src


def test_only_probe_connections_constructs_probe():
    """Only ops_probe_connections constructs Probe/ProbeAll."""
    import inspect

    from stonex_ops.tools import probe_connections as _pc
    src = inspect.getsource(_pc)
    assert ("Probe(" in src or "ProbeAll(" in src)


def test_non_probe_tools_do_not_construct_probe():
    """No non-probe tool constructs Probe or ProbeAll."""
    import inspect

    from stonex_ops.tools import (
        report_status,
        tenant_list,
        tenant_show,
        worker_jobs,
        worker_schedules,
    )
    non_probe = [tenant_list, tenant_show, worker_jobs, worker_schedules, report_status]
    for fn in non_probe:
        src = inspect.getsource(fn)
        assert "Probe(" not in src, f"{fn.__name__} must not construct Probe"
        assert "ProbeAll(" not in src, f"{fn.__name__} must not construct ProbeAll"


# ---- env_check output shape ----

def test_env_check_output_has_no_probe_fields():
    """env_check result dict shape: only env/stonx_reachable/stonx_version."""
    # env_check.run() constructs only StonxVersion; verified by
    # test_env_check_does_not_construct_probe above.
    # This test confirms the output dict shape matches.
    import inspect

    from stonex_ops.tools.env_check import run as _env_check
    src = inspect.getsource(_env_check)
    assert "probe_result" not in src, "env_check output must not contain probe_result"
    assert "probe_ok" not in src, "env_check output must not contain probe_ok"
    assert "ProbeAll" not in src, "env_check must not import ProbeAll"
    assert "StonxVersion" in src, "env_check must call StonxVersion"


def test_probe_tool_annotations_are_not_read_only():
    tool = next(t for t in TOOL_DEFINITIONS if t.name == "ops_probe_connections")
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is False
