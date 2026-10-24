# Run Preflight

Check the prerequisites of one explicitly declared OMP SkillsBench invocation and consume a complete admission record immediately before the owned dispatch boundary. This is an unregistered standalone implementation prefix: no native command, installable package, catalog entry or native-compatibility claim is activated by this delivery.

The normal check reads selected local files and directory metadata. It does not query an authenticated account, infer quota from a signed-in profile, start OMP, request a model, launch the configured bridge or write feature state. Unknown quota remains `unknown`, with its observation time and reason. Exit zero means a normalized report was produced, not permission to launch a campaign.

## Standalone interface

Use the repository-pinned Bun workspace and Python 3.12 project environment. Paths passed to the helper are explicit absolute paths; there is no checkout discovery or package-path fallback.

```sh
bun install --cwd extensions --frozen-lockfile
bun extensions/run-preflight/helpers/cli.ts --help
uv run --python 3.12 python scripts/omp_preflight_cli.py --help
```

The helper has three operations:

| Operation | Inputs | Effect |
| --- | --- | --- |
| `check` | `--config PATH --declaration PATH` | Observe and derive a ready/blocked/unknown report; never spawn the managed runner. |
| `admit` | The same selection plus `--record PATH --invocation PATH` | Reobserve prerequisites and validate the complete record against the actual consumer tuple; never spawn a child itself. |
| `probe` | `--config PATH --declaration PATH` | Only an explicitly authorized synthetic-local declaration can call the configured project bridge. |

`--format json` is the default; `--format text` renders the same status, quota and scope limitations. Invalid arguments, malformed inputs and bridge execution/protocol failures return 2. SIGINT/SIGTERM cancel owned bridge work and return 130/143. A valid blocked report can return zero: always inspect `status`, `admission` and `admitted` separately. Only the actual dispatch boundary consumes admission; a successful ordinary check is not a consumed record.

## Versioned project and declaration

The strict version-1 JSON vocabulary is defined in [`core/types.ts`](core/types.ts) and validated in [`core/validation.ts`](core/validation.ts). Extra fields, incompatible versions, duplicate bindings, malformed hashes/timestamps and control-bearing inputs are rejected.

Project configuration selects `schemaVersion: 1`, `coreVersion: "1.0.0"`, `adapterId: "omp-skillsbench"`, `adapterVersion: 1`, the absolute package/project/contract paths, and `helperPath` (`helpers/cli.ts` for this prefix, `helpers/cli.js` for a bundled helper). `bridgeArgv` explicitly names the executable, absolute entry script and literal arguments. It is trusted project code, not an extension-provided sandbox. Bind the actual entry script, not just its interpreter or an unrelated argv operand.

A declaration binds its run ID and purpose, issue/expiry interval, raw project-config hash, exact target/model/thinking/profile/cell/condition identity, checkpoint root, source/config/data hashes, nonsecret identity observation, quota observation, limits and authorizations. The account fingerprint is a local nonsecret identifier, never a credential. An attestation is not an authentication or provider-capacity probe.

The Python project adapter derives its required consumed-input inventory from the configured contract and selected task. Do not replace those bindings with unrelated files. It reloads the canonical effective contract, rejects caller-mutated task/condition data, and rechecks selected state immediately before invocation. File facts include raw hashes and file identities; directory facts bind the selected project, package and checkpoint directories. Each observation retains private read-time stat snapshots through its final recheck, including ctime and mode, so timestamp-preserving source rewrites during observation refuse admission. Missing, expired, replaced or changed prerequisites refuse admission before the managed runner.

## Authority and enforcement

Synthetic authority is explicitly `synthetic-local-sentinel`, with `synthetic-local`/`not-applicable` identity, `local-sentinel-only` scope, an invocation digest and acknowledgement of unknown quota. Its authorization lasts at most 900 seconds. It never inherits the current host account's campaign authority. The project bridge is `scripts/omp_preflight_cli.py --synthetic-sentinel`; it reaches the actual `dispatch_cell` integration using a fixed real Python `pass` child instead of forwarding OMP argv.

One fresh synthetic probe reaches one harmless child. Its empty output is honestly `terminal-receipt-unavailable`: no model result, derived receipt, benchmark outcome or completed campaign is fabricated. A stale declaration reaches zero children. Repeated invocations require the same current explicit prerequisites; there is no cross-invocation single-use counter.

The existing runner owns its 600-second OMP limit and 630-second outer timeout. Required call/worker/concurrency/token/currency limits are unsupported and block; advisory values are caller discipline, not enforcement. Unknown managed quota produces no admission. No dollar cap, shared call/worker counter or universal bypass guard is provided.

The boundary protects this managed callable, not arbitrary commands, malicious trusted project code or unobserved execution paths. Filesystem observations narrow but cannot eliminate the final filesystem-to-spawn race. Existing live-study holds, population, treatments, pins and results are unchanged. Neither this feature nor a local synthetic success authorizes a paid run or turns the existing preflight-only CLIs into live launchers.

## Verification

```sh
uv run --python 3.12 python scripts/check_extensions.py --feature run-preflight --stage core
uv run --python 3.12 python -m pytest tests/test_omp_skillsbench.py tests/test_omp_skillsbench_dispatch.py tests/test_run_preflight_admission.py -q
uv run --python 3.12 python scripts/omp_skillsbench.py --preflight
uv run --python 3.12 python scripts/omp_skillsbench_dispatch.py --preflight
```

