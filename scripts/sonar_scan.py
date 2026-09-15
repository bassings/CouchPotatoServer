#!/usr/bin/env python3
"""Run a truthful local SonarQube analysis and record CE completion.

The scanner upload is asynchronous.  A zero scanner exit status only means the
report was accepted, so this command polls the submitted Compute Engine task
for at most 120 seconds, every two seconds, before writing the local stamp.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
ANALYSIS_TOKEN = re.compile(r"^sq[ap]_\S+$")
ACTIVE_CE_STATES = {"PENDING", "IN_PROGRESS"}
FAILED_CE_STATES = {"FAILED", "CANCELED"}
GIT_COMMAND_TIMEOUT = 30.0
COVERAGE_COMMAND_TIMEOUT = 15 * 60.0
NPM_COMMAND_TIMEOUT = 5 * 60.0
SCANNER_COMMAND_TIMEOUT = 10 * 60.0


class ScanError(RuntimeError):
    """A safe, actionable scan failure whose message contains no credential."""


class NoRedirectHandler(HTTPRedirectHandler):
    """Refuse redirects so an authenticated CE request stays on its host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_ce_opener(*handlers):
    """Build a CE opener that never discovers proxies from the environment."""

    return build_opener(ProxyHandler({}), NoRedirectHandler(), *handlers)


_CE_OPENER = build_ce_opener()


def open_ce_url(request: Request, timeout: float):
    return _CE_OPENER.open(request, timeout=timeout)


@dataclass
class Config:
    repo: Path
    host_url: str
    token_file: Path
    scanner_version: str
    make_command: str = "make"
    poll_interval: float = 2.0
    poll_timeout: float = 120.0


def load_analysis_token(path: Path) -> str:
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise ScanError(f"No readable analysis token file at {path}") from exc

    values = [line.removeprefix("SONAR_TOKEN=") for line in lines if line.startswith("SONAR_TOKEN=")]
    if len(values) != 1 or not ANALYSIS_TOKEN.fullmatch(values[0]):
        raise ScanError(
            f"{path} must contain one SONAR_TOKEN analysis token with an sqa_ or sqp_ prefix; "
            "the administrator token is not valid for routine scans"
        )
    return values[0]


def _safe_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("NODE_OPTIONS", None)
    for name in list(env):
        if (
            name.startswith("GIT_")
            or name.startswith(("SONAR_", "SONARQUBE_"))
            or name.lower().endswith("_proxy")
            or name.lower().startswith("npm_config_")
        ):
            env.pop(name)
    return env


def _command(
    run,
    argv: list[str],
    repo: Path,
    *,
    env: dict[str, str],
    capture_output: bool = True,
    timeout: float = GIT_COMMAND_TIMEOUT,
    description: str | None = None,
) -> str:
    command_name = description or argv[0]
    try:
        if run is subprocess.run:
            result = _run_isolated_process(
                argv,
                cwd=repo,
                env=env,
                capture_output=capture_output,
                timeout=timeout,
            )
        else:
            result = run(
                argv,
                cwd=repo,
                env=env,
                check=True,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired as exc:
        raise ScanError(
            f"Command timed out: {command_name}; its process group was stopped, inspect local state and retry"
        ) from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScanError(
            f"Command failed: {command_name}; fix the reported local error and retry"
        ) from exc
    return result.stdout or ""


def _run_isolated_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    capture_output: bool,
    timeout: float,
) -> subprocess.CompletedProcess:
    """Run one command in a process group that can be stopped as a unit."""

    pipe = subprocess.PIPE if capture_output else None
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdout=pipe,
        stderr=pipe,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = _stop_process_group(process)
        raise subprocess.TimeoutExpired(
            argv,
            timeout,
            output=stdout if stdout is not None else exc.output,
            stderr=stderr if stderr is not None else exc.stderr,
        ) from exc
    except BaseException:
        _stop_process_group(process)
        raise
    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    if process.returncode:
        raise subprocess.CalledProcessError(
            process.returncode,
            argv,
            output=stdout,
            stderr=stderr,
        )
    return result


