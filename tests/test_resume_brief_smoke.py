"""Manual smoke-driver failures remain honest without launching a coding host."""

from __future__ import annotations

import importlib.util
import json
import os
import pty
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

FEATURE = Path(__file__).resolve().parents[1] / "extensions" / "resume-brief"


def load_driver(host: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_resume_brief_{host}_boundary", FEATURE / "tests" / f"{host}-smoke.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_exited_process_keeps_its_buffered_final_response(tmp_path: Path) -> None:
    driver = load_driver("claude")
    native = driver.NativeTTY([], tmp_path, {})
    master, slave = pty.openpty()
    try:
        native.master = master
        native.process = subprocess.Popen(
            [sys.executable, "-c", "print('claude --resume synthetic')"],
            stdin=subprocess.DEVNULL,
            stdout=slave,
            stderr=slave,
        )
        native.process.wait(timeout=5)
        output = native.read(lambda value: b"--resume synthetic" in value)
        assert b"claude --resume synthetic" in output
    finally:
        os.close(slave)
        os.close(master)


def test_buffered_trust_prompt_is_not_accepted_as_final_response(
    tmp_path: Path,
) -> None:
    driver = load_driver("claude")
    native = driver.NativeTTY([], tmp_path, {})
    master, slave = pty.openpty()
    try:
        native.master = master
        native.process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "print('trust this folder; claude --resume synthetic')",
            ],
            stdin=subprocess.DEVNULL,
            stdout=slave,
            stderr=slave,
        )
        native.process.wait(timeout=5)
        with pytest.raises(
            driver.Unavailable,
            match="native-trust-login-or-policy-interaction-required",
        ):
            native.read(lambda value: b"--resume synthetic" in value)
        assert native.interaction_required is True
    finally:
        os.close(slave)
        os.close(master)


def test_empty_version_writes_unavailable_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = load_driver("claude")
    tool = tmp_path / "empty-version"
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o700)
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        driver, "context", lambda args: (tmp_path, tmp_path / "settings")
    )
    monkeypatch.setattr(driver.shutil, "which", lambda name: str(tool))
    monkeypatch.setattr(
        sys, "argv", ["smoke", "--feature-dir", str(FEATURE), "--report", str(report)]
    )
    previous = os.umask(0o077)
    try:
        assert driver.main() == 3
    finally:
        os.umask(previous)
    observed = json.loads(report.read_text())
    assert observed["status"] == "unavailable"
    assert observed["reasonCode"] == "native-version-unavailable"
    assert all(case["status"] == "not-run" for case in observed["scenarios"])


@pytest.mark.parametrize("host", ["omp", "claude"])
def test_protocol_lookup_failure_still_writes_unavailable_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    driver = load_driver(host)
    report = tmp_path / "report.json"

    def malformed_protocol(*args: object) -> None:
        raise IndexError("private protocol detail")

    monkeypatch.setattr(driver, "execute", malformed_protocol)
    monkeypatch.setattr(
        sys, "argv", ["smoke", "--feature-dir", str(FEATURE), "--report", str(report)]
    )
    previous = os.umask(0o077)
    try:
        assert driver.main() == 3
    finally:
        os.umask(previous)
    observed = json.loads(report.read_text())
    assert observed["status"] == "unavailable"
    assert observed["reasonCode"] == "native-prerequisite-or-protocol-unavailable"
    assert "private protocol detail" not in report.read_text()