These are credential-free local/core checks, not actual OMP or Claude compatibility qualification. Core acceptance includes real local process execution, complete-record consumption, changed/expired/unsupported/missing prerequisites and zero-spawn refusal. The two common preflight CLIs validate the unchanged frozen command matrix offline and do not query provider accounts.

## Explicit local sentinel walkthrough

Run from the repository root. This creates only disposable local JSON/identity/checkpoint files and authorizes a harmless Python `pass` invocation with acknowledged unknown quota. It does not authorize a live OMP cell. The adapter-owned inventory is reused instead of copying a potentially incomplete list of consumed files. Flags and bindings use the same canonical path spelling, including macOS's `/private/var` spelling for temporary data.

```sh
umask 077
export ARMORY_PREFLIGHT_EXAMPLE_ROOT="$(mktemp -d)"
export ARMORY_PREFLIGHT_EXAMPLE_ROOT="$(
  uv run --python 3.12 python -c \
    'import os; print(os.path.realpath(os.environ["ARMORY_PREFLIGHT_EXAMPLE_ROOT"]))'
)"
uv run --python 3.12 python - <<'PY'
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.omp_preflight import (
    derive_runner_invocation,
    load_project_config,
    required_dispatch_inputs,
)
from scripts.omp_skillsbench import declared_omp_cells, load_omp_run_contract

repo = Path.cwd().resolve()
root = Path(os.environ["ARMORY_PREFLIGHT_EXAMPLE_ROOT"]).resolve()
checkpoint = root / "checkpoint"
checkpoint.mkdir()
config_path = root / "project.json"
identity_path = root / "identity.json"

def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

def bind(path):
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }

save(config_path, {
    "schemaVersion": 1, "coreVersion": "1.0.0",
    "adapterId": "omp-skillsbench", "adapterVersion": 1,
    "packageRoot": str(repo / "extensions/run-preflight"),
    "helperPath": "helpers/cli.ts", "projectRoot": str(repo),
    "contractPath": str(repo / "evals/skillsbench/omp_run.yaml"),
    "bridgeArgv": [
        sys.executable, str(repo / "scripts/omp_preflight_cli.py"),
        "--synthetic-sentinel",
    ],
})
config = load_project_config(config_path)
contract = load_omp_run_contract(config.contract_path)
cell = declared_omp_cells(contract)[0]
target = next(target for target in contract.targets if target.id == cell.target_id)
invocation = derive_runner_invocation(contract, cell, target, checkpoint)
inventory = required_dispatch_inputs(config, contract, cell)
inputs = {
    category: [bind(path) for path in paths]
    for category, paths in inventory.items()
}
now = datetime.now(UTC)
issued = now.isoformat().replace("+00:00", "Z")
expires = (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
fingerprint = "local-sentinel-no-account"
save(identity_path, {
    "schemaVersion": 1, "provider": "synthetic-local",
    "profile": contract.profile, "accountFingerprint": fingerprint,
    "kind": "synthetic-local", "auth": "not-applicable",
    "observedAt": issued, "expiresAt": expires,
})
inputs["identity"] = bind(identity_path)
canonical = json.dumps(
    invocation, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
)
save(root / "declaration.json", {
    "schemaVersion": 1, "runId": "explicit-local-sentinel",
    "purpose": "synthetic-local-sentinel",
    "issuedAt": issued, "expiresAt": expires,
    "configSha256": bind(config_path)["sha256"],
    "invocation": invocation, "inputs": inputs,
    "checkpoint": {"path": str(checkpoint)},
    "limits": {
        **{
            name: {"value": 1, "required": False}
            for name in ("calls", "workers", "concurrency")
        },
        "wallSeconds": {"value": 630, "required": True},
        "tokens": None, "currency": None,
    },
    "quota": {
        "status": "unknown", "observedAt": issued, "expiresAt": expires,
        "reason": "No account or provider observation requested",
        "source": "explicit-local-example", "remainingCalls": None,
    },
    "authorizations": [{
        "runId": "explicit-local-sentinel",
        "purpose": "synthetic-local-sentinel",
        "accountFingerprint": fingerprint, "scope": "local-sentinel-only",
        "invocationSha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "acknowledgeUnknownQuota": True,
        "issuedAt": issued, "expiresAt": expires,
    }],
})
PY
bun extensions/run-preflight/helpers/cli.ts check \
  --config "$ARMORY_PREFLIGHT_EXAMPLE_ROOT/project.json" \
  --declaration "$ARMORY_PREFLIGHT_EXAMPLE_ROOT/declaration.json" --format text
bun extensions/run-preflight/helpers/cli.ts probe \
  --config "$ARMORY_PREFLIGHT_EXAMPLE_ROOT/project.json" \
  --declaration "$ARMORY_PREFLIGHT_EXAMPLE_ROOT/declaration.json" --format text
```

The check remains unknown and launches no managed child. The explicit probe reports one local child with `terminal-receipt-unavailable`, while quota stays unknown and no OMP result is persisted. Append a newline to the disposable `identity.json` without updating the declaration and repeat the probe: its old binding is stale, so the child is refused. Do not edit frozen study inputs to demonstrate drift.
