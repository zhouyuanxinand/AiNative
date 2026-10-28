"""Repository checks with explicit suites, working directories and exit codes.

Uses the existing backend virtualenv when present. Never installs dependencies,
starts/stops the user's services, or runs live probes as part of default checks.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "basic-service" / "app"
WEB = ROOT / "web"


def python_executable() -> str:
    for relative in ("Scripts/python.exe", "bin/python"):
        candidate = ROOT / "basic-service" / ".venv" / relative
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def executable(name: str) -> str:
    result = shutil.which(name)
    if not result:
        raise FileNotFoundError(f"{name} is not installed or not on PATH")
    return result


def run(command: list[str], *, cwd: Path = ROOT, environment: dict[str, str] | None = None) -> int:
    print(f"\n[{cwd.relative_to(ROOT) or '.'}] {' '.join(command)}", flush=True)
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8", **(environment or {})}
    return subprocess.run(command, cwd=cwd, env=environment, check=False).returncode


def browser_environment(script: Path) -> dict[str, str]:
    """Let JS checks reuse the optional Python Playwright installation."""
    environment = {"SCREENSHOT_DIR": str(APP / "runtime" / "browser-checks" / script.stem)}
    if "SCREENSHOT_DIR" in os.environ:
        environment.pop("SCREENSHOT_DIR")
    if script.suffix != ".mjs":
        return environment
    support = (
        "from pathlib import Path; import sys; "
        f"sys.path.insert(0, {str(ROOT / 'tests')!r}); "
        "from browser_support import browser_options; "
        "import importlib.util,json; "
        "spec=importlib.util.find_spec('playwright'); "
        "module=Path(spec.origin).parent/'driver/package/index.mjs' if spec and spec.origin else None; "
        "print(json.dumps({'module': module.as_uri() if module and module.is_file() else None, "
        "'executable': browser_options().get('executable_path')}))"
    )
    import json
    result = subprocess.run([python_executable(), "-c", support], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    options = json.loads(result.stdout)
    if "PLAYWRIGHT_MODULE" not in os.environ and options["module"]:
        environment["PLAYWRIGHT_MODULE"] = options["module"]
    if "PLAYWRIGHT_CHROMIUM_EXECUTABLE" not in os.environ and options["executable"]:
        environment["PLAYWRIGHT_CHROMIUM_EXECUTABLE"] = options["executable"]
    return environment


def scripts_for(suite: str) -> list[Path]:
    if suite == "browser":
        return sorted((WEB / "tests/browser").glob("*.browser.*")) + sorted((WEB / "tests/browser").glob("auth-callback-proxy.mjs"))
    if suite == "e2e":
        return sorted((ROOT / "tests/e2e").glob("*.py"))
    if suite == "live":
        return sorted((WEB / "tests/live").glob("*.browser.*")) + sorted((ROOT / "tests/live").glob("*.py"))
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=("all", "frontend", "backend", "rd", "browser", "e2e", "live"), nargs="?", default="all")
    parser.add_argument("--case", help="Browser/e2e/live script filename (see --list)")
    parser.add_argument("--list", action="store_true", help="List scripts without executing them")
    args = parser.parse_args()
    if (args.case or args.list) and args.suite not in {"browser", "e2e", "live"}:
        parser.error("--case and --list are for browser/e2e/live suites")

    if args.suite in {"browser", "e2e", "live"}:
        scripts = scripts_for(args.suite)
        if args.list:
            for script in scripts:
                print(script.relative_to(ROOT).as_posix())
            return 0
        if not args.case:
            parser.error("Choose a script with --case; use --list to inspect available checks")
        matches = [path for path in scripts if path.name == args.case]
        if len(matches) != 1:
            parser.error(f"Unknown or ambiguous case: {args.case}")
        script = matches[0]
        if args.suite == "live":
            print("LIVE: this explicitly selected check can call real services or change their configuration.", flush=True)
        runner = python_executable() if script.suffix == ".py" else executable("node")
        return run([runner, str(script)], cwd=WEB if WEB in script.parents else ROOT, environment=browser_environment(script))

    if args.suite in {"all", "frontend"}:
        for task in ("test", "build"):
            result = run([executable("npm"), "run", task], cwd=WEB)
            if result:
                return result
    if args.suite in {"all", "backend", "rd"}:
        paths = ["basic-service/app/tests"]
        if args.suite == "rd":
            paths = ["basic-service/app/tests/rd_platform", "basic-service/app/tests/assistant"]
        return run([python_executable(), "-m", "pytest", *paths, "-q"])
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
