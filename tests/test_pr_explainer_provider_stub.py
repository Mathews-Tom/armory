"""Consumer-visible, offline CLI regression tests for the fixture-only provider."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

_STUB = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "pr-explainer"
    / "evals"
    / "provider_stub.py"
)
_VIEW = ["pr", "view", "41", "--repo", "example/project", "--json", "number,headRefOid"]
_API = ["api", "repos/example/project/pulls/41", "--method", "GET"]


def _response(
    stdout: str = "registered output", stderr: str = "", exit_code: int = 0
) -> dict[str, object]:
    return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}


def _record(
    argv: list[str], responses: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "argv": argv,
        "responses": responses if responses is not None else [_response()],
    }


def _scenario(tmp_path: Path, commands: list[dict[str, object]]) -> Path:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps({"version": 1, "commands": commands}), encoding="utf-8")
    return path


def _call(
    scenario: Path, state: Path, argv: list[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_STUB),
            "--scenario",
            str(scenario),
            "--state-dir",
            str(state),
            "--",
            *argv,
        ],
        capture_output=True,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )


def _log(state: Path) -> list[dict[str, object]]:
    return [
        cast(dict[str, object], json.loads(line))
        for line in (state / "calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def _assert_rejected(result: subprocess.CompletedProcess[str], reason: str) -> None:
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("provider_stub:")
    assert reason in result.stderr


def test_cli_matches_normalized_read_without_altering_streams(tmp_path: Path) -> None:
    scenario = _scenario(
        tmp_path, [_record(_VIEW, [_response('{"number":41}\n', "notice: café", 7)])]
    )
    state = tmp_path / "state"
    result = _call(
        scenario,
        state,
        [
            "gh",
            "-R",
            "example/project",
            "pr",
            "view",
            "41",
            "--json=headRefOid, number",
        ],
    )

    assert (result.returncode, result.stdout, result.stderr) == (
        7,
        '{"number":41}\n',
        "notice: café",
    )
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in state.iterdir())
    assert _log(state) == [
        {
            "argv": [
                "pr",
                "view",
                "41",
                "--json",
                "headRefOid,number",
                "--repo",
                "example/project",
            ],
            "response_index": 0,
            "exit_code": 7,
        }
    ]
    assert "café" not in (state / "calls.jsonl").read_text(encoding="utf-8")
    assert 'number\\":41' not in (state / "calls.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("repository", [[], ["example/project"]])
def test_repo_view_accepts_optional_positional_repository(
    tmp_path: Path, repository: list[str]
) -> None:
    argv = ["repo", "view", *repository, "--json", "name,owner"]
    scenario = _scenario(tmp_path, [_record(argv, [_response('{"name":"project"}')])])
    state = tmp_path / "state"

    result = _call(
        scenario, state, ["gh", "repo", "view", "--json=owner,name", *repository]
    )

    assert (result.returncode, result.stdout, result.stderr) == (
        0,
        '{"name":"project"}',
        "",
    )
    assert _log(state)[0]["response_index"] == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["repo", "view", "--repo", "example/project"],
        ["repo", "view", "-R", "example/project"],
        ["gh", "-R", "example/project", "repo", "view"],
    ],
)
def test_repo_view_rejects_repository_options(tmp_path: Path, argv: list[str]) -> None:
    scenario = _scenario(tmp_path, [_record(["repo", "view", "example/project"])])
    state = tmp_path / "state"

    result = _call(scenario, state, argv)

    _assert_rejected(result, "option is not supported for this read command")
    assert not state.exists()


def test_pr_list_short_head_matches_long_head_registration(tmp_path: Path) -> None:
    argv = ["pr", "list", "--repo", "example/project", "--head", "feature"]
    scenario = _scenario(tmp_path, [_record(argv, [_response('[{"number":41}]')])])
    state = tmp_path / "state"

    result = _call(
        scenario, state, ["gh", "-H", "feature", "pr", "list", "-R", "example/project"]
    )
    exhausted = _call(scenario, state, argv)

    assert (result.returncode, result.stdout, result.stderr) == (
        0,
        '[{"number":41}]',
        "",
    )
    _assert_rejected(exhausted, "response sequence exhausted at index 1")
    assert len(_log(state)) == 1


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        (["--header", "Accept: application/json"], "option is not supported"),
        (["-H", "feature", "--head", "feature"], "duplicate option: --head"),
    ],
)
def test_pr_list_rejects_headers_and_duplicate_head_filters(
    tmp_path: Path, options: list[str], reason: str
) -> None:
    scenario = _scenario(tmp_path, [_record(["pr", "list"])])
    state = tmp_path / "state"

    result = _call(scenario, state, ["pr", "list", *options])

    _assert_rejected(result, reason)
    assert not state.exists()


def test_api_short_header_preserves_registered_provider_error(tmp_path: Path) -> None:
    header = "Accept: application/vnd.github+json"
    scenario = _scenario(
        tmp_path,
        [_record([*_API, "--header", header], [_response("", "HTTP 403\n", 1)])],
    )
    state = tmp_path / "state"

    result = _call(scenario, state, ["api", "-H", header, "-X", "GET", _API[1]])
    missing_method = _call(scenario, state, ["api", _API[1], "-H", header])
    invalid_head = _call(scenario, state, [*_API, "--head", "feature"])

    assert (result.returncode, result.stdout, result.stderr) == (1, "", "HTTP 403\n")
    _assert_rejected(missing_method, "API reads require explicit --method GET")
    _assert_rejected(invalid_head, "option is not supported for this read command")
    assert len(_log(state)) == 1


def test_initial_and_freshness_observations_are_ordered_and_finite(
    tmp_path: Path,
) -> None:
    initial = '{"head":{"sha":"initial"},"state":"open"}'
    freshness = '{"head":{"sha":"later"},"state":"closed"}'
    scenario = _scenario(
        tmp_path, [_record(_API, [_response(initial), _response(freshness)])]
    )
    state = tmp_path / "state"

    first = _call(scenario, state, ["api", "-X", "GET", _API[1]])
    final = _call(scenario, state, _API)
    counters = (state / "counters.json").read_bytes()
    log = (state / "calls.jsonl").read_bytes()
    exhausted = _call(scenario, state, _API)

    assert (first.returncode, first.stdout, first.stderr) == (0, initial, "")
    assert (final.returncode, final.stdout, final.stderr) == (0, freshness, "")
    _assert_rejected(exhausted, "response sequence exhausted at index 2")
    assert [entry["response_index"] for entry in _log(state)] == [0, 1]
    assert (state / "counters.json").read_bytes() == counters
    assert (state / "calls.jsonl").read_bytes() == log


def test_paginated_reads_and_provider_errors_remain_distinct(tmp_path: Path) -> None:
    page_one = ["api", "--method", "GET", f"{_API[1]}/files?per_page=1&page=1"]
    page_two = ["api", f"{_API[1]}/files?per_page=1&page=2", "-X", "GET"]
    forbidden = ["api", f"{_API[1]}/stack", "--method", "GET"]
    missing = ["api", f"{_API[1]}/commits", "--method", "GET"]
    scenario = _scenario(
        tmp_path,
        [
            _record(page_one, [_response('[{"filename":"old.py"}]')]),
            _record(page_two, [_response("[]")]),
            _record(forbidden, [_response("", "HTTP 403: forbidden\n", 1)]),
            _record(missing, [_response('{"message":"Not Found"}', "HTTP 404\n", 4)]),
        ],
    )
    state = tmp_path / "state"

    observed = [
        _call(scenario, state, argv)
        for argv in (page_two, forbidden, page_one, missing)
    ]

    assert [(item.returncode, item.stdout, item.stderr) for item in observed] == [
        (0, "[]", ""),
        (1, "", "HTTP 403: forbidden\n"),
        (0, '[{"filename":"old.py"}]', ""),
        (4, '{"message":"Not Found"}', "HTTP 404\n"),
    ]
    assert [entry["response_index"] for entry in _log(state)] == [0, 0, 0, 0]


@pytest.mark.parametrize(
    "malicious",
    [
        ["pr", "merge", "41"],
        ["pr", "edit", "41", "--body", "changed"],
        ["pr", "create"],
        ["api", "repos/example/project/issues", "--method", "POST"],
        ["api", "repos/example/project/issues/1", "-X", "PATCH"],
        ["api", "repos/example/project/issues/1", "--method=DELETE"],
        ["api", "repos/example/project/pulls/41"],
        [
            "api",
            "repos/example/project/pulls/41",
            "--method",
            "GET",
            "--input",
            "secret",
        ],
        ["pr", "view", "41", "--web"],
        ["auth", "token"],
    ],
)
def test_mutations_fail_even_when_registered_after_a_valid_read(
    tmp_path: Path, malicious: list[str]
) -> None:
    scenario = _scenario(tmp_path, [_record(_VIEW), _record(malicious)])
    state = tmp_path / "state"

    result = _call(scenario, state, _VIEW)

    _assert_rejected(result, "provider_stub:")
    assert not state.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "view", "42"],
        ["pr", "merge", "41"],
        ["api", "repos/example/project/pulls/41"],
        ["pr", "view", "41", "--json"],
        ["pr", "view", "41", "--repo", "one", "-R", "two"],
        [*_VIEW[:-1], "number"],
        [*_VIEW[:-1], "number,headRefOid,title"],
        [],
    ],
)
def test_unknown_or_unsafe_requests_do_not_create_state(
    tmp_path: Path, argv: list[str]
) -> None:
    scenario = _scenario(tmp_path, [_record(_VIEW)])
    state = tmp_path / "state"
    result = _call(scenario, state, argv)
    _assert_rejected(result, "provider_stub:")
    assert not state.exists()


@pytest.mark.parametrize(
    "document",
    [
        None,
        [],
        {"version": True, "commands": []},
        {"version": 2, "commands": []},
        {"version": 1, "commands": []},
        {"version": 1, "commands": [_record(_VIEW)], "extra": 1},
        {"version": 1, "commands": [{"argv": ["pr", 41], "responses": [_response()]}]},
        {"version": 1, "commands": [_record(_VIEW, [])]},
        {"version": 1, "commands": [_record(_VIEW, [{"stdout": "missing fields"}])]},
        {"version": 1, "commands": [_record(_VIEW, [_response(exit_code=True)])]},
        {"version": 1, "commands": [_record(_VIEW, [_response(exit_code=-1)])]},
        {"version": 1, "commands": [_record(_VIEW, [_response(exit_code=256)])]},
        {
            "version": 1,
            "commands": [
                _record(_VIEW, [{"stdout": {}, "stderr": "", "exit_code": 0}])
            ],
        },
        {
            "version": 1,
            "commands": [_record(_VIEW, [_response(), _response("\ud800")])],
        },
        {"version": 1, "commands": [_record(_VIEW), _record(_VIEW)]},
        {
            "version": 1,
            "commands": [
                _record(_VIEW),
                _record(
                    [
                        "pr",
                        "view",
                        "41",
                        "-R",
                        "example/project",
                        "--json",
                        "headRefOid,number",
                    ]
                ),
            ],
        },
    ],
)
def test_malformed_scenarios_never_return_a_registered_success(
    tmp_path: Path, document: object
) -> None:
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps(document), encoding="utf-8")
    state = tmp_path / "state"
    result = _call(scenario, state, _VIEW)
    _assert_rejected(result, "provider_stub:")
    assert not state.exists()


@pytest.mark.parametrize(
    "text", ["{", '{"version":1,"version":1,"commands":[]}', "[" * 2000]
)
def test_invalid_json_fails_loudly(tmp_path: Path, text: str) -> None:
    scenario = tmp_path / "scenario.json"
    scenario.write_text(text, encoding="utf-8")
    result = _call(scenario, tmp_path / "state", _VIEW)
    _assert_rejected(result, "provider_stub:")
    assert not (tmp_path / "state").exists()


def test_scenario_and_state_errors_do_not_fall_back_to_success(tmp_path: Path) -> None:
    state = tmp_path / "state"
    absent = _call(tmp_path / "absent.json", state, _VIEW)
    _assert_rejected(absent, "provider_stub:")
    assert not state.exists()
    scenario = _scenario(tmp_path, [_record(_VIEW)])
    assert _call(scenario, state, _VIEW).returncode == 0
    (state / "counters.json").write_text("not JSON", encoding="utf-8")
    existing_log = (state / "calls.jsonl").read_bytes()

    corrupt = _call(scenario, state, _VIEW)

    _assert_rejected(corrupt, "invalid state JSON")
    assert (state / "calls.jsonl").read_bytes() == existing_log
    assert (state / "counters.json").read_text(encoding="utf-8") == "not JSON"


def test_state_isolated_between_runs_and_bound_to_scenario_bytes(
    tmp_path: Path,
) -> None:
    scenario = _scenario(
        tmp_path, [_record(_API, [_response("initial"), _response("fresh")])]
    )
    first_state, second_state = tmp_path / "first", tmp_path / "second"

    assert _call(scenario, first_state, _API).stdout == "initial"
    assert _call(scenario, first_state, _API).stdout == "fresh"
    assert _call(scenario, second_state, _API).stdout == "initial"
    before = (second_state / "counters.json").read_bytes()
    scenario.write_text(scenario.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    mismatch = _call(scenario, second_state, _API)

    _assert_rejected(mismatch, "different scenario bytes")
    assert (second_state / "counters.json").read_bytes() == before
    assert len(_log(first_state)) == 2
    assert len(_log(second_state)) == 1


def test_concurrent_consumers_reserve_unique_ordered_response_positions(
    tmp_path: Path,
) -> None:
    count = 12
    scenario = _scenario(
        tmp_path, [_record(_API, [_response(str(index)) for index in range(count)])]
    )
    state = tmp_path / "state"

    def consume(_: int) -> subprocess.CompletedProcess[str]:
        return _call(scenario, state, _API)

    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(consume, range(count)))

    assert all(result.returncode == 0 and result.stderr == "" for result in results)
    assert sorted(int(result.stdout) for result in results) == list(range(count))
    assert [entry["response_index"] for entry in _log(state)] == list(range(count))
    _assert_rejected(_call(scenario, state, _API), f"exhausted at index {count}")
    assert len(_log(state)) == count


def test_symlinked_state_directory_is_rejected(tmp_path: Path) -> None:
    scenario = _scenario(tmp_path, [_record(_VIEW)])
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    state = tmp_path / "state"
    state.symlink_to(target, target_is_directory=True)

    result = _call(scenario, state, _VIEW)

    _assert_rejected(result, "private owned directory")
    assert list(target.iterdir()) == []


def test_unregistered_read_does_not_consume_an_existing_sequence(
    tmp_path: Path,
) -> None:
    scenario = _scenario(
        tmp_path, [_record(_API, [_response("initial"), _response("fresh")])]
    )
    state = tmp_path / "state"
    assert _call(scenario, state, _API).stdout == "initial"
    counters = (state / "counters.json").read_bytes()
    log = (state / "calls.jsonl").read_bytes()

    rejected = _call(scenario, state, ["pr", "view", "999"])

    _assert_rejected(rejected, "unregistered read command")
    assert (state / "counters.json").read_bytes() == counters
    assert (state / "calls.jsonl").read_bytes() == log
    assert _call(scenario, state, _API).stdout == "fresh"


@pytest.mark.parametrize("missing", ["counters.json", "calls.jsonl"])
def test_missing_state_member_cannot_reset_or_hide_prior_observations(
    tmp_path: Path, missing: str
) -> None:
    scenario = _scenario(
        tmp_path, [_record(_API, [_response("initial"), _response("fresh")])]
    )
    state = tmp_path / "state"
    assert _call(scenario, state, _API).stdout == "initial"
    remaining = state / (
        "calls.jsonl" if missing == "counters.json" else "counters.json"
    )
    before = remaining.read_bytes()
    (state / missing).unlink()

    result = _call(scenario, state, _API)

    _assert_rejected(result, "incomplete state")
    assert not (state / missing).exists()
    assert remaining.read_bytes() == before


@pytest.mark.parametrize("filename", ["lock", "counters.json", "calls.jsonl"])
@pytest.mark.parametrize("kind", ["fifo", "hardlink", "symlink"])
def test_nonprivate_state_files_are_rejected_without_following_or_blocking(
    tmp_path: Path, filename: str, kind: str
) -> None:
    scenario = _scenario(
        tmp_path, [_record(_API, [_response("initial"), _response("fresh")])]
    )
    state = tmp_path / "state"
    assert _call(scenario, state, _API).stdout == "initial"
    state_file = state / filename
    original = state_file.read_bytes()
    target = tmp_path / "unrelated-private-file"
    target.write_bytes(original)
    target.chmod(0o600)
    state_file.unlink()
    if kind == "fifo":
        os.mkfifo(state_file, 0o600)
    elif kind == "hardlink":
        os.link(target, state_file)
    else:
        state_file.symlink_to(target)

    result = _call(scenario, state, _API)

    _assert_rejected(result, "provider_stub:")
    assert target.read_bytes() == original


@pytest.mark.parametrize("through_alias", [False, True])
def test_state_cannot_be_created_inside_source_working_directory(
    tmp_path: Path, through_alias: bool
) -> None:
    scenario = _scenario(tmp_path, [_record(_VIEW)])
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    parent = source
    if through_alias:
        parent = tmp_path / "source-alias"
        parent.symlink_to(source, target_is_directory=True)
    state = parent / "private" / "provider-state"

    result = _call(scenario, state, _VIEW, cwd=source)

    _assert_rejected(result, "outside the source working directory")
    assert list(source.iterdir()) == []
