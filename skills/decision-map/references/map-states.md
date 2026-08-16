# Map States

Evaluate these conditions in order. `frontier.py` computes and prints the selected state.

| Order | State | Condition | Meaning |
|---|---|---|---|
| 1 | `ACTIVE` | frontier is non-empty | Actionable decision available now |
| 2 | `WAITING` | open tickets exist and any is claimed | Actionable work is in flight elsewhere |
| 3 | `BLOCKED` | open tickets exist, none actionable or claimed | Every path has an unresolved blocker |
| 4 | `FOGGY` | no open tickets and fog remains | Unspecified questions remain |
| 5 | `COMPLETE` | no open tickets, no fog, and no `Unresolved contradiction:` entry in map Notes | Hand off to `plan-prompts` |

The key invariant is `frontier empty != map complete`. The order resolves overlap: when one ticket is claimed and another is blocked, `WAITING` outranks `BLOCKED`. `COMPLETE` is only a recommendation to begin implementation planning; it does not produce a plan.
