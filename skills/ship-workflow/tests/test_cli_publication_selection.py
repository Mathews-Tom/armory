"""Consumer-visible --pr selection of a confirmed-but-unbound own PR."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace

import pytest
import ship
import test_publication as publication
from test_publication import (
    BASE_REPO,
    BRANCH,
    HOST,
    MappedGit,
    Shop,
    dirty,
    git,
    interrupt_binding_once,
    pending_creation,
    ref,
    run_of,
)

isolated_git = publication.isolated_git
shop = publication.shop

pytestmark = pytest.mark.skipif(os.name != "posix", reason="journals require POSIX")


def interrupted(shop: Shop, monkeypatch: pytest.MonkeyPatch) -> str:
    """A real creation that was confirmed and then interrupted before binding."""
    dirty(shop)
    interrupt_binding_once(monkeypatch)
    first, code = shop.ship(shop.request(plan=shop.plan()))
    assert (code, first["status"]) == (130, "WAITING"), first
    assert pending_creation(shop, first) == ("CONFIRMED", 1)
    assert shop.receipt(first).target is None
    return run_of(first)


def cli(
    shop: Shop,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, dict[str, object]]:
    monkeypatch.chdir(shop.work)
    monkeypatch.setattr(ship, "GitRepository", MappedGit)
    monkeypatch.setattr(ship, "GitHub", lambda host, repo, deadline: shop.hub)
    monkeypatch.setattr(
        sys, "argv", ["ship.py", "--repo", f"{HOST}/{BASE_REPO}", *argv]
    )
    capsys.readouterr()
    code = ship.main()
    return code, json.loads(capsys.readouterr().out)


def journal(shop: Shop, run_id: str) -> bytes:
    return (shop.store().directory / f"{run_id}.json").read_bytes()


@pytest.mark.parametrize("explicit", [True, False])
@pytest.mark.parametrize("merged", [False, True])
def test_pr_selects_the_confirmed_unbound_own_run(
    shop: Shop,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    explicit: bool,
    merged: bool,
) -> None:
    run_id = interrupted(shop, monkeypatch)
    if merged:
        published = git(shop.work, "rev-parse", f"refs/heads/{BRANCH}")
        shop.hub.merge(1, published, "squash")
        git(shop.bare, "update-ref", "-d", f"refs/heads/{BRANCH}")
    resume = ("--resume", run_id) if explicit else ("--resume",)

    code, result = cli(shop, monkeypatch, capsys, *resume, "--pr", "1")

    assert (code, result["status"]) == (0, "COMPLETE"), result
    assert result["run_id"] == run_id
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
    assert shop.store().load(run_id).number == 1
    if merged:
        assert ref(shop.bare, f"refs/heads/{BRANCH}") is None


@pytest.mark.parametrize("explicit", [True, False])
def test_wrong_pr_never_selects_or_mutates_the_unbound_run(
    shop: Shop,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    explicit: bool,
) -> None:
    run_id = interrupted(shop, monkeypatch)
    saved = journal(shop, run_id)
    resume = ("--resume", run_id) if explicit else ("--resume",)

    code, result = cli(shop, monkeypatch, capsys, *resume, "--pr", "2")

    assert (code, result["status"]) == (2, "BLOCKED"), result
    assert journal(shop, run_id) == saved
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]


@pytest.mark.parametrize("outcome", ["PENDING", "REJECTED"])
def test_unconfirmed_creation_is_not_selected_as_an_own_pr(
    shop: Shop,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: str,
) -> None:
    run_id = interrupted(shop, monkeypatch)
    store = shop.store()
    receipt = store.load(run_id)
    assert receipt.publication is not None and receipt.publication.create is not None
    create = replace(receipt.publication.create, outcome=outcome, number=None)
    store.save(
        replace(receipt, publication=replace(receipt.publication, create=create))
    )
    saved = journal(shop, run_id)

    code, result = cli(shop, monkeypatch, capsys, "--resume", run_id, "--pr", "1")

    assert (code, result["status"]) == (2, "BLOCKED"), result
    assert journal(shop, run_id) == saved
    assert len(shop.hub.create_calls) == 1 and list(shop.hub.entries) == [1]
