"""MCP stdio smoke test: verify stonex-ops mcp starts, responds to list_tools.

Usage:
    python tests/smoke_mcp.py /path/to/stonex-ops STONX_BIN \\
        [--env E] [--path P] [--audit-file F]
"""

import json
import queue
import subprocess
import sys
import threading
import time


def main() -> None:
    stonex_ops_bin = sys.argv[1]
    stonx_bin = sys.argv[2] if len(sys.argv) > 2 else "/bin/echo"
    extra_args = sys.argv[3:]  # --env, --path, --audit-file, etc.

    proc = subprocess.Popen(
        [stonex_ops_bin, "mcp",
         "--stonx-bin", stonx_bin] + extra_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Background thread reads stdout lines into a queue to avoid
    # blocking indefinitely on proc.stdout.readline().
    line_queue: queue.Queue[tuple[float, str | None]] = queue.Queue()
    stop_event = threading.Event()

    def _reader() -> None:
        try:
            for line in proc.stdout:
                if stop_event.is_set():
                    break
                line_queue.put((time.time(), line))
        finally:
            line_queue.put((time.time(), None))  # sentinel

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

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

        init_resp = _read_jsonrpc(line_queue, timeout=15)
        if init_resp is None:
            rc = proc.poll()
            stderr_tail = _read_stderr(proc)[-500:]
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

        list_resp = _read_jsonrpc(line_queue, timeout=10)
        if list_resp is None:
            raise AssertionError(
                f"no tools/list response. stderr tail: {_read_stderr(proc)[-300:]}"
            )
        tools = list_resp.get("result", {}).get("tools", [])
        assert len(tools) >= 6, f"expected >=6 tools, got {len(tools)}"
        tool_names = [t["name"] for t in tools]
        assert "ops_env_check" in tool_names, f"missing ops_env_check in {tool_names}"
        assert "ops_probe_connections" in tool_names, "missing ops_probe_connections"

        print(f"list_tools OK: {len(tools)} tools ({', '.join(tool_names[:3])}...)")

    finally:
        stop_event.set()
        proc.stdin.close()
        proc.terminate()
        reader_thread.join(timeout=3)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    # Verify stderr has startup output, not tool results
    stderr = _read_stderr(proc)
    assert stderr, "stderr should have startup logs"
    assert "ops_env_check" not in stderr, (
        f"stderr should not contain tool output. Got: {stderr[:300]}"
    )

    print("MCP stdio smoke all checks passed")


def _read_jsonrpc(
    line_queue: queue.Queue,
    timeout: float = 10,
) -> dict | None:
    """Read one JSON-RPC message from the queue with a deadline."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            ts, line = line_queue.get(timeout=remaining)
        except queue.Empty:
            break

        if line is None:  # sentinel (stdout closed)
            break
        stripped = line.strip()
        if not stripped:
            continue
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            continue
    return None


def _read_stderr(proc: subprocess.Popen) -> str:
    """Non-blocking read of whatever is in stderr so far."""
    try:
        import os as _os
        fd = proc.stderr.fileno()
        _os.set_blocking(fd, False)
    except (AttributeError, OSError):
        pass
    try:
        return proc.stderr.read() or ""
    except Exception:
        return ""


if __name__ == "__main__":
    main()
