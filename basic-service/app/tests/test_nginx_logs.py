"""Exercise nginx log supervision with real, bounded Python child processes."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]


def run_wrapper(child, *arguments, code=None):
    wrapper = code or (
        "import sys; from src.common.nginx_logs import run_nginx; "
        "raise SystemExit(run_nginx([sys.executable, '-u', *sys.argv[1:]]))"
    )
    return subprocess.run(
        [sys.executable, "-u", "-c", wrapper, str(child), *arguments], cwd=APP_DIR,
        env={**os.environ, "PYTHONUTF8": "1"}, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=10, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@pytest.mark.parametrize("exit_code", [0, 7, 23])
def test_real_child_stdout_and_stderr_are_scrubbed_without_losing_nginx_diagnostics(tmp_path, exit_code):
    stdout = (
        '2026/10/15 [error] upstream timed out (110: Connection timed out), '
        'request: "GET /review/任务?token=stdout-query-secret&_jtb_auth_state=stdout-state HTTP/1.1", '
        'upstream: "http://127.0.0.1:18130/review/任务?token=upstream-secret&nonce=upstream-state", '
        'host: "taskbook.example:443", status=504'
    )
    stderr = (
        '[error] connect() failed (111: Connection refused) while connecting to upstream, '
        'request: "POST /callback?%74oken=encoded-query-secret&name=%E4%B8%AD%E6%96%87 HTTP/1.1", '
        'upstream: "https://127.0.0.1:18131/callback?_jtb_auth_state=encoded-state", status=502\n'
        'request: "GET /encoded%3Ftoken%3Dpercent-secret%26nonce%3Dpercent-state HTTP/1.1"\n'
        'token=plain-secret nonce=plain-nonce _jtb_auth_state=plain-state sv_login_state=cookie-state\n'
    )
    child = tmp_path / "nginx_double.py"
    child.write_text(
        "import sys\n" + f"print({stdout!r}, flush=True)\n"
        + f"sys.stderr.write({stderr!r})\nsys.stderr.flush()\n"
        + "sys.stderr.buffer.write(b'non-UTF8: \\xff\\n'); sys.stderr.buffer.flush()\n"
        + "raise SystemExit(int(sys.argv[1]))\n", encoding="utf-8",
    )
    result = run_wrapper(child, str(exit_code))
    assert result.returncode == exit_code, result.stderr
    output = result.stdout + result.stderr
    for secret in (
        "stdout-query-secret", "stdout-state", "upstream-secret", "upstream-state",
        "encoded-query-secret", "encoded-state", "percent-secret", "percent-state",
        "plain-secret", "plain-nonce", "plain-state", "cookie-state",
    ):
        assert secret not in output
    assert "?" not in output and "%3F" not in output
    assert 'request: "GET /review/任务 HTTP/1.1"' in output
    assert 'upstream: "http://127.0.0.1:18130/review/任务"' in output
    assert 'request: "POST /callback HTTP/1.1"' in output
    assert 'upstream: "https://127.0.0.1:18131/callback"' in output
    assert 'host: "taskbook.example:443"' in output
    assert "Connection timed out" in output and "Connection refused" in output
    assert "status=504" in output and "status=502" in output
    assert "non-UTF8: �" in output


def test_unsensitive_startup_error_and_real_child_failure_exit_are_preserved(tmp_path):
    child = tmp_path / "nginx_failure.py"
    diagnostic = "nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)"
    child.write_text(f"import sys\nprint({diagnostic!r}, file=sys.stderr, flush=True)\nsys.exit(12)\n", encoding="utf-8")
    result = run_wrapper(child)
    assert result.returncode == 12
    assert result.stdout == diagnostic + "\n"
    assert not result.stderr


@pytest.mark.parametrize("ignore_stop", [False, True])
def test_stop_signal_is_forwarded_or_forced_and_the_child_is_reaped(tmp_path, ignore_stop):
    child = tmp_path / "signal_child.py"
    ready = tmp_path / "child-ready"
    child.write_text(
        "import os, signal, sys, time\nfrom pathlib import Path\n"
        "signal.signal(signal.SIGTERM, lambda *args: sys.exit(19))\n"
        "Path(sys.argv[1]).write_text('ready')\n"
        "deadline=time.monotonic()+3\n"
        "while time.monotonic()<deadline:\n print('child-running', flush=True); time.sleep(.02)\n"
        "sys.exit(71)\n", encoding="utf-8",
    )
    wrapper = (
        "import signal, sys, threading, time\nfrom pathlib import Path\n"
        "import subprocess\nimport src.common.nginx_logs as supervision\n"
        "from src.common.nginx_logs import run_nginx\n"
        + ("supervision._STOP_TIMEOUT_SECONDS=.15\n"
           "original_send_signal=subprocess.Popen.send_signal\n"
           "subprocess.Popen.send_signal=lambda child,sig: None if sig==signal.SIGTERM else original_send_signal(child,sig)\n" if ignore_stop else "")
        +
        "def stop_when_ready():\n"
        " deadline=time.monotonic()+2\n"
        " while not Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        " time.sleep(.05)\n signal.raise_signal(signal.SIGTERM)\n"
        "threading.Thread(target=stop_when_ready, daemon=True).start()\n"
        "code=run_nginx([sys.executable, '-u', *sys.argv[1:]])\n"
        "print('wrapper-reaped-child:' + str(code), flush=True)\n"
        "raise SystemExit(code)\n"
    )
    started = time.monotonic()
    result = run_wrapper(child, str(ready), code=wrapper)
    # Windows implements Popen.send_signal(SIGTERM) with TerminateProcess(1).
    child_code = 1 if os.name == "nt" else -9 if ignore_stop else 19
    assert result.returncode == child_code % 256
    assert f"wrapper-reaped-child:{child_code}" in result.stdout, result.stderr
    assert "child-running" in result.stdout
    assert time.monotonic() - started < 2, "An unresponsive child must be stopped before its natural 3-second exit"
