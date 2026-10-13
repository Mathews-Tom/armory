"""Lifecycle receipt journal: schema, private storage, CAS saves, and the flock boundary."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from state_store import (
    TARGET_KEYS,
    ChangesetRecord,
    CreateRecord,
    GateRow,
    GraphJournal,
    GraphNode,
    GroupRecord,
    LockBusy,
    NativeMember,
    NativeRecord,
    NativeRequest,
    PublicationRecord,
    PushRecord,
    Receipt,
    ReceiptInputError,
    RefUpdate,
    StateError,
    Store,
    Target,
    validate_run_id,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="receipts require POSIX")

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
RUN = "0123456789abcdef0123456789abcdef"
OTHER_RUN = "fedcba9876543210fedcba9876543210"
OID = "1" * 40
OID2 = "2" * 40
DIGEST = "a" * 64
DIGEST2 = "b" * 64

Payload = dict[str, object]


@pytest.fixture(autouse=True)
def isolated_environment(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)
    home = tmp_path_factory.mktemp("home")
    config = home / "gitconfig"
    config.write_text("[gc]\nauto = 0\n[maintenance]\nauto = false\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Ship Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "ship@example.invalid")
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture
def common(tmp_path: Path) -> Path:
    path = tmp_path / "common"
    path.mkdir()
    path.chmod(0o700)
    return path


def make_receipt(run_id: str = RUN, **changes: object) -> Receipt:
    target = Target(
        host="github.com",
        repo="owner/repo",
        number=7,
        head_sha=OID,
        base_sha=OID2,
        head_ref="feature",
        head_repo="owner/repo",
        base_ref="main",
    )
    target_changes = {
        key: value for key, value in changes.items() if key in TARGET_KEYS
    }
    base = Receipt(
        run_id=run_id,
        endpoint="pr",
        code_identity=DIGEST,
        policy_identity=None,
        inventory_identity=DIGEST2,
        target=replace(target, **target_changes),
    )
    return replace(
        base, **{key: value for key, value in changes.items() if key not in TARGET_KEYS}
    )


def changeset_record(**changes: object) -> ChangesetRecord:
    group = GroupRecord(
        id="g1",
        parent=OID,
        tree=OID2,
        message_identity=DIGEST,
        commit=OID2,
        outcome="VALIDATED",
        gates=[GateRow("@secret-scan", DIGEST2, "PASSED", 0)],
    )
    record = ChangesetRecord(
        plan_identity=DIGEST,
        gates_identity=DIGEST2,
        source_snapshot=DIGEST,
        source_head=OID,
        source_branch="main",
        source_index=DIGEST2,
        base_ref="main",
        base_oid=OID,
        branch="feat/topic",
        mode="switch",
        groups=[group],
        update=RefUpdate(
            ref="refs/heads/feat/topic",
            old=None,
            new=OID2,
            index_before=DIGEST,
            index_after=DIGEST2,
            head_before="refs/heads/main",
            head_after="refs/heads/feat/topic",
            outcome="CONFIRMED",
        ),
        confirmed=[OID2],
        residual_snapshot=DIGEST,
        preserved=DIGEST,
    )
    return replace(record, **changes)


def unbound_receipt(run_id: str = RUN, **changes: object) -> Receipt:
    receipt = Receipt(
        run_id=run_id,
        endpoint="clean",
        code_identity=DIGEST,
        policy_identity=None,
        inventory_identity=DIGEST2,
        target=None,
        next_action="publish the confirmed commits",
        changeset=changeset_record(),
    )
    return replace(receipt, **changes)


def verification_row() -> dict[str, object]:
    return {
        "sha": OID,
        "command_index": 0,
        "command_identity": DIGEST,
        "returncode": 0,
        "outcome": "PASSED",
    }


def intent_row() -> dict[str, object]:
    return {
        "key": "merge:7",
        "kind": "merge",
        "resource": "pull/7",
        "expected_oid": OID,
        "outcome": "PENDING",
        "actual_oid": None,
        "created_at": "2026-01-01T00:00:00Z",
        "namespace": None,
        "required": True,
        "ref": None,
        "proof": None,
    }


def cleanup_row() -> dict[str, object]:
    return {
        "kind": "branch",
        "resource": "feature",
        "namespace": None,
        "expected_oid": OID,
        "actual_oid": None,
        "reason": "merged",
        "proof": "ancestor",
        "required": False,
        "ref": "refs/heads/feature",
    }


def full_receipt(run_id: str = RUN) -> Receipt:
    return make_receipt(
        run_id,
        endpoint="clean",
        status="COMPLETE",
        policy_identity=DIGEST,
        evidence_identity=DIGEST2,
        merge_sha=OID2,
        merge_verified=True,
        validation_sha=OID2,
        validation_policy=DIGEST,
        verification=[verification_row()],
        intents=[intent_row()],
        cleanup={"removed": [cleanup_row()], "retained": [], "failed": []},
        issue="needs a look",
        next_action="nothing",
    )


def payload(receipt: Receipt | None = None) -> Payload:
    return (receipt or full_receipt()).serialize()


def row(data: Payload, group: str) -> dict[str, object]:
    if group == "removed":
        cleanup = cast("dict[str, list[dict[str, object]]]", data["cleanup"])
        return cleanup["removed"][0]
    return cast("list[dict[str, object]]", data[group])[0]


def ship_dir(common_dir: Path) -> Path:
    directory = common_dir / "armory" / "ship"
    directory.mkdir(parents=True, exist_ok=True)
    for path in (common_dir / "armory", directory):
        path.chmod(0o700)
    return directory


def plant(common_dir: Path, run_id: str, content: bytes, mode: int = 0o600) -> Path:
    """Put raw bytes where the journal looks, without using the Store under test."""
    target = ship_dir(common_dir) / f"{run_id}.json"
    target.write_bytes(content)
    target.chmod(mode)
    return target


def plant_payload(common_dir: Path, run_id: str, data: Payload) -> Path:
    return plant(common_dir, run_id, json.dumps(data).encode())


def tree(root: Path) -> dict[str, tuple[int, int, int]]:
    state: dict[str, tuple[int, int, int]] = {}
    for path in [root, *root.rglob("*")]:
        info = path.lstat()
        state[str(path.relative_to(root))] = (
            info.st_mode,
            info.st_mtime_ns,
            info.st_size,
        )
    return state


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"git {args} failed: {result.stderr.decode(errors='replace')}"
        )
    return os.fsdecode(result.stdout).rstrip("\n")


# --- schema -------------------------------------------------------------------------------


def test_full_receipt_survives_a_save_and_a_fresh_load(common: Path) -> None:
    receipt = full_receipt()
    Store(common).save(receipt)

    assert Store(common).load(RUN) == receipt


def test_saved_journal_is_private_even_under_a_permissive_umask(common: Path) -> None:
    os.umask(0)
    Store(common).save(make_receipt())

    for directory in (common / "armory", common / "armory" / "ship"):
        assert stat.S_IMODE(directory.lstat().st_mode) == 0o700
    journal = common / "armory" / "ship" / f"{RUN}.json"
    assert stat.S_IMODE(journal.lstat().st_mode) == 0o600


def mutate(change: Callable[[Payload], None]) -> Callable[[Payload], None]:
    return change


def set_key(key: str, value: object) -> Callable[[Payload], None]:
    return mutate(lambda data: data.__setitem__(key, value))


def set_row(group: str, key: str, value: object) -> Callable[[Payload], None]:
    return mutate(lambda data: row(data, group).__setitem__(key, value))


def verification(outcome: str, returncode: object) -> Callable[[Payload], None]:
    def change(data: Payload) -> None:
        row(data, "verification").update({"outcome": outcome, "returncode": returncode})

    return change


def drop_key(key: str) -> Callable[[Payload], None]:
    def change(data: Payload) -> None:
        del data[key]

    return change


def extra_cleanup_disposition(data: Payload) -> None:
    cast("dict[str, object]", data["cleanup"])["lost"] = []


def missing_cleanup_field(data: Payload) -> None:
    del row(data, "removed")["proof"]


def extra_cleanup_field(data: Payload) -> None:
    row(data, "removed")["note"] = "x"


def extra_row_field(group: str) -> Callable[[Payload], None]:
    return mutate(lambda data: row(data, group).__setitem__("surprise", 1))


# Each entry corrupts a fully valid, completed receipt in exactly one way.
SCHEMA_REJECTS = [
    pytest.param(set_key("surprise", 1), id="unknown-top-level-key"),
    pytest.param(drop_key("issue"), id="missing-top-level-key"),
    pytest.param(set_key("schema_version", True), id="schema-version-bool"),
    pytest.param(set_key("schema_version", 1.0), id="schema-version-float"),
    pytest.param(set_key("schema_version", 4), id="schema-version-future"),
    pytest.param(set_key("publication", {}), id="publication-missing-fields"),
    pytest.param(set_key("number", None), id="partial-target"),
    pytest.param(set_key("changeset", {}), id="changeset-missing-fields"),
    pytest.param(set_key("number", True), id="number-bool"),
    pytest.param(set_key("number", 0), id="number-zero"),
    pytest.param(set_key("number", "7"), id="number-string"),
    pytest.param(set_key("merge_verified", 1), id="merge-verified-int"),
    pytest.param(set_key("status", "DONE"), id="unknown-status"),
    pytest.param(set_key("endpoint", "everything"), id="unknown-endpoint"),
    pytest.param(set_key("host", "GitHub.COM"), id="host-case"),
    pytest.param(set_key("repo", "owner"), id="repo-without-owner"),
    pytest.param(set_key("repo", "../owner/repo"), id="repo-traversal"),
    pytest.param(set_key("head_repo", "a/b/c"), id="head-repo-malformed"),
    pytest.param(set_key("head_sha", "abc123"), id="abbreviated-head-sha"),
    pytest.param(set_key("code_identity", DIGEST.upper()), id="uppercase-digest"),
    pytest.param(set_key("evidence_identity", "short"), id="short-evidence-digest"),
    pytest.param(set_key("next_action", ""), id="empty-next-action"),
    pytest.param(set_key("run_id", "../" + "a" * 29), id="traversal-run-id"),
    pytest.param(set_key("run_id", RUN.upper()), id="uppercase-run-id"),
    pytest.param(extra_row_field("verification"), id="verification-extra-field"),
    pytest.param(extra_row_field("intents"), id="intent-extra-field"),
    pytest.param(extra_cleanup_field, id="cleanup-extra-field"),
    pytest.param(missing_cleanup_field, id="cleanup-missing-field"),
    pytest.param(extra_cleanup_disposition, id="cleanup-extra-disposition"),
    pytest.param(
        set_row("verification", "command_index", True), id="command-index-bool"
    ),
    pytest.param(
        set_row("verification", "command_index", -1), id="command-index-negative"
    ),
    pytest.param(
        set_row("verification", "command_index", 1.0), id="command-index-float"
    ),
    pytest.param(verification("PASSED", True), id="passed-returncode-bool"),
    pytest.param(verification("PASSED", "0"), id="passed-returncode-string"),
    pytest.param(verification("PASSED", 1), id="passed-nonzero"),
    pytest.param(verification("PASSED", None), id="passed-without-exit"),
    pytest.param(verification("FAILED", 0), id="failed-zero"),
    pytest.param(verification("FAILED", None), id="failed-without-exit"),
    pytest.param(verification("TIMED_OUT", 0), id="timed-out-with-exit"),
    pytest.param(
        set_row("verification", "outcome", "OK"), id="unknown-verification-outcome"
    ),
    pytest.param(set_row("verification", "sha", "abc"), id="verification-short-sha"),
    pytest.param(set_row("intents", "required", 1), id="intent-required-int"),
    pytest.param(set_row("intents", "kind", "force_push"), id="unknown-intent-kind"),
    pytest.param(set_row("intents", "outcome", "DONE"), id="unknown-intent-outcome"),
    pytest.param(set_row("intents", "expected_oid", "abc"), id="intent-short-oid"),
    pytest.param(set_row("removed", "required", 0), id="cleanup-required-int"),
    pytest.param(set_row("removed", "reason", ""), id="cleanup-empty-reason"),
    # Merge and validation markers must agree with each other and the endpoint.
    pytest.param(set_key("merge_sha", None), id="verified-merge-without-landing"),
    pytest.param(
        set_key("merge_verified", False), id="validation-without-verified-merge"
    ),
    pytest.param(set_key("policy_identity", None), id="validation-without-policy"),
    pytest.param(
        set_key("validation_policy", DIGEST2), id="validation-for-another-policy"
    ),
    pytest.param(
        mutate(
            lambda data: data.update(
                status="COMPLETE", validation_sha=None, validation_policy=None
            )
        ),
        id="complete-landing-without-acceptance",
    ),
    pytest.param(
        mutate(
            lambda data: data.update(
                status="COMPLETE",
                merge_verified=False,
                merge_sha=None,
                validation_sha=None,
                validation_policy=None,
            )
        ),
        id="complete-landing-never-verified",
    ),
]


@pytest.mark.parametrize("change", SCHEMA_REJECTS)
def test_parse_rejects_each_corrupted_receipt(
    change: Callable[[Payload], None],
) -> None:
    Receipt.parse(payload())
    data = payload()
    change(data)

    with pytest.raises(ReceiptInputError):
        Receipt.parse(data)


@pytest.mark.parametrize("change", SCHEMA_REJECTS)
def test_a_corrupted_journal_at_rest_is_never_loaded(
    common: Path, change: Callable[[Payload], None]
) -> None:
    data = payload()
    change(data)
    plant_payload(common, RUN, data)

    with pytest.raises(ReceiptInputError):
        Store(common).load(RUN)
    with pytest.raises(ReceiptInputError):
        Store(common).list_runs()


@pytest.mark.parametrize(
    "receipt",
    [
        pytest.param(make_receipt(), id="fresh-pr-run"),
        pytest.param(make_receipt(status="COMPLETE"), id="complete-pr-without-landing"),
        pytest.param(make_receipt(head_repo=""), id="empty-head-repo"),
        pytest.param(
            make_receipt(endpoint="merged", merge_sha=OID2, merge_verified=True),
            id="verified-landing-before-validation",
        ),
        pytest.param(
            make_receipt(endpoint="merged", merge_sha=OID2, merge_verified=False),
            id="unverified-landing-candidate",
        ),
        pytest.param(
            make_receipt(
                endpoint="merged",
                status="COMPLETE",
                policy_identity=DIGEST,
                merge_sha=OID2,
                merge_verified=True,
                validation_sha=OID2,
                validation_policy=DIGEST,
            ),
            id="complete-merged-with-acceptance",
        ),
        pytest.param(
            make_receipt(
                verification=[
                    {**verification_row(), "outcome": "FAILED", "returncode": 3},
                    {**verification_row(), "outcome": "TIMED_OUT", "returncode": None},
                ]
            ),
            id="failed-and-timed-out-verifications",
        ),
    ],
)
def test_consistent_receipts_are_accepted(receipt: Receipt, common: Path) -> None:
    store = Store(common)
    store.save(receipt)

    assert Store(common).load(RUN) == receipt


def legacy_payload(receipt: Receipt) -> Payload:
    """The exact flat v1 journal M1 wrote for ``receipt``."""
    data = receipt.serialize()
    del data["changeset"]
    del data["publication"]
    data["schema_version"] = 1
    return data


def changeset_payload(receipt: Receipt) -> Payload:
    """The exact schema 2 journal written before publication was journaled."""
    data = receipt.serialize()
    del data["publication"]
    data["schema_version"] = 2
    return data


def publication_record(**changes: object) -> PublicationRecord:
    record = PublicationRecord(
        host="github.com",
        base_repo="owner/repo",
        base_ref="main",
        base_oid=OID,
        head_repo="contrib/repo",
        head_ref="feat/topic",
        remote="fork",
        head=OID2,
        validated_head=OID2,
        push=PushRecord(None, OID2, "CONFIRMED"),
        create=CreateRecord(
            DIGEST, DIGEST2, "2026-10-12T00:00:00+00:00", "CONFIRMED", 7
        ),
    )
    return replace(record, **changes)


@pytest.mark.parametrize(
    "receipt",
    [
        pytest.param(full_receipt(), id="completed-clean"),
        pytest.param(
            make_receipt(
                endpoint="merged",
                policy_identity=DIGEST,
                intents=[intent_row()],
                issue="merge outcome unknown",
                next_action="reconcile the original merge",
            ),
            id="pending-merge-uncertainty",
        ),
        pytest.param(make_receipt(head_repo=""), id="deleted-fork-head"),
    ],
)
def test_v1_journal_migrates_exactly_and_saves_as_current_schema(
    common: Path, receipt: Receipt
) -> None:
    v1 = legacy_payload(receipt)
    plant_payload(common, RUN, v1)

    loaded = Store(common).load(RUN)

    assert loaded == receipt
    assert loaded.changeset is None and loaded.target == receipt.target
    store = Store(common)
    store.save(store.load(RUN))
    saved = json.loads((common / "armory" / "ship" / f"{RUN}.json").read_bytes())
    assert saved == {**v1, "schema_version": 3, "changeset": None, "publication": None}


def test_schema_2_changeset_journal_migrates_exactly(common: Path) -> None:
    receipt = unbound_receipt()
    plant_payload(common, RUN, changeset_payload(receipt))

    assert Store(common).load(RUN) == receipt
    with_publication = {**changeset_payload(receipt), "publication": None}
    with pytest.raises(ReceiptInputError):
        Receipt.parse(with_publication)


@pytest.mark.parametrize(
    "receipt",
    [
        pytest.param(
            unbound_receipt(
                changeset=None, publication=publication_record(create=None)
            ),
            id="pushed-before-pr-creation",
        ),
        pytest.param(
            make_receipt(publication=publication_record()), id="bound-to-created-pr"
        ),
        pytest.param(
            unbound_receipt(
                publication=publication_record(
                    create=CreateRecord(DIGEST, DIGEST2, "2026-10-12T00:00:00+00:00")
                )
            ),
            id="pending-creation",
        ),
    ],
)
def test_publication_journals_round_trip(common: Path, receipt: Receipt) -> None:
    Store(common).save(receipt)

    assert Store(common).load(RUN) == receipt


@pytest.mark.parametrize(
    "receipt",
    [
        pytest.param(
            unbound_receipt(publication=publication_record(push=PushRecord(None, OID))),
            id="push-of-another-head",
        ),
        pytest.param(
            unbound_receipt(
                publication=publication_record(
                    create=CreateRecord(DIGEST, DIGEST2, "now", "CONFIRMED", None)
                )
            ),
            id="confirmed-creation-without-pr",
        ),
        pytest.param(
            unbound_receipt(
                publication=publication_record(
                    create=CreateRecord(DIGEST, DIGEST2, "now", "PENDING", 7)
                )
            ),
            id="pending-creation-with-pr",
        ),
        pytest.param(
            make_receipt(number=8, publication=publication_record()),
            id="bound-to-a-different-pr-than-created",
        ),
        pytest.param(
            unbound_receipt(publication=publication_record(head_repo="a/b/c")),
            id="malformed-head-namespace",
        ),
        pytest.param(
            unbound_receipt(
                publication=publication_record(decision_identity="not-a-digest")
            ),
            id="malformed-decision-authority",
        ),
    ],
)
def test_inconsistent_publication_journals_are_refused(
    common: Path, receipt: Receipt
) -> None:
    with pytest.raises(ReceiptInputError):
        Store(common).save(receipt)

    assert list(common.iterdir()) == []


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(set_key("changeset", None), id="v1-with-v2-key"),
        pytest.param(set_key("number", None), id="v1-without-pr-number"),
        pytest.param(set_key("head_sha", None), id="v1-without-head"),
    ],
)
def test_v1_journal_is_not_reinterpreted_or_defaulted(
    change: Callable[[Payload], None],
) -> None:
    data = legacy_payload(full_receipt())
    change(data)

    with pytest.raises(ReceiptInputError):
        Receipt.parse(data)


def test_pre_publication_run_keeps_only_typed_changeset_state(common: Path) -> None:
    receipt = unbound_receipt()
    Store(common).save(receipt)

    loaded = Store(common).load(RUN)

    assert loaded == receipt and loaded.target is None
    data = payload(receipt)
    assert all(data[key] is None for key in TARGET_KEYS)
    with pytest.raises(StateError):
        _ = loaded.number


@pytest.mark.parametrize(
    "receipt",
    [
        pytest.param(unbound_receipt(status="COMPLETE"), id="complete-without-pr"),
        pytest.param(unbound_receipt(merge_sha=OID), id="landing-without-pr"),
        pytest.param(
            unbound_receipt(intents=[intent_row()]), id="merge-intent-without-pr"
        ),
        pytest.param(unbound_receipt(changeset=None), id="no-target-no-changeset"),
        pytest.param(
            unbound_receipt(changeset=changeset_record(residual_snapshot=None)),
            id="confirmed-update-without-residual",
        ),
        pytest.param(
            unbound_receipt(
                changeset=changeset_record(
                    update=None,
                    preserved=None,
                    residual_snapshot=DIGEST,
                    confirmed=[],
                )
            ),
            id="residual-without-update",
        ),
        pytest.param(
            unbound_receipt(
                changeset=changeset_record(
                    groups=[GroupRecord("g1", OID, OID2, DIGEST, None, "VALIDATED", [])]
                )
            ),
            id="validated-without-commit-or-gates",
        ),
        pytest.param(
            unbound_receipt(
                changeset=changeset_record(
                    groups=[
                        GroupRecord(
                            "g1",
                            OID,
                            OID2,
                            DIGEST,
                            OID,
                            "VALIDATED",
                            [GateRow("unit", DIGEST, "PASSED", 0)],
                        )
                    ]
                )
            ),
            id="update-not-the-validated-chain",
        ),
        pytest.param(
            unbound_receipt(
                changeset=changeset_record(
                    groups=[
                        GroupRecord(
                            "g1",
                            OID,
                            OID2,
                            DIGEST,
                            OID2,
                            "VALIDATED",
                            [GateRow("unit", DIGEST, "PASSED", 3)],
                        )
                    ]
                )
            ),
            id="passed-gate-with-nonzero-exit",
        ),
        pytest.param(
            unbound_receipt(changeset=changeset_record(mode="rebase")),
            id="unsupported-placement-mode",
        ),
        pytest.param(
            unbound_receipt(
                changeset=changeset_record(
                    update=None, residual_snapshot=None, confirmed=[]
                )
            ),
            id="preserved-work-identity-without-update",
        ),
        pytest.param(
            unbound_receipt(changeset=changeset_record(preserved="not-a-digest")),
            id="preserved-work-identity-not-a-digest",
        ),
    ],
)
def test_inconsistent_changeset_journals_are_refused(
    common: Path, receipt: Receipt
) -> None:
    with pytest.raises(ReceiptInputError):
        Store(common).save(receipt)

    assert list(common.iterdir()) == []


@pytest.mark.parametrize(
    "stage",
    ["before-update", "pending-update", "confirmed-update", "unknown-baseline"],
)
def test_preserved_work_identity_round_trips_with_its_update(
    common: Path, stage: str
) -> None:
    record = changeset_record()
    if stage == "before-update":
        record = replace(
            record, update=None, preserved=None, residual_snapshot=None, confirmed=[]
        )
    elif stage == "pending-update":
        assert record.update is not None
        record = replace(
            record,
            update=replace(record.update, outcome="PENDING"),
            residual_snapshot=None,
            confirmed=[],
        )
    elif stage == "unknown-baseline":
        record = replace(record, preserved=None)  # an update with no known baseline
    receipt = unbound_receipt(changeset=record)

    Store(common).save(receipt)

    loaded = Store(common).load(RUN)
    assert loaded == receipt
    assert loaded.changeset is not None
    assert loaded.changeset.preserved == record.preserved
    saved = cast("dict[str, object]", payload(receipt)["changeset"])
    assert saved["preserved"] == record.preserved


def test_historical_update_without_a_preserved_identity_loads_as_unknown(
    common: Path,
) -> None:
    data = payload(unbound_receipt(changeset=changeset_record()))
    cast("dict[str, object]", data["changeset"]).pop("preserved")
    path = plant_payload(common, RUN, data)
    at_rest = path.read_bytes()

    loaded = Store(common).load(RUN)

    assert loaded.changeset is not None and loaded.changeset.update is not None
    assert loaded.changeset.preserved is None  # unknown: never fabricated
    assert path.read_bytes() == at_rest  # and never rewritten by loading
    assert Receipt.parse(data) == loaded


@pytest.mark.parametrize(
    "run_id",
    [
        "",
        "../" + "a" * 29,
        "a" * 31,
        "a" * 33,
        RUN.upper(),
        RUN + "\n",
        "g" * 32,
        "\u0661" * 32,
        "a/" + "b" * 30,
    ],
)
def test_unsafe_run_ids_never_reach_the_filesystem(common: Path, run_id: str) -> None:
    with pytest.raises(ReceiptInputError):
        validate_run_id(run_id)
    with pytest.raises(ReceiptInputError):
        Store(common).load(run_id)
    with pytest.raises(ReceiptInputError):
        Store(common).save(make_receipt(run_id))

    assert list(common.iterdir()) == []


def test_receipt_content_must_agree_with_its_filename(common: Path) -> None:
    plant_payload(common, OTHER_RUN, payload(make_receipt(RUN)))

    with pytest.raises(ReceiptInputError):
        Store(common).load(OTHER_RUN)
    with pytest.raises(ReceiptInputError):
        Store(common).list_runs()


def test_invalid_receipt_is_refused_before_anything_is_created(common: Path) -> None:
    for broken in (
        make_receipt(number=0),
        make_receipt(status="DONE"),
        make_receipt(merge_verified=True),
    ):
        with pytest.raises(ReceiptInputError):
            Store(common).save(broken)

    assert list(common.iterdir()) == []


@pytest.mark.parametrize(
    "content",
    [b"", b"{", b"[]", b"null", b'"text"', b'{"schema_version": 1}', b"\xff\xfe"],
)
def test_unparseable_journals_are_rejected(common: Path, content: bytes) -> None:
    plant(common, RUN, content)

    with pytest.raises(ReceiptInputError):
        Store(common).load(RUN)


def test_oversized_journal_is_rejected(common: Path) -> None:
    plant(common, RUN, b" " * (2 * 1024 * 1024 + 1))

    with pytest.raises(ReceiptInputError):
        Store(common).load(RUN)


def test_list_runs_is_sorted_and_ignores_foreign_files(common: Path) -> None:
    store = Store(common)
    store.save(make_receipt(OTHER_RUN))
    store.save(make_receipt(RUN))
    with store.mutation_lock():
        pass
    (common / "armory" / "ship" / f".{RUN}.stray").write_bytes(b"not a receipt")

    assert [receipt.run_id for receipt in Store(common).list_runs()] == [RUN, OTHER_RUN]


def test_excluded_run_is_never_read_so_its_save_baseline_holds(common: Path) -> None:
    controller = Store(common)
    controller.save(make_receipt(OTHER_RUN))
    controller.save(make_receipt(RUN))
    held = controller.load(RUN)  # the controller's in-memory view of its own run
    other = Store(common)
    newer = other.load(RUN)
    newer.next_action = "another controller's journaled intent"
    other.save(newer)
    path = common / "armory" / "ship" / f"{RUN}.json"
    newer_bytes = path.read_bytes()

    others = controller.list_runs(exclude=RUN)

    assert [receipt.run_id for receipt in others] == [OTHER_RUN]
    held.next_action = "overwrite from a stale view"
    with pytest.raises(StateError):
        controller.save(held)  # enumeration must not have adopted the newer bytes
    assert path.read_bytes() == newer_bytes
    reloaded = Store(common).load(RUN)
    assert reloaded.next_action == "another controller's journaled intent"


def test_exclusion_skips_even_an_unreadable_own_journal(common: Path) -> None:
    Store(common).save(make_receipt(OTHER_RUN))
    plant(common, RUN, b"{")

    with pytest.raises(ReceiptInputError):
        Store(common).list_runs()

    remaining = Store(common).list_runs(exclude=RUN)
    assert [receipt.run_id for receipt in remaining] == [OTHER_RUN]


def test_exclusion_must_name_a_valid_run_id(common: Path) -> None:
    Store(common).save(make_receipt())

    with pytest.raises(ReceiptInputError):
        Store(common).list_runs(exclude="../" + RUN)
    everything = Store(common).list_runs(exclude=None)
    assert [receipt.run_id for receipt in everything] == [RUN]


def test_store_requires_an_existing_common_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Store(tmp_path / "missing")


# --- private storage ----------------------------------------------------------------------


def test_missing_journal_reads_do_not_create_directories(common: Path) -> None:
    store = Store(common)

    assert store.list_runs() == ()
    with pytest.raises(FileNotFoundError):
        store.load(RUN)
    assert list(common.iterdir()) == []

    (common / "armory").mkdir(mode=0o700)
    assert store.list_runs() == ()
    with pytest.raises(FileNotFoundError):
        store.load(RUN)
    assert list((common / "armory").iterdir()) == []


def test_reads_leave_an_existing_journal_untouched(common: Path) -> None:
    store = Store(common)
    store.save(make_receipt())
    store.save(full_receipt(OTHER_RUN))
    before = tree(common)

    store.load(RUN)
    store.list_runs()
    Store(common).list_runs()

    assert tree(common) == before


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666])
def test_journal_readable_by_others_is_rejected_and_not_replaced(
    common: Path, mode: int
) -> None:
    target = plant_payload(common, RUN, payload(make_receipt()))
    target.chmod(mode)
    before = target.read_bytes()

    with pytest.raises(StateError):
        Store(common).load(RUN)
    with pytest.raises(StateError):
        Store(common).list_runs()
    with pytest.raises(StateError):
        Store(common).save(make_receipt(next_action="overwrite"))
    assert target.read_bytes() == before


def test_hardlinked_journal_is_rejected(common: Path, tmp_path: Path) -> None:
    target = plant_payload(common, RUN, payload(make_receipt()))
    os.link(target, tmp_path / "alias.json")

    with pytest.raises(StateError):
        Store(common).load(RUN)


@pytest.mark.parametrize("dangling", [False, True])
def test_symlinked_journal_is_never_followed(
    common: Path, tmp_path: Path, dangling: bool
) -> None:
    victim = tmp_path / "victim.json"
    if not dangling:
        victim.write_bytes(json.dumps(payload(make_receipt())).encode())
        victim.chmod(0o600)
    directory = common / "armory" / "ship"
    ship_dir(common)
    (directory / f"{RUN}.json").symlink_to(victim)
    before = victim.read_bytes() if not dangling else None

    with pytest.raises((StateError, OSError)):
        Store(common).load(RUN)
    with pytest.raises((StateError, OSError)):
        Store(common).save(make_receipt(next_action="through the link"))
    assert (directory / f"{RUN}.json").is_symlink()
    if dangling:
        assert not victim.exists()
    else:
        assert victim.read_bytes() == before


@pytest.mark.parametrize("name", ["armory", "ship"])
@pytest.mark.parametrize("mode", [0o775, 0o757, 0o777])
def test_journal_directory_writable_by_others_is_rejected(
    common: Path, name: str, mode: int
) -> None:
    Store(common).save(make_receipt())
    target = common / "armory" if name == "armory" else common / "armory" / "ship"
    target.chmod(mode)
    before = sorted(path.name for path in (common / "armory" / "ship").iterdir())

    for operation in (
        lambda: Store(common).load(RUN),
        lambda: Store(common).list_runs(),
        lambda: Store(common).save(make_receipt(next_action="again")),
    ):
        with pytest.raises(StateError):
            operation()
    with pytest.raises(StateError), Store(common).mutation_lock():
        pytest.fail("lock must not be granted in an unsafe directory")
    assert (
        sorted(path.name for path in (common / "armory" / "ship").iterdir()) == before
    )


def test_symlinked_journal_directory_is_rejected(common: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (elsewhere / f"{RUN}.json").write_bytes(
        json.dumps(payload(make_receipt())).encode()
    )
    (elsewhere / f"{RUN}.json").chmod(0o600)
    (common / "armory").mkdir(mode=0o700)
    (common / "armory" / "ship").symlink_to(elsewhere)
    before = tree(elsewhere)

    with pytest.raises(StateError):
        Store(common).load(RUN)
    with pytest.raises(StateError):
        Store(common).list_runs()
    with pytest.raises(StateError):
        Store(common).save(make_receipt(OTHER_RUN))
    assert tree(elsewhere) == before


def test_unsafe_common_directory_is_rejected(common: Path) -> None:
    common.chmod(0o777)

    with pytest.raises(StateError):
        Store(common).list_runs()
    with pytest.raises(StateError):
        Store(common).save(make_receipt())
    assert list(common.iterdir()) == []


# --- compare-and-swap saves ---------------------------------------------------------------


def test_stale_writer_cannot_overwrite_a_newer_receipt(common: Path) -> None:
    first = Store(common)
    second = Store(common)
    first.save(make_receipt())
    stale = second.load(RUN)
    current = first.load(RUN)

    current.next_action = "newer decision"
    current.status = "BLOCKED"
    first.save(current)
    newer_bytes = (common / "armory" / "ship" / f"{RUN}.json").read_bytes()

    stale.next_action = "stale decision"
    with pytest.raises(StateError):
        second.save(stale)

    assert (common / "armory" / "ship" / f"{RUN}.json").read_bytes() == newer_bytes
    reloaded = Store(common).load(RUN)
    assert (reloaded.next_action, reloaded.status) == ("newer decision", "BLOCKED")
    names = {path.name for path in (common / "armory" / "ship").iterdir()}
    assert names == {f"{RUN}.json"}


def test_stale_writer_recovers_by_reloading(common: Path) -> None:
    first = Store(common)
    second = Store(common)
    first.save(make_receipt())
    stale = second.load(RUN)
    winner = first.load(RUN)
    winner.next_action = "winner"
    first.save(winner)
    stale.issue = "from stale view"
    with pytest.raises(StateError):
        second.save(stale)

    fresh = second.load(RUN)
    fresh.issue = "merged view"
    second.save(fresh)

    final = Store(common).load(RUN)
    assert (final.next_action, final.issue) == ("winner", "merged view")


def test_blind_create_cannot_overwrite_an_existing_journal(common: Path) -> None:
    Store(common).save(make_receipt(next_action="original"))
    blind = Store(common)

    with pytest.raises(StateError):
        blind.save(make_receipt(next_action="blind"))

    assert Store(common).load(RUN).next_action == "original"


def test_create_race_after_missing_read_is_detected(common: Path) -> None:
    loser = Store(common)
    with pytest.raises(FileNotFoundError):
        loser.load(RUN)
    Store(common).save(make_receipt(next_action="winner"))

    with pytest.raises(StateError):
        loser.save(make_receipt(next_action="loser"))

    assert Store(common).load(RUN).next_action == "winner"


def test_deleted_journal_is_not_silently_recreated(common: Path) -> None:
    store = Store(common)
    receipt = make_receipt()
    store.save(receipt)
    (common / "armory" / "ship" / f"{RUN}.json").unlink()

    with pytest.raises(StateError):
        store.save(receipt)

    assert not (common / "armory" / "ship" / f"{RUN}.json").exists()


def test_one_store_can_save_repeatedly_and_runs_are_independent(common: Path) -> None:
    store = Store(common)
    receipt = make_receipt()
    store.save(receipt)
    receipt.next_action = "second"
    store.save(receipt)
    receipt.next_action = "third"
    store.save(receipt)
    store.save(make_receipt(OTHER_RUN))

    assert Store(common).load(RUN).next_action == "third"
    assert Store(common).load(OTHER_RUN).run_id == OTHER_RUN


def test_saved_bytes_are_canonical_json_with_trailing_newline(common: Path) -> None:
    Store(common).save(full_receipt())
    data = (common / "armory" / "ship" / f"{RUN}.json").read_bytes()

    assert data.endswith(b"\n")
    assert json.loads(data) == payload(full_receipt())
    assert data.count(b"\n") == 1


# --- mutation lock ------------------------------------------------------------------------

HOLDER = """
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from state_store import Store

