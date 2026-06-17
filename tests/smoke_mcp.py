"""MCP stdio smoke test: verify stonex-ops mcp starts, responds to list_tools.

Usage: python tests/smoke_mcp.py /path/to/stonex-ops [--stonx-bin BIN]
"""

import json
import subprocess
import sys
import time


def main() -> None:
    stonex_ops_bin = sys.argv[1]
    # Use /bin/echo as a fake stonx so the process can at least start.
    # The startup check will fail but the server should continue.
    stonx_bin = sys.argv[2] if len(sys.argv) > 2 else "/bin/echo"

    proc = subprocess.Popen(
        [stonex_ops_bin, "mcp",
         "--stonx-bin", stonx_bin,
         "--env", "scratch",
         "--path", "/tmp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # MCP initialize handshake
        init_req = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "0.1.0"},
            },
        })

        proc.stdin.write(init_req + "\n")
        proc.stdin.flush()

        init_resp = _read_jsonrpc_line(proc, timeout=15)
        if init_resp is None:
            stderr_tail = proc.stderr.read()[-500:]
            # If stonx --version fails, the server still logs a warning and
            # starts. If the process exited, capture why.
            rc = proc.poll()
            raise AssertionError(
                f"no initialize response (exit={rc}). stderr tail: {stderr_tail}"
            )

        assert "result" in init_resp, (
            f"initialize failed: {json.dumps(init_resp)[:300]}"
        )
        server_name = init_resp["result"].get("serverInfo", {}).get("name", "?")
        print(f"initialize OK: server={server_name}")

        # Send initialized notification
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }) + "\n")
        proc.stdin.flush()

        # Request tools/list
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }) + "\n")
        proc.stdin.flush()

        list_resp = _read_jsonrpc_line(proc, timeout=10)
        assert list_resp is not None, (
            f"no tools/list response. stderr tail: {proc.stderr.read()[-300:]}"
        )
        tools = list_resp.get("result", {}).get("tools", [])
        assert len(tools) >= 6, f"expected >=6 tools, got {len(tools)}"
        tool_names = [t["name"] for t in tools]
        assert "ops_env_check" in tool_names, f"missing ops_env_check in {tool_names}"
        assert "ops_probe_connections" in tool_names, "missing ops_probe_connections"

        print(f"list_tools OK: {len(tools)} tools ({', '.join(tool_names[:3])}...)")

    finally:
        proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    # Verify stderr has startup output, not tool results
    stderr = proc.stderr.read()
    assert stderr, "stderr should have startup logs"
    assert "ops_env_check" not in stderr, (
        f"stderr should not contain tool output. Got: {stderr[:300]}"
    )

    print("MCP stdio smoke all checks passed")


def _read_jsonrpc_line(proc: subprocess.Popen, timeout: float = 10) -> dict | None:
    """Read one JSON-RPC line from stdout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        stripped = line.strip()
        if not stripped:
            continue
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            continue
    return None


if __name__ == "__main__":
    main()
