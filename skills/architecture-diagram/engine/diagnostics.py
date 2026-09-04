"""Machine-readable diagnostics and quality-profile policy."""

from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
_SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARNING)

QUALITY_STANDARD = "standard"
QUALITY_SHOWCASE = "showcase"
QUALITY_PROFILES = (QUALITY_STANDARD, QUALITY_SHOWCASE)

# Codes in this namespace describe how the drawing reads rather than whether
# the spec is answerable. They are warnings under the standard profile and
# errors under showcase, so stricter geometry rules can ship without breaking
# specs that already render.
PROFILE_SENSITIVE_NAMESPACE = "composition/"

DIAGNOSTIC_SCHEMA_VERSION = 1


@dataclass
class Diagnostic:
    """One machine-readable finding.

    The predecessor of this type was ``list[str]`` of English prose printed to
    stderr, which forced the calling agent to regex sentences and left it to
    invent its own repair. ``code`` is the stable identity, ``subject`` says
    what the finding is about, ``evidence`` carries locating values, and
    ``supported_fixes`` bounds the repair to changes an author can make in the
    spec.
    """

    code: str
    severity: str
    message: str
    subject: dict[str, object] = field(default_factory=dict)
    evidence: dict[str, object] = field(default_factory=dict)
    supported_fixes: tuple[str, ...] = ()
    suppresses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITIES:
            raise ValueError(
                f"diagnostic {self.code!r} has unknown severity {self.severity!r}; "
                f"expected one of {_SEVERITIES}"
            )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "subject": dict(self.subject),
            "evidence": dict(self.evidence),
            "supported_fixes": list(self.supported_fixes),
        }
        if self.suppresses:
            payload["suppresses"] = list(self.suppresses)
        return payload


def apply_quality_profile(
    diagnostics: list[Diagnostic], quality: str
) -> list[Diagnostic]:
    """Raise profile-sensitive findings to errors under the showcase profile."""
    if quality not in QUALITY_PROFILES:
        raise ValueError(
            f"unknown quality profile {quality!r}; expected one of {QUALITY_PROFILES}"
        )
    if quality != QUALITY_SHOWCASE:
        return list(diagnostics)
    out = []
    for diagnostic in diagnostics:
        if (
            diagnostic.code.startswith(PROFILE_SENSITIVE_NAMESPACE)
            and diagnostic.severity != SEVERITY_ERROR
        ):
            out.append(
                Diagnostic(
                    code=diagnostic.code,
                    severity=SEVERITY_ERROR,
                    message=diagnostic.message,
                    subject=diagnostic.subject,
                    evidence=diagnostic.evidence,
                    supported_fixes=diagnostic.supported_fixes,
                    suppresses=diagnostic.suppresses,
                )
            )
        else:
            out.append(diagnostic)
    return out


def suppress_derived(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Drop findings a reported cause makes redundant.

    Suppression is one level deep and keyed on ``code``. Every emitter must
    declare ``suppresses`` only for a code it directly explains, never for one
    that suppresses something else in turn.
    """
    suppressed = {code for diagnostic in diagnostics for code in diagnostic.suppresses}
    return [
        diagnostic for diagnostic in diagnostics if diagnostic.code not in suppressed
    ]


def count_by_severity(diagnostics: list[Diagnostic]) -> dict[str, int]:
    """Count error and warning diagnostics."""
    return {
        "errors": sum(
            1 for diagnostic in diagnostics if diagnostic.severity == SEVERITY_ERROR
        ),
        "warnings": sum(
            1 for diagnostic in diagnostics if diagnostic.severity == SEVERITY_WARNING
        ),
    }
