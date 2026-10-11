# Code2Video provenance

The opt-in planner, fixup and critic prompts in this directory adapt prompt logic from
Code2Video. Nothing here is needed for the template path (`scripts/build_scene.py`).

| Field         | Value                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------ |
| Paper         | [Code2Video: A Code-Centric Paradigm for Educational Video Generation](https://arxiv.org/abs/2510.01174)      |
| Authors       | Anno Yanzhe Chen et al., Show Lab, National University of Singapore                                          |
| Venue         | NeurIPS 2025 Workshop on Deep Learning for Code (DL4C)                                                        |
| Upstream repo | [showlab/Code2Video](https://github.com/showlab/Code2Video)                                                   |
| License       | MIT — full text in `LICENSE` in this directory                                                                |
| Pinned commit | `f579f1e527f9d6684eb581853f8739b6b39f2914`                                                                    |

## What is vendored (prompt text only, no upstream code)

| File         | Upstream source(s)                       |
| ------------ | ---------------------------------------- |
| `planner.md` | `prompts/stage1.py`, `prompts/stage2.py` |
| `coder.md`   | `prompts/stage3.py`                      |
| `critic.md`  | `prompts/stage4.py`                      |

Upstream stores prompts as Python functions returning f-strings. The text was extracted,
variable names were adapted to this package's storyboard schema, and the result was
reformatted as Markdown templates.

## What is reimplemented from the paper (no code copied)

- Auto-fix loop (paper section 3.3) in `scripts/render_video.py`: capture render stderr, extract the
  offending line range, call the fixup prompt, patch the scene, retry up to N times.
- Critic loop (paper section 3.4) in `scripts/critic_pass.py`: sample frames, send them to a vision
  model with the critic prompt, apply anchor-based layout patches.

## Not adopted

MMMC benchmark and TeachQuiz metric (research harness), IconFinder as a default (replaced by the
pluggable `scripts/fetch_assets.py`), upstream shell entry points, and 3D scenes.

## Re-sync policy

Prompts stay pinned to the commit above. Re-sync only for substantive upstream prompt changes, after
diffing against the pinned commit; never auto-update.
