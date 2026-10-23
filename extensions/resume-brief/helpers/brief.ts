import { buildCard, discrepancies } from "../core/card.ts";
import type { Context } from "../core/index.ts";
import type { ListEntry, ListResult, RecordResult, ReopenResult, ShowResult } from "../core/protocol.ts";
import type { Snapshot } from "../core/snapshot.ts";
import { canonicalSelection, observe, resolveRepository } from "./sources.ts";
import type { ObserveOptions, Repository, Selection } from "./sources.ts";
import { openStore, StateError } from "./state.ts";
import type { SnapshotStore } from "./state.ts";

// The four read-only brief operations. The standalone CLI, the Claude helper
// and the in-process OMP adapter all call these; none of them executes,
// resumes or authorizes anything.

/** A selection or repository the caller supplied that cannot be used. */
export class InputError extends Error {}

export interface Scope {
  repositoryRoot: string;
  dataRoot: string;
  context: Context;
}

export interface RawSelection {
  contextPath: string;
  ompSessionPath: string | null;
  ompHandoffPath: string | null;
  receiptPath: string | null;
}

async function selected(path: string | null, extension: string): Promise<string | null> {
  if (path === null) return null;
  try { return await canonicalSelection(path, extension); } catch (error) {
    throw new InputError(error instanceof Error ? error.message : "invalid selected source");
  }
}

/** Canonical form of an explicit selection; nothing is discovered or scanned. */
export async function resolveSelection(raw: RawSelection): Promise<Selection> {
  return {
    contextPath: raw.contextPath,
    ompSessionPath: await selected(raw.ompSessionPath, ".jsonl"),
    ompHandoffPath: await selected(raw.ompHandoffPath, ".md"),
    receiptPath: await selected(raw.receiptPath, ".json"),
  };
}

function sameSelection(left: Selection, right: Selection): boolean {
  return left.contextPath === right.contextPath && left.ompSessionPath === right.ompSessionPath
    && left.ompHandoffPath === right.ompHandoffPath && left.receiptPath === right.receiptPath;
}

async function open(scope: Omit<Scope, "context">): Promise<{ repository: Repository; store: SnapshotStore }> {
  const repository = await resolveRepository(scope.repositoryRoot).catch((error: unknown) => {
    throw new InputError(error instanceof Error && error.message.startsWith("repository must") ? error.message : "the selected repository is not an accessible Git worktree");
  });
  return { repository, store: await openStore(scope.dataRoot, repository) };
}

async function load(store: SnapshotStore, snapshot: string): Promise<Snapshot> {
  if (snapshot !== "latest") return store.read(snapshot);
  const ids = await store.list();
  const last = ids[ids.length - 1];
  if (last === undefined) throw new StateError("no snapshot recorded for this repository");
  return store.read(last);
}

export async function recordBrief(scope: Scope, selection: Selection, options: ObserveOptions = {}): Promise<RecordResult> {
  options.signal?.throwIfAborted();
  const { repository, store } = await open(scope);
  const observations = await observe(repository, selection, Date.now, { ...options, sessionId: scope.context.sessionId });
  // Nothing is published for an invocation cancelled while it observed.
  options.signal?.throwIfAborted();
  const snapshot = await store.record(scope.context, selection, observations, Date.now());
  return { action: "record", snapshotId: snapshot.snapshotId, card: buildCard(snapshot.observations, scope.context, snapshot.recordedAtMs) };
}

/**
 * Re-read the recorded selection and compare. Native adapters pass their
 * configured selection: a snapshot recorded for a different selection is
 * refused before any source is read, so reopening never widens what is read.
 */
export async function reopenBrief(scope: Scope, snapshot: string, options: ObserveOptions & { configured?: Selection } = {}): Promise<ReopenResult> {
  options.signal?.throwIfAborted();
  const { repository, store } = await open(scope);
  const recorded = await load(store, snapshot);
  if (options.configured !== undefined && !sameSelection(recorded.selection, options.configured)) {
    throw new StateError("the recorded source selection differs from the configured selection; reopen refused without reading sources");
  }
  const current = await observe(repository, recorded.selection, Date.now, { ...options, sessionId: scope.context.sessionId });
  options.signal?.throwIfAborted();
  const recordedCard = buildCard(recorded.observations, scope.context, recorded.recordedAtMs);
  const currentCard = buildCard(current, scope.context, current.observedAtMs);
  return {
    action: "reopen", snapshotId: recorded.snapshotId, recordedAtMs: recorded.recordedAtMs, recordedBy: recorded.recordedBy,
    recorded: recordedCard, current: currentCard, discrepancies: discrepancies(recordedCard, currentCard), resumed: false, authority: "none",
  };
}

/** A recorded card with approval expiry evaluated now; no source is read. */
export async function showBrief(scope: Scope, snapshot: string): Promise<ShowResult> {
  const { store } = await open(scope);
  const recorded = await load(store, snapshot);
  return { action: "show", snapshotId: recorded.snapshotId, observations: "recorded", card: buildCard(recorded.observations, scope.context, Date.now()) };
}

export async function listBriefs(scope: Omit<Scope, "context">): Promise<ListResult> {
  const { store } = await open(scope);
  const snapshots: ListEntry[] = [];
  for (const id of await store.list()) {
    const snapshot = await store.read(id);
    snapshots.push({ snapshotId: id, recordedAtMs: snapshot.recordedAtMs, recordedBy: snapshot.recordedBy, branch: snapshot.observations.git.branch, contextPath: snapshot.selection.contextPath });
  }
  return { action: "list", snapshots };
}