with Store(Path(sys.argv[2])).mutation_lock():
    print("held", flush=True)
    sys.stdin.read()
"""


def start_holder(common_dir: Path) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(SCRIPTS), str(common_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    if process.stdout.readline().strip() != "held":
        process.kill()
        _, error = process.communicate()
        raise AssertionError(f"lock holder did not acquire the lock: {error}")
    return process


def test_lock_is_exclusive_across_processes_and_released_on_exit(common: Path) -> None:
    holder = start_holder(common)
    try:
        for _ in range(2):
            with pytest.raises(LockBusy), Store(common).mutation_lock():
                pytest.fail("a second controller must not enter the boundary")
        lock = common / "armory" / "ship" / "mutation.lock"
        assert lock.stat().st_size == 0
    finally:
        _, error = holder.communicate(timeout=30)
    assert holder.returncode == 0, error

    entered = False
    with Store(common).mutation_lock():
        entered = True
    assert entered


def test_lock_is_released_when_its_owner_is_killed(common: Path) -> None:
    holder = start_holder(common)
    try:
        with pytest.raises(LockBusy), Store(common).mutation_lock():
            pytest.fail("held lock was granted")
    finally:
        holder.send_signal(signal.SIGKILL)
        holder.communicate(timeout=30)

    entered = False
    with Store(common).mutation_lock():
        entered = True
    assert entered
    assert (common / "armory" / "ship" / "mutation.lock").stat().st_size == 0


def test_lock_is_exclusive_between_store_instances_and_survives_body_failure(
    common: Path,
) -> None:
    outer = Store(common)
    with outer.mutation_lock():
        with pytest.raises(LockBusy), Store(common).mutation_lock():
            pytest.fail("second instance entered a held lock")
        with pytest.raises(LockBusy), outer.mutation_lock():
            pytest.fail("the lock is not reentrant")

    with pytest.raises(RuntimeError), outer.mutation_lock():
        raise RuntimeError("body failed")
    with Store(common).mutation_lock():
        pass


def test_lock_does_not_block_read_only_resumption_facts(common: Path) -> None:
    store = Store(common)
    store.save(make_receipt())
    holder = start_holder(common)
    try:
        before = tree(common)
        reader = Store(common)
        assert reader.load(RUN).run_id == RUN
        assert [record.run_id for record in reader.list_runs()] == [RUN]
        assert tree(common) == before
    finally:
        holder.communicate(timeout=30)


def test_lock_file_with_foreign_content_is_never_cleared(common: Path) -> None:
    lock = ship_dir(common) / "mutation.lock"
    lock.write_bytes(b"owned by someone else")
    lock.chmod(0o600)

    with pytest.raises(StateError), Store(common).mutation_lock():
        pytest.fail("unfamiliar lock granted")
    assert lock.read_bytes() == b"owned by someone else"


def test_lock_file_readable_by_others_is_rejected(common: Path) -> None:
    lock = ship_dir(common) / "mutation.lock"
    lock.write_bytes(b"")
    lock.chmod(0o644)

    with pytest.raises(StateError), Store(common).mutation_lock():
        pytest.fail("lock with unsafe permissions granted")


def test_symlinked_lock_file_is_never_followed(common: Path, tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_bytes(b"precious")
    victim.chmod(0o600)
    lock = ship_dir(common) / "mutation.lock"
    lock.symlink_to(victim)

    with pytest.raises((StateError, OSError)), Store(common).mutation_lock():
        pytest.fail("symlinked lock granted")
    assert victim.read_bytes() == b"precious"


# --- linked worktrees ---------------------------------------------------------------------


def common_dir_of(checkout: Path) -> Path:
    return Path(
        git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )


def test_linked_worktrees_share_one_journal_and_one_lock(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "tracked.txt").write_text("one\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "-b", "feature", str(linked))

    main_common = common_dir_of(repo)
    linked_common = common_dir_of(linked)
    assert main_common.resolve() == linked_common.resolve() == (repo / ".git").resolve()

    from_main = Store(main_common)
    from_linked = Store(linked_common)
    from_main.save(make_receipt())
    from_main.save(make_receipt(OTHER_RUN))

    seen = from_linked.load(RUN)
    assert seen == make_receipt()
    assert [receipt.run_id for receipt in from_linked.list_runs()] == [RUN, OTHER_RUN]

    seen.next_action = "continued from the linked worktree"
    from_linked.save(seen)
    assert from_main.load(RUN).next_action == "continued from the linked worktree"

    with (
        from_main.mutation_lock(),
        pytest.raises(LockBusy),
        from_linked.mutation_lock(),
    ):
        pytest.fail("worktrees of one repository must share the mutation boundary")

    assert (repo / ".git" / "armory" / "ship" / f"{RUN}.json").is_file()
    assert not list((repo / ".git" / "worktrees").rglob("armory"))
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == ""
    assert git(linked, "status", "--porcelain", "--untracked-files=all") == ""


def test_separate_clones_do_not_share_journals(tmp_path: Path) -> None:
    for name in ("one", "two"):
        path = tmp_path / name
        path.mkdir()
        git(path, "init", "-q", "-b", "main")
    Store(common_dir_of(tmp_path / "one")).save(make_receipt())

    assert Store(common_dir_of(tmp_path / "two")).list_runs() == ()
    with pytest.raises(FileNotFoundError):
        Store(common_dir_of(tmp_path / "two")).load(RUN)
    assert not (tmp_path / "two" / ".git" / "armory").exists()


# -- native stack records of graph journals ---------------------------------------

NOW = "2026-10-13T12:00:00+00:00"
UUID = "6aa849f9-5647-4c96-a58d-8019d8830a2c"
STACK_BASE = "b" * 40


def head_of(pr: int) -> str:
    return f"{pr:040x}"


def native_member(pr: int, position: int, base_ref: str, base: str) -> NativeMember:
    return NativeMember(
        pr=pr,
        position=position,
        head_ref=f"stack/layer{position}",
        head_sha=head_of(pr),
        base_ref=base_ref,
        base_sha=base,
        tree=f"{pr + 100:040x}",
        slice_base=base,
        slice_identity=f"{pr:064x}",
    )


def native_journal() -> GraphJournal:
    """Stack 7 on main: PRs 4 and 5 are the queued scope, 6 is retained above."""
    lower = native_member(4, 1, "main", STACK_BASE)
    selected = native_member(5, 2, lower.head_ref, lower.head_sha)
    retained = replace(
        native_member(6, 3, selected.head_ref, selected.head_sha),
        fork=selected.head_sha,
    )
    nodes = [
        GraphNode(4, None, True, "owner/repo", "stack/layer1", head_of(4), "main",
                  DIGEST),
        GraphNode(5, 4, True, "owner/repo", "stack/layer2", head_of(5),
                  "stack/layer1", DIGEST),
        GraphNode(6, 5, False, "owner/repo", "stack/layer3", head_of(6),
                  "stack/layer2", None, state="RETAINED"),
    ]  # fmt: skip
    return GraphJournal(
        run_id=RUN,
        host="github.com",
        repo="owner/repo",
        trunk="main",
        endpoint="clean",
        plan_identity=DIGEST,
        topology=DIGEST2,
        plan={},
        code_identity=DIGEST,
        nodes=nodes,
        created_at=NOW,
        updated_at=NOW,
        native=NativeRecord(
            stack=7,
            base_ref="main",
            base_sha=STACK_BASE,
            size=3,
            selected=5,
            scope=[4, 5],
            retained=[6],
            members=[lower, selected, retained],
            request=NativeRequest("merge_queue", None, head_of(5)),
        ),
    )


def accepted(journal: GraphJournal) -> GraphJournal:
    """The queue accepted the request; both scope members landed and were proved."""
    native = journal.native
    assert native is not None
    native.request = replace(
        native.request,
        state="ACCEPTED",
        dispatched_at=NOW,
        uuid=UUID,
        status="enqueued",
        message="Merge request enqueued.",
        echo_action="merge_queue",
        echo_method="default",
        echo_head=head_of(5),
    )
    for member in native.members[:2]:
        member.landing = f"{member.pr + 200:040x}"
        member.landed_tree = f"{member.pr + 300:040x}"
        member.verified = True
    return journal


def completed(journal: GraphJournal) -> GraphJournal:
    for node, run_id in zip(journal.nodes[:2], (OTHER_RUN, "c" * 32), strict=True):
        node.state, node.run_id = "LANDED", run_id
    journal.status = "COMPLETE"
    return journal


@pytest.mark.parametrize(
    "build", [native_journal, lambda: accepted(native_journal()),
              lambda: completed(accepted(native_journal()))],
)  # fmt: skip
def test_native_graph_journal_round_trips_through_the_store(
    common: Path, build: Callable[[], GraphJournal]
) -> None:
    journal = build()

    Store(common).save_graph(journal)
    loaded = Store(common).load_graph(RUN)

    assert loaded == journal
    assert GraphJournal.parse(json.loads(json.dumps(loaded.serialize()))) == journal
    stale, fresh = Store(common), Store(common)
    stale.load_graph(RUN)
    current = fresh.load_graph(RUN)
    current.updated_at = "2026-10-13T12:05:00+00:00"
    fresh.save_graph(current)
    with pytest.raises(StateError):
        stale.save_graph(journal)


def test_manual_graph_journal_keeps_its_exact_shape(common: Path) -> None:
    journal = native_journal()
    journal.native = None
    store = Store(common)

    store.save_graph(journal)
    data = (common / "armory" / "ship" / "graphs" / f"{RUN}.json").read_bytes()

    assert "native" not in json.loads(data)
    assert Store(common).load_graph(RUN) == journal
    explicit = {**journal.serialize(), "native": None}
    with pytest.raises(ReceiptInputError):
        GraphJournal.parse(explicit)


def native_payload() -> Payload:
    return accepted(native_journal()).serialize()


def native_part(data: Payload, *path: str | int) -> dict[str, object]:
    target: object = data["native"]
    for key in path:
        if isinstance(key, int):
            target = cast(list[object], target)[key]
        else:
            target = cast(dict[str, object], target)[key]
    return cast(dict[str, object], target)


def set_native(*path: str | int, **values: object) -> Callable[[Payload], None]:
    def change(data: Payload) -> None:
        native_part(data, *path).update(values)

    return change


def set_journal(**values: object) -> Callable[[Payload], None]:
    def change(data: Payload) -> None:
        data.update(values)

    return change


def select_node(pr: int, selected: bool) -> Callable[[Payload], None]:
    def change(data: Payload) -> None:
        for node in cast(list[dict[str, object]], data["nodes"]):
            if node["pr"] == pr:
                node["selected"] = selected
                node["decision_identity"] = DIGEST if selected else None
                node["state"] = "PENDING" if selected else "RETAINED"

    return change


def complete_unverified(data: Payload) -> None:
    nodes = cast(list[dict[str, object]], data["nodes"])
    for node, run_id in zip(nodes[:2], (OTHER_RUN, "c" * 32), strict=True):
        node["state"], node["run_id"] = "LANDED", run_id
    data["status"] = "COMPLETE"
    native_part(data, "members", 1).update(verified=False)


def oversized_scope(data: Payload) -> None:
    native_part(data)["scope"] = list(range(1, 70))


# Each corruption and the rule that refuses it.
NATIVE_REJECTS: list[tuple[Callable[[Payload], None], str]] = [
    (set_journal(native=None), "native record must be a JSON object"),
    (set_native(unknown=True), "native record fields are missing"),
    (set_native("request", unknown=True), "native request fields are missing"),
    (set_native("members", 0, unknown=True), "native member fields are missing"),
    (set_native("request", uuid=UUID.upper()), "uuid must be a lowercase UUID"),
    (set_native("request", uuid="not-a-uuid"), "uuid must be a lowercase UUID"),
    (set_native("request", method="squash"), "merge_queue sends no method"),
    (set_native("request", action="direct_merge", echo_action="direct_merge"),
     "direct_merge names one"),
    (set_native("request", action="fast_forward"), "unsupported action or state"),
    (set_native("request", method="fast-forward", action="default"),
     "request method has an unsupported value"),
    (set_native("request", echo_method="squash"), "echo must equal the exact"),
    (set_native("request", echo_head=head_of(4)), "echo must equal the exact"),
    (set_native("request", expected_head=head_of(4), echo_head=head_of(4)),
     "must guard the selected head"),
    (set_native("request", message="line one\nline two"),
     "message must be plain text"),
    (set_native("request", message="m" * 513), "message must be plain text"),
    (set_native("request", status="merged"), "only a merged status has a merge"),
    (set_native("request", status="queued"), "status has an unsupported value"),
    (set_native("request", sha=head_of(9)), "only a merged status has a merge"),
    (set_native("request", message=None), "status and message together"),
    (set_native("request", uuid=None), "only an immediate merged/enqueued answer"),
    (set_native("request", state="PLANNED"), "exactly a dispatched request has a time"),
    (set_native("request", state="DISPATCHING", uuid=None, status=None,
                message=None, echo_action=None, echo_method=None, echo_head=None),
     "landings are recorded only after the request outcome"),
    (set_native("request", state="REJECTED", detail="HTTP 422 refused"),
     "a refused or unknown request has no id or echo"),
    (set_native("request", state="UNKNOWN", uuid=None, echo_action=None,
                echo_method=None, echo_head=None, status=None, message=None),
     "a refused or unknown request has no id or echo"),
    (set_native("request", state="SENT"), "unsupported action or state"),
    (set_native(selected=4), "scope must end at the selected PR"),
    (set_native(scope=[4, 5, 4]), "native scope must list distinct PRs"),
    (set_native(scope=[], selected=5), "native scope must list distinct PRs"),
    (oversized_scope, "native scope must list at most"),
    (set_native(retained=[]), "members must be the scope then the retained PRs"),
    (set_native(size=4), "must reach the top of the stack"),
    (set_native(base_ref="trunk"), "trunk is its stack base"),
    (set_native(base_ref="refs/heads/main"), "stack base ref must be a short branch"),
    (set_native(stack=0), "stack number must be a bounded positive integer"),
    (set_native("members", 1, position=3), "#5 is not at the next stack position"),
    (set_native("members", 1, base_ref="main"), "#5 must sit on the member below"),
    (set_native("members", 1, slice_base=STACK_BASE),
     "#5 must sit on the member below"),
    (set_native("members", 1, slice_base=head_of(5)), "#5 own slice must be nonempty"),
    (set_native("members", 1, head_sha="abc"), "#5 head must be a full object"),
    (set_native("members", 1, slice_identity="ff"),
     "#5 slice identity must be a SHA-256 identity"),
    (set_native("members", 1, landing=None), "a landed tree needs its landing"),
    (set_native("members", 1, landed_tree=None), "a verified landing both"),
    (set_native("members", 1, verified="yes"), "#5 verified flag must be a boolean"),
    (set_native("members", 1, fork=head_of(5)),
     "#5: only a retained member records a fork"),
    (set_native("members", 2, fork=head_of(4)), "#6 is retained on the selected head"),
    (set_native("members", 2, landing=head_of(9)), "and never lands here"),
    (set_native("members", 0, pr=6), "members must be the scope then the retained"),
    (select_node(6, True), "every retained native PR must be an unselected node"),
    (select_node(5, False), "every native scope PR must be a selected graph node"),
    (complete_unverified, "a complete native run has verified every scope landing"),
    (set_journal(endpoint="pr"), "a pr-endpoint graph run is observation-only"),
]  # fmt: skip


@pytest.mark.parametrize(("corrupt", "rule"), NATIVE_REJECTS)
def test_malformed_native_records_are_refused(
    corrupt: Callable[[Payload], None], rule: str
) -> None:
    data = native_payload()
    GraphJournal.parse(data)
    corrupt(data)

    with pytest.raises(ReceiptInputError, match=rule):
        GraphJournal.parse(data)


@pytest.mark.parametrize(
    "request_row",
    [
        {"state": "ACCEPTED", "uuid": None, "status": "merged", "message": "done",
         "sha": "c" * 40, "echo_action": None, "echo_method": None,
         "echo_head": None},
        {"state": "REJECTED", "uuid": None, "status": "failed",
         "message": "Merge conflict.", "echo_action": None, "echo_method": None,
         "echo_head": None, "detail": "the provider answered failed"},
        {"state": "UNKNOWN", "uuid": None, "status": None, "message": None,
         "echo_action": None, "echo_method": None, "echo_head": None,
         "detail": "native-merge-uncertain-timeout"},
    ],
)  # fmt: skip
def test_each_request_outcome_keeps_confirmed_landings(
    common: Path, request_row: dict[str, object]
) -> None:
    data = native_payload()
    native_part(data, "request").update(request_row)
    journal = GraphJournal.parse(data)

    Store(common).save_graph(journal)
    loaded = Store(common).load_graph(RUN)

    assert loaded == journal
    assert loaded.native is not None
    assert [m.landing is not None for m in loaded.native.members] == [True, True, False]
