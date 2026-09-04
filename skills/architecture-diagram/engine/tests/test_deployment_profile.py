from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import render
from engine.render import check_deployment_profile, load_spec


_FIXTURES = Path(__file__).parent / "fixtures"


def _findings(name: str) -> list[render.Diagnostic]:
    spec = load_spec((_FIXTURES / name).read_text())
    return check_deployment_profile(spec)


def _codes(name: str) -> list[str]:
    return [finding.code for finding in _findings(name)]


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("deployment-profile-missing-owner.yaml", "profile/missing-owner"),
        ("deployment-profile-missing-region.yaml", "profile/missing-region-scope"),
        ("deployment-profile-ambiguous-region.yaml", "profile/ambiguous-region"),
        (
            "deployment-profile-storage-outside-security.yaml",
            "profile/storage-outside-security-zone",
        ),
        (
            "deployment-profile-inconsistent-security-region.yaml",
            "profile/inconsistent-security-zone-region",
        ),
        (
            "deployment-profile-missing-boundary-mechanism.yaml",
            "profile/missing-boundary-crossing-mechanism",
        ),
        (
            "deployment-profile-missing-required-zone-kinds.yaml",
            "profile/missing-required-zone-kinds",
        ),
    ],
)
def test_deployment_profile_rejects_each_required_fact(fixture: str, code: str) -> None:
    finding = next(finding for finding in _findings(fixture) if finding.code == code)
    assert finding.severity == "error"
    assert finding.supported_fixes


def test_deployment_profile_accepts_complete_authored_facts() -> None:
    assert _codes("deployment-profile-valid.yaml") == []


def test_profile_is_inert_when_omitted() -> None:
    spec_text = (_FIXTURES / "deployment-profile-valid.yaml").read_text()
    without_profile = spec_text.replace("profile: deployment-ownership\n", "")

    result = render.render(load_spec(without_profile), lambda _provider, _service: None)

    assert result.ok
    assert not [
        finding for finding in result.diagnostics if finding.code.startswith("profile/")
    ]


def test_existing_serverless_spec_remains_outside_profile_validation() -> None:
    existing = (
        Path(__file__).parent.parent.parent / "assets" / "example-serverless.yaml"
    ).read_text()
    spec = load_spec(existing)

    assert spec.profile is None
    assert check_deployment_profile(spec) == []


def test_profile_failure_has_a_distinct_receipt_check(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert (
        render._check_name(_findings("deployment-profile-missing-owner.yaml")[0])
        == "profile"
    )
    code = render.main(
        [
            "validate",
            str(_FIXTURES / "deployment-profile-missing-owner.yaml"),
            "--cache-dir",
            str(tmp_path),
            "--json",
        ]
    )
    receipt = json.loads(capsys.readouterr().out)

    assert code == render.EXIT_FAILURE
    assert receipt["validation"] == {
        "checks_passed": 10,
        "checks_total": 11,
        "quality": "standard",
        "composition_status": "passed",
        "errors": 1,
        "warnings": 0,
    }
