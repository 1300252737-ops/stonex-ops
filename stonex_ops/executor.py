"""Sandbox executor: safely invoke `stonx ctl --output json` via asyncio subprocess.

Security measures:
- No shell execution; list args passed directly to the process.
- Tiered timeouts to prevent hangs; hung processes are killed and reaped.
- Output size limit to prevent OOM.
- Probe commands return stdout even on non-zero exit (diagnostics are in JSON).
- Stderr is never exposed externally.
"""

from __future__ import annotations

import asyncio

from stonex_ops.whitelist import AllowedCommand, op_kind

# Maximum output size (1 MB) to prevent OOM.
MAX_OUTPUT_BYTES: int = 1_048_576

# Timeouts in seconds.
TIMEOUTS: dict[str, float] = {
    "read": 15.0,
    "probe": 45.0,
}


class ExecutionError(Exception):
    """Command execution failed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


async def execute(
    stonx_bin: str,
    env: str,
    path: str,
    command: AllowedCommand,
) -> str:
    """Execute an allowlisted command. Returns the stdout string.

    Raises:
        ValueError: parameter validation failed.
        ExecutionError: command execution failed or timed out.
    """
    try:
        args = command.to_args(stonx_bin, env, path)
    except ValueError:
        raise

    timeout = TIMEOUTS.get(op_kind(command), 15.0)

    proc = None
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        # Kill and reap the hung child process to prevent zombies.
        if proc is not None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        raise ExecutionError(
            f"stonx command timed out after {timeout}s: {' '.join(args)}"
        )
    except OSError as exc:
        raise ExecutionError(f"stonx command failed to start: {exc}")

    stdout = stdout_bytes.decode("utf-8", errors="replace")

    if len(stdout) > MAX_OUTPUT_BYTES:
        raise ExecutionError(
            f"stonx output too large: {len(stdout)} bytes (max {MAX_OUTPUT_BYTES})"
        )

    # Probe may exit non-zero when diagnostics find problems, but
    # stdout still contains the full structured JSON.
    is_probe = op_kind(command) == "probe"

    if proc.returncode != 0 and not is_probe:
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        stderr_summary = "; ".join(stderr.splitlines()[:3])
        raise ExecutionError(
            f"stonx exited with {proc.returncode}: {stderr_summary}"
        )

    return stdout
