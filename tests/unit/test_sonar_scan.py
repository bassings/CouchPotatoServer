"""Regression tests for the local-only SonarQube scan orchestrator."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import BaseHandler, ProxyHandler, Request, build_opener
from urllib.response import addinfourl

import pytest

from scripts import sonar_scan
from tests.unit.conftest import sanitized_git_env


SHA_A = "a" * 40
SHA_B = "b" * 40
TOKEN = "sqa_test-analysis-token"


def configured_sonar_roots(properties: str) -> set[str]:
    roots = []
    for key in ("sonar.sources", "sonar.tests"):
        match = re.search(rf"^{re.escape(key)}=([^\n]+)$", properties, re.MULTILINE)
        assert match, f"{key} must remain a simple comma-separated property"
        roots.extend(part.strip().removeprefix("./").rstrip("/") for part in match.group(1).split(","))
    result = {root for root in roots if root}
    assert result, "Sonar root discovery must not pass vacuously"
    return result


def staleness_script_roots(script: str) -> set[str]:
    match = re.search(r"^ANALYSED_PATHS=\(([^)]*)\)$", script, re.MULTILINE)
    assert match, "staleness pathscope declaration is missing"
    result = {part.removeprefix("./").rstrip("/") for part in shlex.split(match.group(1))}
    assert result, "staleness root discovery must not pass vacuously"
    return result


def assert_staleness_roots_synced(properties: str, script: str) -> None:
    assert staleness_script_roots(script) == configured_sonar_roots(properties)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class FakeCommands:
    def __init__(self, repo: Path, sha: str = SHA_A):
        self.repo = repo
        self.sha = sha
        self.branch = "master"
        self.dirty = False
        self.change_head_after_coverage = False
        self.drift_after_npm = None
        self.drift_after_scanner = None
        self.write_scanner_report = True
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if argv[:3] == ["git", "symbolic-ref", "--short"]:
            stdout = self.branch + "\n"
        elif argv[:3] == ["git", "status", "--porcelain"]:
            stdout = " M tracked.py\n" if self.dirty else ""
        elif argv[:3] == ["git", "rev-parse", "HEAD"]:
            stdout = self.sha + "\n"
        elif argv[-1:] == ["coverage"]:
            stdout = ""
            if self.change_head_after_coverage:
                self.sha = SHA_B
        elif argv[0] == "npm":
            stdout = ""
            if self.drift_after_npm == "branch":
                self.branch = "feature"
            elif self.drift_after_npm == "dirty":
                self.dirty = True
            elif self.drift_after_npm == "head":
                self.sha = SHA_B
        elif argv[0] == "node":
            stdout = ""
            if self.write_scanner_report:
                report = self.repo / ".scannerwork" / "report-task.txt"
                report.parent.mkdir(exist_ok=True)
                report.write_text("taskId=ce-task-123\nserverUrl=http://evil.invalid\n")
            if self.drift_after_scanner == "branch":
                self.branch = "feature"
            elif self.drift_after_scanner == "dirty":
                self.dirty = True
            elif self.drift_after_scanner == "head":
                self.sha = SHA_B
        else:  # pragma: no cover - makes unexpected command shapes obvious
            raise AssertionError(f"unexpected command: {argv}")
        return subprocess.CompletedProcess(argv, 0, stdout, "")


def config(tmp_path: Path, sha: str = SHA_A):
    token_file = tmp_path / "token"
    token_file.write_text(f"SONAR_TOKEN={TOKEN}\n")
    return sonar_scan.Config(
        repo=tmp_path,
        host_url="http://sonar.internal:9000",
        token_file=token_file,
        scanner_version="5.0.0",
        make_command="make",
    )


def success_opener(request, timeout):
    assert request.full_url == "http://sonar.internal:9000/api/ce/task?id=ce-task-123"
    assert request.get_header("Authorization").startswith("Basic ")
    assert timeout > 0
    return Response({"task": {"status": "SUCCESS"}})


@pytest.mark.parametrize("sha", [SHA_A, SHA_B])
def test_success_uses_exact_sha_without_token_in_argv_and_stamps_after_ce(tmp_path, sha):
    cfg = config(tmp_path, sha)
    commands = FakeCommands(tmp_path, sha)

    sonar_scan.run_scan(cfg, run=commands, open_url=success_opener)

    scanner_argv, scanner_kwargs = next(call for call in commands.calls if call[0][0] == "node")
    assert f"-Dsonar.projectVersion={sha}" in scanner_argv
    assert f"-Dsonar.scm.revision={sha}" in scanner_argv
    assert all(TOKEN not in arg for arg in scanner_argv)
    assert scanner_kwargs["env"]["SONAR_TOKEN"] == TOKEN
    assert all(
        "SONAR_TOKEN" not in kwargs["env"]
        for argv, kwargs in commands.calls
        if argv[0] != "node"
    )
    assert (tmp_path / ".sonar-last-analysis").read_text().splitlines()[0] == sha


def test_all_child_environments_scrub_ambient_admin_token(tmp_path, monkeypatch):
    monkeypatch.setenv("SONAR_ADMIN_TOKEN", "squ_ambient-admin-token")
    cfg = config(tmp_path)
    commands = FakeCommands(tmp_path)

    sonar_scan.run_scan(cfg, run=commands, open_url=success_opener)

    assert all("SONAR_ADMIN_TOKEN" not in kwargs["env"] for _argv, kwargs in commands.calls)


def test_token_bearing_scanner_scrubs_node_preloads(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE_OPTIONS", "--require=/tmp/must-not-run-before-scanner.js")
    commands = FakeCommands(tmp_path)

    sonar_scan.run_scan(config(tmp_path), run=commands, open_url=success_opener)

    _argv, scanner_kwargs = next(call for call in commands.calls if call[0][0] == "node")
    assert "NODE_OPTIONS" not in scanner_kwargs["env"]
    assert Path(_argv[1]).parts[-4:] == (
        "node_modules",
        "sonarqube-scanner",
        "bin",
        "sonar-scanner.js",
    )


def test_all_child_environments_scrub_the_npm_config_namespace(tmp_path, monkeypatch):
    monkeypatch.setenv("npm_config_node_options", "--require=/tmp/lowercase-preload.js")
    monkeypatch.setenv("NPM_CONFIG_NODE_OPTIONS", "--require=/tmp/uppercase-preload.js")
    monkeypatch.setenv("npm_config_future_preload_option", "must-not-survive")
    commands = FakeCommands(tmp_path)

    sonar_scan.run_scan(config(tmp_path), run=commands, open_url=success_opener)

    assert all(
        not any(name.lower().startswith("npm_config_") for name in kwargs["env"])
        for _argv, kwargs in commands.calls
    )


def test_scanner_install_uses_distinct_empty_configs_without_the_token(tmp_path):
    commands = FakeCommands(tmp_path)
    observed = {}

    def inspect_install(argv, **kwargs):
        if argv[0] == "npm":
            config_paths = [
                Path(argument.split("=", 1)[1])
                for argument in argv
                if argument.startswith(("--userconfig=", "--globalconfig="))
            ]
            observed["config_paths"] = config_paths
            observed["argv"] = argv
            observed["contents"] = [path.read_text() for path in config_paths]
            observed["cwd"] = kwargs["cwd"]
            observed["has_token"] = "SONAR_TOKEN" in kwargs["env"]
        return commands(argv, **kwargs)

    sonar_scan.run_scan(config(tmp_path), run=inspect_install, open_url=success_opener)

    assert len(set(observed["config_paths"])) == 2
    assert observed["contents"] == ["", ""]
    assert observed["cwd"] != tmp_path
    assert observed["has_token"] is False
    assert observed["argv"] == [
        "npm",
        "install",
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
        "--package-lock=false",
        f"--userconfig={observed['config_paths'][0]}",
        f"--globalconfig={observed['config_paths'][1]}",
        "sonarqube-scanner@5.0.0",
    ]


def test_direct_node_scanner_does_not_execute_user_npm_hooks(tmp_path, monkeypatch):
    marker = tmp_path / "preload-ran"
    preload = tmp_path / "preload.js"
    preload.write_text(
        "require('node:fs').writeFileSync(process.env.PRELOAD_MARKER, "
        "process.env.SONAR_TOKEN || 'missing')\n"
    )
    npm_home = tmp_path / "home"
    npm_home.mkdir()
    shell_hook = tmp_path / "script-shell"
    shell_hook.write_text(f"#!/bin/sh\necho shell > {marker}\nexec /bin/sh \"$@\"\n")
    shell_hook.chmod(0o700)
    (npm_home / ".npmrc").write_text(
        f"node-options=--require={preload}\nscript-shell={shell_hook}\n"
    )
    monkeypatch.setenv("HOME", str(npm_home))
    monkeypatch.setenv("PRELOAD_MARKER", str(marker))
    env = sonar_scan._safe_env()
    env["SONAR_TOKEN"] = "sqa_execution-sentinel"

    subprocess.run(
        ["node", "-e", "process.exit(0)"],
        cwd=Path.cwd(),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert not marker.exists()


def test_all_child_environments_scrub_upper_and_lower_proxy_variables(tmp_path, monkeypatch):
    proxy_names = [
        "http_proxy",
        "HTTP_PROXY",
        "https_proxy",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
        "ftp_proxy",
        "FTP_PROXY",
        "no_proxy",
        "NO_PROXY",
    ]
    for name in proxy_names:
        monkeypatch.setenv(name, "http://proxy.invalid:8080")
    commands = FakeCommands(tmp_path)

    sonar_scan.run_scan(config(tmp_path), run=commands, open_url=success_opener)

    assert all(
        not any(name.lower().endswith("_proxy") for name in kwargs["env"])
        for _argv, kwargs in commands.calls
    )


def test_all_child_environments_scrub_every_git_variable(tmp_path, monkeypatch):
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_FUTURE_SENTINEL",
    ):
        monkeypatch.setenv(name, "/tmp/must-not-survive")
    commands = FakeCommands(tmp_path)

    sonar_scan.run_scan(config(tmp_path), run=commands, open_url=success_opener)

    assert all(
        not any(name.startswith("GIT_") for name in kwargs["env"])
        for _argv, kwargs in commands.calls
    )


@pytest.mark.parametrize("prefix", ["sqa_", "sqp_"])
def test_analysis_token_prefixes_are_accepted(tmp_path, prefix):
    cfg = config(tmp_path)
    cfg.token_file.write_text(f"SONAR_TOKEN={prefix}test-token\n")
    sonar_scan.run_scan(cfg, run=FakeCommands(tmp_path), open_url=success_opener)


@pytest.mark.parametrize("value", ["squ_admin-token", "", "not-a-sonar-token", "sqa_not valid"])
def test_bad_or_admin_token_is_rejected_before_any_external_work(tmp_path, value):
    cfg = config(tmp_path)
    cfg.token_file.write_text(f"SONAR_TOKEN={value}\n")
    commands = FakeCommands(tmp_path)

    with pytest.raises(sonar_scan.ScanError, match="analysis token"):
        sonar_scan.run_scan(cfg, run=commands, open_url=success_opener)

    assert commands.calls == []


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [("branch", "feature", "master"), ("dirty", True, "clean")],
)
def test_checkout_preflight_fails_before_coverage(tmp_path, attribute, value, message):
    cfg = config(tmp_path)
    commands = FakeCommands(tmp_path)
    setattr(commands, attribute, value)
    stamp = tmp_path / ".sonar-last-analysis"
    stamp.write_text("previous\n")

    with pytest.raises(sonar_scan.ScanError, match=message):
        sonar_scan.run_scan(cfg, run=commands, open_url=success_opener)

    assert not any(call[0][-1:] == ["coverage"] for call in commands.calls)
    assert not any(call[0][0] in {"npm", "node"} for call in commands.calls)
    assert stamp.read_text() == "previous\n"


def test_non_exact_sha_fails_before_coverage(tmp_path):
    cfg = config(tmp_path)
    commands = FakeCommands(tmp_path, "short-sha")

    with pytest.raises(sonar_scan.ScanError, match="40-character"):
        sonar_scan.run_scan(cfg, run=commands, open_url=success_opener)

    assert not any(call[0][-1:] == ["coverage"] for call in commands.calls)


def test_head_change_after_coverage_refuses_upload(tmp_path):
    cfg = config(tmp_path)
    commands = FakeCommands(tmp_path)
    commands.change_head_after_coverage = True

    with pytest.raises(sonar_scan.ScanError, match="HEAD changed"):
        sonar_scan.run_scan(cfg, run=commands, open_url=success_opener)

    assert not any(call[0][0] in {"npm", "node"} for call in commands.calls)


@pytest.mark.parametrize("drift", ["branch", "dirty", "head"])
def test_checkout_drift_during_npm_install_refuses_upload(tmp_path, drift):
    cfg = config(tmp_path)
    commands = FakeCommands(tmp_path)
    commands.drift_after_npm = drift

    with pytest.raises(sonar_scan.ScanError):
        sonar_scan.run_scan(cfg, run=commands, open_url=success_opener)

    assert any(call[0][0] == "npm" for call in commands.calls)
    assert not any(call[0][0] == "node" for call in commands.calls)


@pytest.mark.parametrize("drift", ["branch", "dirty", "head"])
def test_post_scanner_checkout_drift_preserves_stamp_and_disregards_upload(tmp_path, drift):
    cfg = config(tmp_path)
    commands = FakeCommands(tmp_path)
    commands.drift_after_scanner = drift
    stamp = tmp_path / ".sonar-last-analysis"
    stamp.write_text("previous\n")

    with pytest.raises(sonar_scan.ScanError, match="uploaded result must be disregarded and re-run"):
        sonar_scan.run_scan(cfg, run=commands, open_url=success_opener)

    assert stamp.read_text() == "previous\n"


def test_scan_order_revalidates_after_upload_before_ce_and_stamp(tmp_path, monkeypatch):
    events = []
    commands = FakeCommands(tmp_path)
    revision_reads = 0

    def ordered_commands(argv, **kwargs):
        nonlocal revision_reads
        result = commands(argv, **kwargs)
        if argv[-1:] == ["coverage"]:
            events.append("coverage")
        elif argv[:3] == ["git", "rev-parse", "HEAD"]:
            revision_reads += 1
            if revision_reads == 2:
                events.append("recheck")
            elif revision_reads == 3:
                events.append("upload-boundary-check")
            elif revision_reads == 4:
                events.append("postcheck")
        elif argv[0] == "node":
            events.append("scanner")
        return result

    statuses = iter(["PENDING", "IN_PROGRESS", "SUCCESS"])

    def ordered_opener(*_args, **_kwargs):
        status = next(statuses)
        events.append(status)
        return Response({"task": {"status": status}})

    original_stamp = sonar_scan.write_stamp_atomically

    def ordered_stamp(path, sha):
        events.append("stamp")
        original_stamp(path, sha)

    monkeypatch.setattr(sonar_scan, "write_stamp_atomically", ordered_stamp)
    sonar_scan.run_scan(
        config(tmp_path),
        run=ordered_commands,
        open_url=ordered_opener,
        sleep=lambda _seconds: None,
    )

    assert events == [
        "coverage",
        "recheck",
        "upload-boundary-check",
        "scanner",
        "postcheck",
        "PENDING",
        "IN_PROGRESS",
        "SUCCESS",
        "stamp",
    ]


@pytest.mark.parametrize("status", ["FAILED", "CANCELED"])
def test_terminal_ce_failure_preserves_previous_stamp(tmp_path, status):
    cfg = config(tmp_path)
    stamp = tmp_path / ".sonar-last-analysis"
    stamp.write_text("previous\nold-time\n")

    with pytest.raises(sonar_scan.ScanError, match=status):
        sonar_scan.run_scan(
            cfg,
            run=FakeCommands(tmp_path),
            open_url=lambda *_args, **_kwargs: Response({"task": {"status": status}}),
        )

    assert stamp.read_text() == "previous\nold-time\n"


@pytest.mark.parametrize("payload", [{}, {"task": {}}, {"task": {"status": 7}}])
def test_malformed_ce_response_preserves_previous_stamp(tmp_path, payload):
    cfg = config(tmp_path)
    stamp = tmp_path / ".sonar-last-analysis"
    stamp.write_text("previous\n")

    with pytest.raises(sonar_scan.ScanError, match="malformed"):
        sonar_scan.run_scan(
            cfg,
            run=FakeCommands(tmp_path),
            open_url=lambda *_args, **_kwargs: Response(payload),
        )

    assert stamp.read_text() == "previous\n"


def test_ce_auth_failure_preserves_previous_stamp(tmp_path):
    cfg = config(tmp_path)
    stamp = tmp_path / ".sonar-last-analysis"
    stamp.write_text("previous\n")

    def unauthorized(request, timeout):
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    with pytest.raises(sonar_scan.ScanError, match="authentication"):
        sonar_scan.run_scan(cfg, run=FakeCommands(tmp_path), open_url=unauthorized)

    assert stamp.read_text() == "previous\n"


def test_ce_timeout_is_bounded_and_preserves_previous_stamp(tmp_path):
    cfg = config(tmp_path)
    cfg.poll_timeout = 1.0
    stamp = tmp_path / ".sonar-last-analysis"
    stamp.write_text("previous\n")
    ticks = iter([0.0, 0.5, 1.1])

    with pytest.raises(sonar_scan.ScanError, match="timed out"):
        sonar_scan.run_scan(
            cfg,
            run=FakeCommands(tmp_path),
            open_url=lambda *_args, **_kwargs: Response({"task": {"status": "PENDING"}}),
            sleep=lambda _seconds: None,
            monotonic=lambda: next(ticks),
        )

    assert stamp.read_text() == "previous\n"


def test_report_task_requires_task_id_and_ignores_report_server_url(tmp_path):
    report = tmp_path / "report-task.txt"
    report.write_text("serverUrl=http://evil.invalid\n")
    with pytest.raises(sonar_scan.ScanError, match="taskId"):
        sonar_scan.read_task_id(report)


def test_missing_ce_task_id_after_upload_preserves_previous_stamp(tmp_path):
    cfg = config(tmp_path)
    stamp = tmp_path / ".sonar-last-analysis"
    stamp.write_text("previous\n")
    commands = FakeCommands(tmp_path)

    def scanner_without_task(argv, **kwargs):
        result = commands(argv, **kwargs)
        if argv[0] == "node":
            (tmp_path / ".scannerwork" / "report-task.txt").write_text(
                "serverUrl=http://evil.invalid\n"
            )
        return result

    with pytest.raises(sonar_scan.ScanError, match="taskId"):
        sonar_scan.run_scan(cfg, run=scanner_without_task, open_url=success_opener)

    assert stamp.read_text() == "previous\n"


def test_stale_report_is_removed_and_cannot_be_reused(tmp_path):
    cfg = config(tmp_path)
    report = tmp_path / ".scannerwork" / "report-task.txt"
    report.parent.mkdir()
    report.write_text("taskId=stale-task\n")
    stamp = tmp_path / ".sonar-last-analysis"
    stamp.write_text("previous\n")
    commands = FakeCommands(tmp_path)
    commands.write_scanner_report = False

    with pytest.raises(sonar_scan.ScanError, match="did not produce"):
        sonar_scan.run_scan(cfg, run=commands, open_url=success_opener)

    assert not report.exists()
    assert stamp.read_text() == "previous\n"


def test_real_urllib_redirect_handler_refuses_cross_origin_redirect():
    requested_urls = []

    class RedirectTransport(BaseHandler):
        handler_order = 100

        def http_open(self, request):
            requested_urls.append(request.full_url)
            headers = Message()
            headers["Location"] = "http://attacker.invalid/steal"
            response = addinfourl(BytesIO(b""), headers, request.full_url, 302)
            response.msg = "Found"
            return response

    opener = build_opener(RedirectTransport(), sonar_scan.NoRedirectHandler())
    request = Request(
        "http://sonar.internal/api/ce/task?id=1",
        headers={"Authorization": "Basic test-only"},
    )

    with pytest.raises(HTTPError) as caught:
        opener.open(request)

    assert caught.value.code == 302
    assert requested_urls == ["http://sonar.internal/api/ce/task?id=1"]


def test_real_ce_opener_disables_ambient_proxy_routing(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    routed_requests = []

    class DirectTransport(BaseHandler):
        handler_order = 100

        def http_open(self, request):
            routed_requests.append((request.host, request.selector, request.get_header("Authorization")))
            response = addinfourl(BytesIO(b"{}"), Message(), request.full_url, 200)
            response.msg = "OK"
            return response

    opener = sonar_scan.build_ce_opener(DirectTransport())
    proxy_handlers = [handler for handler in opener.handlers if isinstance(handler, ProxyHandler)]
    request = Request(
        "http://sonar.internal/api/ce/task?id=1",
        headers={"Authorization": "Basic test-only"},
    )

    with opener.open(request) as response:
        assert response.status == 200

    # urllib omits an explicit empty ProxyHandler from ``handlers``, but its
    # presence during build suppresses the environment-backed default.
    assert all(handler.proxies == {} for handler in proxy_handlers)
    assert routed_requests == [
        ("sonar.internal", "/api/ce/task?id=1", "Basic test-only"),
    ]


def test_project_properties_names_make_sonar_as_only_scan_interface():
    properties = Path("sonar-project.properties").read_text()
    instructions = properties.split("sonar.projectKey=", 1)[0]

    assert "make sonar" in instructions
    assert "SONAR_HOST_URL" in instructions
    assert "SONAR_TOKEN_FILE" in instructions
    assert "SONAR_SCANNER_VERSION" in instructions
    assert "npx" not in instructions
    assert "set -a" not in instructions


def test_scanner_cli_has_no_embedded_host_default(tmp_path):
    args = sonar_scan.parse_args(["--token-file", str(tmp_path / "token")])

    assert args.host_url is None


def test_check_token_cli_does_not_require_host(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text(f"SONAR_TOKEN={TOKEN}\n")

    assert sonar_scan.main(["--token-file", str(token_file), "--check-token"]) == 0


def test_scan_cli_requires_explicit_host_before_starting(tmp_path, monkeypatch, capsys):
    token_file = tmp_path / "token"
    token_file.write_text(f"SONAR_TOKEN={TOKEN}\n")

    def unexpected_scan(_config):
        raise AssertionError("scan must not start without an explicit host")

    monkeypatch.setattr(sonar_scan, "run_scan", unexpected_scan)

    assert sonar_scan.main(["--token-file", str(token_file)]) == 1
    assert "--host-url is required" in capsys.readouterr().err


def make_staleness_repo(tmp_path, relative_path):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(Path("scripts/sonar_staleness.sh"), scripts)
    subprocess.run(
        ["git", "init", "-b", "master"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=sanitized_git_env(),
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=repo,
        check=True,
        env=sanitized_git_env(),
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        env=sanitized_git_env(),
    )
    tracked = repo / relative_path
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("first\n")
    subprocess.run(
        ["git", "add", "scripts/sonar_staleness.sh", relative_path],
        cwd=repo,
        check=True,
        env=sanitized_git_env(),
    )
    subprocess.run(
        ["git", "commit", "-m", "fixture"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=sanitized_git_env(),
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=sanitized_git_env(),
    ).stdout.strip()
    (repo / ".sonar-last-analysis").write_text(f"{sha}\n2026-09-15T00:00:00Z\n")
    return repo, tracked


def make_git_repo(path: Path, relative_path: str, contents: str) -> str:
    path.mkdir()
    subprocess.run(
        ["git", "init", "-b", "master"],
        cwd=path,
        check=True,
        capture_output=True,
        env=sanitized_git_env(),
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=path,
        check=True,
        env=sanitized_git_env(),
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
        env=sanitized_git_env(),
    )
    tracked = path / relative_path
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text(contents)
    (path / ".gitignore").write_text("/.scannerwork/\n/.sonar-last-analysis\n")
    subprocess.run(
        ["git", "add", ".gitignore", relative_path],
        cwd=path,
        check=True,
        env=sanitized_git_env(),
    )
    subprocess.run(
        ["git", "commit", "-m", contents.strip()],
        cwd=path,
        check=True,
        capture_output=True,
        env=sanitized_git_env(),
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        env=sanitized_git_env(),
    ).stdout.strip()


def contaminated_git_environment(monkeypatch, other_repo: Path):
    values = {
        "GIT_DIR": other_repo / ".git",
        "GIT_WORK_TREE": other_repo,
        "GIT_INDEX_FILE": other_repo / ".git" / "index",
        "GIT_OBJECT_DIRECTORY": other_repo / ".git" / "objects",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": other_repo / ".git" / "objects",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, str(value))


def test_real_scanner_git_validation_stays_bound_to_configured_repo(tmp_path, monkeypatch):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    sha_a = make_git_repo(repo_a, "app.py", "repository a\n")
    sha_b = make_git_repo(repo_b, "other.py", "repository b\n")
    assert sha_a != sha_b
    contaminated_git_environment(monkeypatch, repo_b)
    token_file = tmp_path / "analysis-token"
    token_file.write_text(f"SONAR_TOKEN={TOKEN}\n")
    scanner_argv = []

    def real_git_runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        if argv[-1:] == ["coverage"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "npm":
            return subprocess.CompletedProcess(argv, 0, "", "")
        assert argv[0] == "node"
        scanner_argv.extend(argv)
        report = repo_a / ".scannerwork" / "report-task.txt"
        report.parent.mkdir()
        report.write_text("taskId=ce-task-123\n")
        return subprocess.CompletedProcess(argv, 0, "", "")

    cfg = sonar_scan.Config(
        repo=repo_a,
        host_url="http://sonar.internal:9000",
        token_file=token_file,
        scanner_version="5.0.0",
    )

    result = sonar_scan.run_scan(cfg, run=real_git_runner, open_url=success_opener)

    assert result == sha_a
    assert f"-Dsonar.projectVersion={sha_a}" in scanner_argv
    assert f"-Dsonar.projectVersion={sha_b}" not in scanner_argv


def test_real_scanner_git_validation_detects_configured_repo_dirtiness(tmp_path, monkeypatch):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    make_git_repo(repo_a, "app.py", "repository a\n")
    make_git_repo(repo_b, "other.py", "repository b\n")
    contaminated_git_environment(monkeypatch, repo_b)
    (repo_a / "app.py").write_text("dirty repository a\n")
    cfg = sonar_scan.Config(
        repo=repo_a,
        host_url="http://sonar.internal:9000",
        token_file=tmp_path / "unused-token",
        scanner_version="5.0.0",
    )

    with pytest.raises(sonar_scan.ScanError, match="clean checkout"):
        sonar_scan.checkout_sha(cfg, subprocess.run)


def test_staleness_ignores_ambient_git_repository_selection(tmp_path, monkeypatch):
    repo_a, tracked_a = make_staleness_repo(tmp_path / "a", "couchpotato/app.py")
    sha_a = (repo_a / ".sonar-last-analysis").read_text().splitlines()[0]
    repo_b = tmp_path / "repo-b"
    sha_b = make_git_repo(repo_b, "couchpotato/other.py", "repository b\n")
    assert sha_a != sha_b
    tracked_a.write_text("dirty repository a\n")
    contaminated_git_environment(monkeypatch, repo_b)

    result = subprocess.run(
        ["bash", str(repo_a / "scripts" / "sonar_staleness.sh")],
        cwd=repo_a,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"analysis matches HEAD ({sha_a[:12]})" in result.stdout
    assert sha_b[:12] not in result.stdout
    assert "DIRTY" in result.stdout


@pytest.mark.parametrize(
    "relative_path",
    [
        "couchpotato/module.py",
        "scripts/helper.sh",
        "tests/fixture.json",
        "couchpotato/core/schema.sql",
        "CouchPotato.py",
    ],
)
def test_staleness_warns_when_analysed_root_file_is_dirty(tmp_path, relative_path):
    repo, tracked = make_staleness_repo(tmp_path, relative_path)
    tracked.write_text("second\n")

    result = subprocess.run(
        ["bash", str(repo / "scripts" / "sonar_staleness.sh")],
        cwd=repo,
        env={**os.environ, "SONAR_TOKEN": "must-not-be-needed"},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "DIRTY" in result.stdout
    assert "line numbers describe this tree" not in result.stdout.lower()


def test_staleness_ignores_dirty_file_outside_analysis_roots(tmp_path):
    repo, tracked = make_staleness_repo(tmp_path, "docs/note.py")
    tracked.write_text("second\n")

    result = subprocess.run(
        ["bash", str(repo / "scripts" / "sonar_staleness.sh")],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "DIRTY" not in result.stdout
    assert "Line numbers describe this tree." in result.stdout


@pytest.mark.parametrize(
    ("relative_path", "changed_count"),
    [
        ("couchpotato/module.py", 1),
        ("scripts/helper.sh", 1),
        ("tests/fixture.json", 1),
        ("couchpotato/core/schema.sql", 1),
        ("CouchPotato.py", 1),
        ("docs/note.py", 0),
    ],
)
def test_staleness_commit_drift_uses_analysis_roots_for_every_file_type(
    tmp_path, relative_path, changed_count
):
    repo, tracked = make_staleness_repo(tmp_path, relative_path)
    tracked.write_text("second\n")
    subprocess.run(
        ["git", "add", relative_path], cwd=repo, check=True, env=sanitized_git_env()
    )
    subprocess.run(
        ["git", "commit", "-m", "change"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=sanitized_git_env(),
    )

    result = subprocess.run(
        ["bash", str(repo / "scripts" / "sonar_staleness.sh")],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"{changed_count} analysed file(s) changed since." in result.stdout
    assert ("LINE NUMBERS IN FINDINGS ARE UNRELIABLE" in result.stdout) is bool(changed_count)


def test_staleness_pathscope_exactly_matches_configured_sonar_roots():
    assert_staleness_roots_synced(
        Path("sonar-project.properties").read_text(),
        Path("scripts/sonar_staleness.sh").read_text(),
    )


@pytest.mark.parametrize("changed_side", ["properties", "script"])
def test_staleness_root_sync_guard_rejects_one_sided_additions(changed_side):
    properties = Path("sonar-project.properties").read_text()
    script = Path("scripts/sonar_staleness.sh").read_text()
    if changed_side == "properties":
        properties = properties.replace("sonar.tests=tests", "sonar.tests=tests,new-analysis-root")
    else:
        script = script.replace(
            "ANALYSED_PATHS=(couchpotato scripts CouchPotato.py tests)",
            "ANALYSED_PATHS=(couchpotato scripts CouchPotato.py tests new-analysis-root)",
        )

    with pytest.raises(AssertionError):
        assert_staleness_roots_synced(properties, script)
