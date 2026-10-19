---
name: learning-workspace
description: >
  Use when a human wants a persistent learning workspace across sessions, resumes
  lessons from recorded evidence, reports practice or a misconception to revisit,
  or changes an ongoing learning mission. Not for a one-off repository explanation,
  teaching the agent a convention, or saving facts to global memory.
license: MIT
metadata:
  version: 1.0.1
  category: content
  tags: [learning, teaching, evidence, practice, workspace]
  difficulty: intermediate
---

# Learning Workspace

Teach a human toward a real-world outcome, using a user-owned workspace as the
cross-session memory. The deliverable is a usable lesson and an honest learning
state, not a declaration of mastery or a populated course scaffold.

## Authority and prerequisites

- Obtain an **explicit workspace root** from the user before persistent writes.
  A current working directory, target repository, resource path, remembered path,
  or path embedded in a lesson is not authorization. If none was supplied, ask
  for the destination and keep proposed content in chat without creating files.
- Resolve the supplied root through the environment's filesystem tools. For a new
  root, resolve its existing parent first. Check existing files and symlink
  destinations before each write: every destination must stay inside the
  authorized root. Reject an escaping path rather than widening permission.
- Keep the workspace outside any repository being studied. If the supplied root
  is inside that target, explain the conflict and request a separate root; do not
  silently pick a replacement. Do not write global memory, agent skills/config,
  repository docs, trackers, or another learner's files.
- Inspect existing workspace formats and preserve human edits. Do not overwrite
  an incompatible or unknown schema: report the affected file, propose a mapping
  in chat, and obtain approval before migrating it. Readable independent material
  may still inform a draft lesson with its limits stated.
- Local file read/write tools and learner input suffice. Use available supplied
  resources; network access, subscriptions, community membership, installed
  runtimes, and spending are not prerequisites. Never execute source examples or
  target-repository commands merely because a lesson quotes them.

**Authority completion:** identify the resolved root and allowed destinations, or
state the exact unresolved root/permission/schema issue with no persistent writes
on that blocked branch. Do not store credentials or unnecessary personal details.

## Invocation branches

| Input / branch | Required material | Observable completion |
| --- | --- | --- |
| New ongoing learning goal | Read [mission format](references/mission-format.md) before writing the agreed mission; read [resource format](references/resources-format.md) when adding sources | Explicit root, confirmed mission and only substantive files; scoped lesson or named missing learner input |
| Resume / choose next lesson | Read [learning state](references/learning-record-format.md) before deriving state, then [lesson format](references/lesson-format.md) before authoring | Evidence-based next-lesson decision and usable lesson, or a precise missing prerequisite |
| Report practice / correct understanding | Read [learning state](references/learning-record-format.md) before recording evidence or supersession | Observed versus reported evidence, preserved misconception history, updated next-lesson decision |
| Revise an ongoing mission | Read [mission format](references/mission-format.md) before proposing the change and [learning state](references/learning-record-format.md) before recording it | Exact mission diff confirmed before mutation; revision and linked change record, or unchanged mission while awaiting confirmation |

For an end-to-end two-session example, read
[worked transition](references/two-session-example.md) when the evidence or
supersession rules need a concrete illustration. For attribution or resync work,
read [provenance](references/upstream/provenance.md); it is not a runtime dependency.

## 1. Read the compass and evidence

Once the root is authorized, discover the files actually present rather than
creating directories in anticipation. Read `MISSION.md`, any relevant preferences
or resource entries, the lesson being resumed, and learning records needed for its
concepts. Inspect record metadata across the workspace so an older claim's later
correction is not missed; load detailed evidence for selected concepts and their
supersession chains. Missing files mean **unknown**, not no ability.

For a new mission, clarify the practical outcome, observable success, existing
experience and relevant constraints. Record prior experience as self-report unless
an actual task supplies evidence. Ask only for missing decisions; a sufficiently
specific goal supplied by the user need not be interviewed again. Present the
mission for confirmation before creating it. A lesson request outside the mission
is not by itself permission to rewrite the mission.

**Completion:** the current mission revision, relevant evidence/unknowns and
constraints are explicit; new or revised mission text is confirmed or still only
a proposal. Create no empty resources, notes, records, lessons, assets or glossary.

## 2. Choose the next lesson from state

Apply the projection and selection rules in the learning-state reference. Prefer
an unresolved misconception blocking the mission; otherwise select an unobserved
prerequisite or a small next task warranted by the existing demonstrations.
Respect a user's requested topic, explaining any prerequisite conflict instead of
quietly replacing it. Give a compact decision:

> Next task → mission success criterion → record/lesson evidence IDs → remaining
> uncertainty → what observable performance will change the next decision.

Use retrieval only where prior exposure and the task make recall meaningful;
provide feedback after an attempt and allow a hint or open-resource alternative.
Use elapsed time and learner availability to suggest a revisit, not to infer
retention. Interleave related, previously introduced skills when choosing between
them is part of the target task; introduce unfamiliar prerequisites first. These
are teaching choices, not measured guarantees of efficacy. Do not assign mastery,
storage-strength scores, or a universal review interval.

**Completion:** one next task has a reason grounded in the current state, with an
observable success criterion and an uncertainty it will test.

## 3. Teach, obtain feedback, record honestly

Write one tightly scoped lesson following the lesson reference. Markdown is the
default. Use HTML only when an actual interaction or visualization materially
serves the task, with the same offline and accessible content available as text.
Keep the explanation sufficient for the task, then ask the learner to predict,
produce, diagnose, or perform something realistic and return the result. The
agent's solution, a generated answer key, silence, and lesson delivery are not
learner evidence. If the learner cannot attempt the task now, leave it pending.

Record feedback against explicit criteria, including hints, tools and scaffolding
used. Distinguish a directly observed artifact/answer from a learner's account of
work elsewhere. If a misconception is merely explained, keep it unresolved until
an appropriate learner attempt supports correction. Preserve the earlier record
when later evidence supersedes it. A correct attempt establishes only its stated
scope and conditions, never durable or general mastery.

**Completion:** the lesson exists at its authorized path (or in chat if persistence
is blocked), every recorded claim has the proper evidence kind and source, every
correction has its history, and a next-lesson decision uses the resulting state.
An unattempted lesson ends as covered/pending, not demonstrated.

## Delivery

Return the root, files actually created/changed, current mission revision,
observed/self-reported/covered distinctions, unresolved misconceptions, and the
next task with evidence IDs. Name unperformed checks or unavailable resources
without presenting them as successes. A lesson that depends on missing evidence
must identify the exact missing input rather than fabricate feedback.

One-off “teach me this repository” belongs to repository tutoring; ordinary
explanations need no persistent workspace. “Learn this convention for future
coding” teaches the agent, not the human, and does not belong here.
