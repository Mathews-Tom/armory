// Pure data contract. Every effectful read supplies its own provenance and visibility.
export const SCHEMA = "armory.delivery-radar.observation/v1" as const;
export const FEATURE_VERSION = "1.0.0" as const;
export const CORE_VERSION = "1.0.0" as const;

export interface Selection {
  repository: string;
  pullRequests: readonly number[];
}

export interface Binding {
  repository: string;
  pullRequest: number;
  headOid: string;
  baseOid: string;
  viewerId: string;
}

export type SourceStatus = "available" | "partial" | "unavailable" | "rate-limited" | "malformed" | "not-selected";

export interface Source<T> {
  status: SourceStatus;
  binding: Binding | null;
  observedAt: number;
  reference: string;
  diagnostic: string | null;
  value: T | null;
}

export interface PullIdentity {
  number: number;
  url: string;
  title: string;
  state: "OPEN" | "CLOSED" | "MERGED";
  headOid: string;
  baseOid: string;
  headRef: string;
  baseRef: string;
  headRepository: string | null;
  draft: boolean;
  mergeable: "MERGEABLE" | "CONFLICTING" | "UNKNOWN";
  mergeCommitOid: string | null;
}

export interface Review {
  id: string;
  reviewerId: string;
  state: "APPROVED" | "CHANGES_REQUESTED" | "COMMENTED" | "DISMISSED" | "PENDING";
  commitOid: string | null;
  submittedAt: number | null;
}

export interface ReviewThread {
  id: string;
  resolved: boolean;
  outdated: boolean;
}

export interface Check {
  id: string;
  context: string;
  publisherId: number | null;
  state: "pending" | "passed" | "failed" | "cancelled" | "unknown";
  headOid: string;
  testedBaseOid: string | null;
  url: string | null;
  completedAt: number | null;
}

export interface RequiredCheck {
  context: string;
  publisherId: number | null;
}

export interface RequiredPolicy {
  checks: readonly RequiredCheck[];
  requiredApprovals: number;
  requireCodeOwnerReview: boolean;
  requireLatestApproval: boolean;
  dismissStaleReviews: boolean;
  strict: boolean;
  unsupported: readonly string[];
}

// A workflow success or a merged PR alone is never proof of published artifacts.
export interface Publication {
  state: "published" | "pending" | "failed" | "unknown";
  commitOid: string | null;
  artifactIds: readonly string[];
  url: string | null;
}

export interface PullObservation {
  before: Source<PullIdentity>;
  after: Source<PullIdentity>;
  reviews: Source<readonly Review[]>;
  threads: Source<readonly ReviewThread[]>;
  checks: Source<readonly Check[]>;
  policy: Source<RequiredPolicy>;
  publication: Source<Publication>;
}

export interface Observation {
  schema: typeof SCHEMA;
  selection: Selection;
  viewerBefore: Source<string>;
  viewerAfter: Source<string>;
  startedAt: number;
  finishedAt: number;
  pulls: readonly PullObservation[];
}

export type State = "passed" | "failed" | "pending" | "unknown" | "not-applicable";
export type Action = "agent-work" | "external-wait" | "owner-decision" | "none";

export interface Dimension {
  state: State;
  reasons: readonly string[];
  sources: readonly string[];
}

export interface PullView {
  number: number;
  title: string;
  url: string;
  headOid: string | null;
  baseOid: string | null;
  observedAt: number;
  implementation: Dimension;
  verification: Dimension;
  review: Dimension;
  merge: Dimension;
  publication: Dimension;
  action: Action;
  nextAction: string;
  diagnostics: readonly string[];
}

export interface RadarView {
  schema: "armory.delivery-radar.view/v1";
  repository: string;
  viewerId: string | null;
  observedAt: number;
  pulls: readonly PullView[];
  edges: readonly { parent: number; child: number }[];
  diagnostics: readonly string[];
}
