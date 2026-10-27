"""Run foreground nginx while removing query credentials from both log streams.

The container entrypoint supervises this process in place of nginx. Application
configuration is deliberately not loaded here: nginx starts with root privileges
and only its own output and lifecycle belong to this wrapper.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence

from src.common.runtime_logs import redact_log_text

_URI_QUERY = re.compile(r"""((?:https?://|/)[^\s"'<>?]*?)(?:\?|%3[fF])[^\s"'<>]*""")
_LOGIN_STATE = re.compile(
    r"""(?i)(["']?\b(?:nonce|_jtb_auth_state|sv_login_state)\b["']?\s*[:=]\s*)"""
    r"""(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}&]+)"""
)
_STOP_TIMEOUT_SECONDS = 5.0


def sanitize_nginx_line(line: str) -> str:
    """Preserve nginx diagnostics, excluding URI queries and credential fields."""
    line = _URI_QUERY.sub(r"\1", line)
    line = _LOGIN_STATE.sub(lambda match: match.group(1) + "***", line)
    return redact_log_text(line)


def run_nginx(command: Sequence[str] | None = None) -> int:
    """Forward sanitized output and stop signals, then reap nginx and return its status."""
    child = subprocess.Popen(
        list(command) if command is not None else ["nginx", "-g", "daemon off;"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        start_new_session=os.name != "nt",
    )
    previous_handlers = {}
    finished = threading.Event()
    stop_deadline = None

    def force_stop():
        try:
            if os.name != "nt":
                # Nginx workers share only this master's new process group.
                os.killpg(child.pid, signal.SIGKILL)
            elif child.poll() is None:
                child.kill()
        except ProcessLookupError:
            pass

    def supervise_child():
        while not finished.wait(0.05):
            if child.poll() is not None or (stop_deadline is not None and time.monotonic() >= stop_deadline):
                # Also close inherited worker pipes if the master died first.
                force_stop()
                return

    def forward_signal(signum, _frame):
        nonlocal stop_deadline
        if stop_deadline is None:
            stop_deadline = time.monotonic() + _STOP_TIMEOUT_SECONDS
        if child.poll() is None:
            try:
                child.send_signal(signum)
            except ProcessLookupError:
                pass

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, forward_signal)
        watchdog = threading.Thread(target=supervise_child, daemon=True)
        watchdog.start()
        for line in child.stdout:
            sys.stdout.write(sanitize_nginx_line(line))
            sys.stdout.flush()
        return child.wait()
    finally:
        try:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=_STOP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    force_stop()
                    child.wait()
            else:
                child.wait()
        finally:
            finished.set()
            # Reap the master and stop any workers surviving a master failure.
            force_stop()
            child.stdout.close()
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


if __name__ == "__main__":
    exit_code = run_nginx()
    if exit_code < 0 and os.name != "nt":
        # Preserve a child's signal termination as well as ordinary exit codes.
        child_signal = -exit_code
        if child_signal not in (signal.SIGKILL, signal.SIGSTOP):
            signal.signal(child_signal, signal.SIG_DFL)
        os.kill(os.getpid(), child_signal)
    raise SystemExit(exit_code)