def _stop_process_group(process: subprocess.Popen) -> tuple[str | None, str | None]:
    """Stop and reap a command group without leaving detached child work."""

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        stdout, stderr = process.communicate(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return process.communicate()

    # The group leader may have exited while a descendant that closed its
    # inherited pipes kept running. Ensure no such work survives.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return stdout, stderr


def checkout_sha(
    config: Config,
    run,
    *,
    expected_sha: str | None = None,
    after_upload: bool = False,
) -> str:
    env = _safe_env()
    recovery = "; the uploaded result must be disregarded and re-run" if after_upload else ""
    branch = _command(run, ["git", "symbolic-ref", "--short", "HEAD"], config.repo, env=env).strip()
    if branch != "master":
        raise ScanError(
            f"Sonar scan requires branch master; current branch is {branch or 'detached'}{recovery}"
        )

    dirty = _command(
        run,
        ["git", "status", "--porcelain", "--untracked-files=all"],
        config.repo,
        env=env,
    )
    if dirty:
        raise ScanError(
            "Sonar scan requires a clean checkout; commit or remove local changes first"
            f"{recovery}"
        )

    sha = _command(run, ["git", "rev-parse", "HEAD"], config.repo, env=env).strip()
    if not FULL_SHA.fullmatch(sha):
        raise ScanError(f"Git did not return an exact 40-character commit SHA{recovery}")
    if expected_sha is not None and sha != expected_sha:
        if after_upload:
            raise ScanError("HEAD changed during scanner upload; the uploaded result must be disregarded and re-run")
        raise ScanError("HEAD changed while coverage was running; no analysis was uploaded")
    return sha


def read_task_id(report_path: Path) -> str:
    try:
        fields = dict(
            line.split("=", 1)
            for line in report_path.read_text().splitlines()
            if "=" in line
        )
    except OSError as exc:
        raise ScanError("Scanner did not produce .scannerwork/report-task.txt; no freshness stamp written") from exc
    task_id = fields.get("ceTaskId", "").strip()
    if not task_id:
        raise ScanError("Scanner report is missing ceTaskId; no freshness stamp written")
    return task_id


def poll_ce_task(
    config: Config,
    task_id: str,
    token: str,
    *,
    open_url: Callable = open_ce_url,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    # Never trust report-task.txt's serverUrl: only the operator-configured host
    # may receive the Authorization header.
    host = urlsplit(config.host_url)
    if host.scheme not in {"http", "https"} or not host.netloc:
        raise ScanError("SonarQube host URL must be an HTTP(S) server")
    url = f"{config.host_url.rstrip('/')}/api/ce/task?{urlencode({'id': task_id})}"
    authorization = base64.b64encode(f"{token}:".encode()).decode("ascii")
    started = monotonic()

    while True:
        remaining = config.poll_timeout - (monotonic() - started)
        if remaining <= 0:
            raise ScanError("SonarQube CE task timed out; check the task on the server and retry the scan")
        request = Request(url, headers={"Authorization": f"Basic {authorization}"})
        try:
            with open_url(request, timeout=min(10.0, remaining)) as response:
                payload = json.loads(response.read())
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ScanError("SonarQube CE authentication failed; verify the analysis token and retry") from exc
            raise ScanError(f"SonarQube CE request failed with HTTP {exc.code}; retry the scan") from exc
        except (URLError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ScanError("SonarQube CE returned an unreadable response; retry the scan") from exc

        try:
            status = payload["task"]["status"]
        except (KeyError, TypeError) as exc:
            raise ScanError("SonarQube CE returned malformed task data; no freshness stamp written") from exc
        if not isinstance(status, str):
            raise ScanError("SonarQube CE returned malformed task data; no freshness stamp written")
        if status == "SUCCESS":
            return
        if status in FAILED_CE_STATES:
            raise ScanError(f"SonarQube CE task ended {status}; inspect server logs and retry the scan")
        if status not in ACTIVE_CE_STATES:
            raise ScanError(f"SonarQube CE returned unknown status {status!r}; no freshness stamp written")
        remaining = config.poll_timeout - (monotonic() - started)
        if remaining <= 0:
            raise ScanError("SonarQube CE task timed out; check the task on the server and retry the scan")
        sleep(min(config.poll_interval, remaining))


def write_stamp_atomically(path: Path, sha: str) -> None:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(f"{sha}\n{timestamp}\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def run_scan(
    config: Config,
    *,
    run=subprocess.run,
    open_url: Callable = open_ce_url,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> str:
    token = load_analysis_token(config.token_file)
    sha = checkout_sha(config, run)
    _command(
        run,
        [config.make_command, "coverage"],
        config.repo,
        env=_safe_env(),
        capture_output=False,
        timeout=COVERAGE_COMMAND_TIMEOUT,
        description="coverage",
    )
    checkout_sha(config, run, expected_sha=sha)

    report_path = config.repo / ".scannerwork" / "report-task.txt"
    try:
        report_path.unlink(missing_ok=True)
    except OSError as exc:
        raise ScanError("Cannot remove the previous scanner task report; no analysis was uploaded") from exc

    scanner = f"sonarqube-scanner@{config.scanner_version}"
    # npm is configuration-extensible (for example through user ``.npmrc``
    # hooks), so it must never run with the Sonar credential. Install the
    # pinned scanner in an isolated temporary project first, then launch its
    # JavaScript entry point directly with the token-bearing environment.
    with tempfile.TemporaryDirectory(prefix="couchpotato-sonar-scanner-") as scanner_root:
        scanner_root_path = Path(scanner_root)
        empty_user_config = scanner_root_path / "empty-user.npmrc"
        empty_global_config = scanner_root_path / "empty-global.npmrc"
        empty_user_config.write_text("")
        empty_global_config.write_text("")
        _command(
            run,
            [
                "npm",
                "install",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--package-lock=false",
                f"--userconfig={empty_user_config}",
                f"--globalconfig={empty_global_config}",
                scanner,
            ],
            scanner_root_path,
            env=_safe_env(),
            capture_output=False,
            timeout=NPM_COMMAND_TIMEOUT,
        )
        checkout_sha(config, run, expected_sha=sha)
        scanner_entry = (
            scanner_root_path
            / "node_modules"
            / "sonarqube-scanner"
            / "bin"
            / "sonar-scanner.js"
        )
        scanner_env = _safe_env()
        scanner_env["SONAR_TOKEN"] = token
        _command(
            run,
            [
                "node",
                str(scanner_entry),
                f"-Dsonar.host.url={config.host_url}",
                f"-Dsonar.projectVersion={sha}",
                f"-Dsonar.scm.revision={sha}",
            ],
            config.repo,
            env=scanner_env,
            capture_output=False,
            timeout=SCANNER_COMMAND_TIMEOUT,
        )
    checkout_sha(config, run, expected_sha=sha, after_upload=True)
    task_id = read_task_id(report_path)
    poll_ce_task(
        config,
        task_id,
        token,
        open_url=open_url,
        sleep=sleep,
        monotonic=monotonic,
    )
    write_stamp_atomically(config.repo / ".sonar-last-analysis", sha)
    return sha


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--host-url")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--scanner-version", default="5.0.0")
    parser.add_argument("--make-command", default="make")
    parser.add_argument("--check-token", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.check_token:
            load_analysis_token(args.token_file)
            return 0
        if not args.host_url:
            raise ScanError("--host-url is required for a scan")
        sha = run_scan(
            Config(
                repo=args.repo.resolve(),
                host_url=args.host_url,
                token_file=args.token_file,
                scanner_version=args.scanner_version,
                make_command=args.make_command,
            )
        )
    except ScanError as exc:
        print(f"SonarQube scan stopped: {exc}", file=sys.stderr)
        return 1
    print(f"SonarQube CE completed successfully for {sha}.")
    print("The quality gate is informational and does not control this command.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
