"""Validation-only, fail-closed gh stand-in; never dispatches a real command.

Each normalized argv owns a finite ordered response sequence. A private state
folder is bound to the exact scenario bytes; use a new folder for a new run.
Invoke from the isolated source root; state must be outside that directory.
Missing counters or logs in an initialized state fail closed rather than replay.
Counters are atomically replaced while holding an exclusive flock. A process
interrupted after reservation can consume a response without delivering it;
this helper does not promise crash-transactional stdout delivery.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_MAX_SCENARIO_BYTES = 8 * 1024 * 1024
_MAX_COMMANDS = 2048
_MAX_RESPONSES = 256
_ALIASES = {
    "-R": "--repo",
    "-X": "--method",
    "-F": "--field",
    "-f": "--raw-field",
    "-q": "--jq",
    "-t": "--template",
    "-L": "--limit",
    "-i": "--include",
    "-h": "--help",
}
_COMMON = {"--repo", "--json", "--jq", "--template", "--help"}
_LIST = {
    "--state",
    "--base",
    "--head",
    "--limit",
    "--search",
    "--author",
    "--assignee",
    "--label",
    "--draft",
}
_API = {
    "--method",
    "--header",
    "--field",
    "--raw-field",
    "--jq",
    "--paginate",
    "--slurp",
    "--include",
    "--silent",
    "--hostname",
    "--help",
}
_FLAGS = {"--help", "--draft", "--paginate", "--slurp", "--include", "--silent"}
_REPEATABLE = {"--header", "--field", "--raw-field", "--label"}
_OPTIONS = _COMMON | _LIST | _API


class StubError(Exception):
    """Invalid input or an unavailable registered observation."""


@dataclass(frozen=True)
class Response:
    stdout: str
    stderr: str
    exit_code: int


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    responses: tuple[Response, ...]


@dataclass(frozen=True)
class Scenario:
    digest: str
    commands: dict[tuple[str, ...], Command]


class Arguments(argparse.Namespace):
    scenario: str
    state_dir: str
    command: list[str]


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise StubError(f"{label} must be an object")
    result: dict[str, object] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            raise StubError(f"{label} keys must be strings")
        result[key] = item
    return result


def _sequence(value: object, label: str, maximum: int) -> list[object]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise StubError(f"{label} must be a nonempty array of at most {maximum} items")
    return cast(list[object], value)


def _keys(value: dict[str, object], expected: set[str], label: str) -> None:
    if value.keys() != expected:
        raise StubError(f"{label} requires exactly {', '.join(sorted(expected))}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StubError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode(text: str, label: str) -> object:
    try:
        value: object = json.loads(text, object_pairs_hook=_unique_object)
        return value
    except (ValueError, RecursionError) as exc:
        raise StubError(f"invalid {label} JSON: {exc}") from exc


def normalize(argv: list[str]) -> tuple[str, ...]:
    """Normalize only declared read syntax; reject unknown or mutating syntax."""
    if argv and argv[0] == "gh":
        argv = argv[1:]
    if not 1 <= len(argv) <= 256 or any(
        not token or len(token) > 16384 or "\x00" in token for token in argv
    ):
        raise StubError("command must contain 1..256 nonempty bounded arguments")
    for token in argv:
        token.encode("utf-8")
    if argv in (["--version"], ["version"], ["--help"], ["help"]):
        return tuple(argv)
    if argv[0] == "help":
        if all(token in {"pr", "view", "list", "repo", "api"} for token in argv[1:]):
            return tuple(argv)
        raise StubError("unsupported help command")

    positional: list[str] = []
    options: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    index = 0
    while index < len(argv):
        token = argv[index]
        index += 1
        if not token.startswith("-"):
            positional.append(token)
            continue
        name, separator, inline = token.partition("=")
        name = _ALIASES.get(name, name)
        if name not in _OPTIONS and name != "-H":
            raise StubError(f"unsupported option: {name}")
        value: str | None = None
        if name in _FLAGS:
            if separator:
                raise StubError(f"flag takes no value: {name}")
        else:
            if separator:
                value = inline
            else:
                if index == len(argv) or argv[index].startswith("-"):
                    raise StubError(f"option requires a value: {name}")
                value = argv[index]
                index += 1
            if not value:
                raise StubError(f"option requires a nonempty value: {name}")
            if name == "--json":
                fields = [field.strip() for field in value.split(",")]
                if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", f) for f in fields):
                    raise StubError("--json requires comma-separated field names")
                value = ",".join(sorted(set(fields)))
            if name == "--method":
                if value.upper() != "GET":
                    raise StubError("only explicit API GET reads are allowed")
                value = "GET"
        options.append((name, value))

    # gh assigns -H by command: PR-list head filter versus API request header.
    normalized_options: list[tuple[str, str | None]] = []
    for name, value in options:
        if name == "-H":
            name = "--head" if positional[:2] == ["pr", "list"] else "--header"
        if name in seen and name not in _REPEATABLE:
            raise StubError(f"unsupported or duplicate option: {name}")
        seen.add(name)
        normalized_options.append((name, value))
    options = normalized_options

    if seen == {"--help"} and positional in (["pr"], ["repo"], ["api"]):
        return (*positional, "--help")

    if positional[:2] in (["pr", "view"], ["pr", "list"], ["repo", "view"]):
        operation = positional[:2]
        maximum = 2 if operation == ["pr", "list"] else 3
        if len(positional) > maximum:
            raise StubError("too many positional read arguments")
        allowed = _COMMON | (_LIST if operation == ["pr", "list"] else set())
        if operation == ["repo", "view"]:
            allowed = allowed - {"--repo"}
    elif positional[:1] == ["api"] and len(positional) == 2:
        allowed = _API
        if "--method" not in seen:
            raise StubError("API reads require explicit --method GET")
    else:
        raise StubError("unsupported command; only pr view/list, repo view and API GET")
    if not seen <= allowed:
        raise StubError("option is not supported for this read command")
    normalized = positional.copy()
    for name, value in sorted(options, key=lambda option: option[0]):
        normalized.append(name)
        if value is not None:
            normalized.append(value)
    return tuple(normalized)


def load_scenario(path: Path) -> Scenario:
    with path.open("rb") as stream:
        data = stream.read(_MAX_SCENARIO_BYTES + 1)
    if len(data) > _MAX_SCENARIO_BYTES:
        raise StubError("scenario exceeds 8 MiB")
    root = _mapping(_decode(data.decode("utf-8"), "scenario"), "scenario")
    _keys(root, {"version", "commands"}, "scenario")
    if type(root["version"]) is not int or root["version"] != 1:
        raise StubError("scenario version must be integer 1")
    commands: dict[tuple[str, ...], Command] = {}
    for item in _sequence(root["commands"], "commands", _MAX_COMMANDS):
        record = _mapping(item, "command")
        _keys(record, {"argv", "responses"}, "command")
        raw_argv = _sequence(record["argv"], "argv", 256)
        argv: list[str] = []
        for token in raw_argv:
            if not isinstance(token, str):
                raise StubError("argv items must be strings")
            argv.append(token)
        key = normalize(argv)
        if key in commands:
            raise StubError("duplicate normalized command")
        responses: list[Response] = []
        for raw_response in _sequence(record["responses"], "responses", _MAX_RESPONSES):
            response = _mapping(raw_response, "response")
            _keys(response, {"stdout", "stderr", "exit_code"}, "response")
            stdout, stderr, code = (
                response["stdout"],
                response["stderr"],
                response["exit_code"],
            )
            if not isinstance(stdout, str) or not isinstance(stderr, str):
                raise StubError("response stdout and stderr must be strings")
            stdout.encode("utf-8")
            stderr.encode("utf-8")
            if (
                not isinstance(code, int)
                or isinstance(code, bool)
                or not 0 <= code <= 255
            ):
                raise StubError("response exit_code must be an integer in 0..255")
            responses.append(Response(stdout, stderr, code))
        commands[key] = Command(key, tuple(responses))
    return Scenario(hashlib.sha256(data).hexdigest(), commands)


def _private_open(path: Path, flags: int) -> int:
    descriptor = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        os.close(descriptor)
        raise StubError(f"state file must be a private owned regular file: {path.name}")
    return descriptor


def _load_counters(path: Path, scenario: Scenario) -> dict[str, int]:
    if not path.exists() and not path.is_symlink():
        return {}
    with os.fdopen(_private_open(path, os.O_RDONLY), encoding="utf-8") as stream:
        text = stream.read(_MAX_SCENARIO_BYTES + 1)
    if len(text) > _MAX_SCENARIO_BYTES:
        raise StubError("state exceeds size limit")
    root = _mapping(_decode(text, "state"), "state")
    _keys(root, {"scenario_sha256", "positions"}, "state")
    if root["scenario_sha256"] != scenario.digest:
        raise StubError("state directory belongs to different scenario bytes")
    positions = _mapping(root["positions"], "positions")
    lengths = {
        _command_id(command.argv): len(command.responses)
        for command in scenario.commands.values()
    }
    counters: dict[str, int] = {}
    for key, value in positions.items():
        if (
            key not in lengths
            or not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= lengths[key]
        ):
            raise StubError("invalid state response position")
        counters[key] = value
    return counters


def _command_id(argv: tuple[str, ...]) -> str:
    return hashlib.sha256(json.dumps(argv).encode("utf-8")).hexdigest()


def _save_counters(path: Path, scenario: Scenario, counters: dict[str, int]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".counters-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {"scenario_sha256": scenario.digest, "positions": counters}, stream
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def observe(scenario: Scenario, state_dir: Path, argv: list[str]) -> Response:
    key = normalize(argv)
    command = scenario.commands.get(key)
    if command is None:
        raise StubError(f"unregistered read command: {json.dumps(key)}")
    if state_dir.resolve().is_relative_to(Path.cwd().resolve()):
        raise StubError("state directory must be outside the source working directory")
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = state_dir.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise StubError("state directory must be a private owned directory (0700)")
    with os.fdopen(
        _private_open(state_dir / "lock", os.O_CREAT | os.O_RDWR), "r+"
    ) as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        counter_path = state_dir / "counters.json"
        log_path = state_dir / "calls.jsonl"
        has_counters = counter_path.exists() or counter_path.is_symlink()
        has_log = log_path.exists() or log_path.is_symlink()
        if has_counters != has_log:
            raise StubError("incomplete state: counters and call log must both exist")
        counters = _load_counters(counter_path, scenario)
        identifier = _command_id(key)
        index = counters.get(identifier, 0)
        if index >= len(command.responses):
            raise StubError(
                f"response sequence exhausted at index {index}: {json.dumps(key)}"
            )
        response = command.responses[index]
        with os.fdopen(
            _private_open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY),
            "a",
            encoding="utf-8",
        ) as log:
            counters[identifier] = index + 1
            _save_counters(counter_path, scenario, counters)
            log.write(
                json.dumps(
                    {
                        "argv": key,
                        "response_index": index,
                        "exit_code": response.exit_code,
                    }
                )
                + "\n"
            )
            log.flush()
            os.fsync(log.fileno())
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = Arguments()
    parser.parse_args(argv, namespace=arguments)
    command = arguments.command
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        scenario = load_scenario(Path(arguments.scenario))
        response = observe(scenario, Path(arguments.state_dir), command)
    except (StubError, OSError, UnicodeError) as exc:
        sys.stderr.write(f"provider_stub: {exc}\n")
        return 2
    sys.stdout.write(response.stdout)
    sys.stderr.write(response.stderr)
    return response.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
