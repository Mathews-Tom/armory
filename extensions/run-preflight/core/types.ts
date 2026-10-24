// Pure vocabulary: runtime observations and clock/hash functions are supplied by helpers.
export const CORE_VERSION = "1.0.0" as const;
export const SCHEMA_VERSION = 1 as const;
export const ADAPTER_ID = "omp-skillsbench" as const;
export const ADAPTER_VERSION = 1 as const;
export const RUNNER_MAX_SECONDS = 600;
export const RUNNER_GRACE_SECONDS = 30;
export const SYNTHETIC_AUTHORITY_SECONDS = 900;
export const MAX_JSON_BYTES = 1024 * 1024;
export const MAX_BINDINGS = 256;

export type Purpose = "synthetic-local-sentinel" | "managed";
export interface FileBinding { readonly path: string; readonly sha256: string }
export interface Invocation {
  readonly adapterId: typeof ADAPTER_ID;
  readonly adapterVersion: typeof ADAPTER_VERSION;
  readonly targetId: string;
  readonly targetModel: string;
  readonly targetThinking: string;
  readonly profile: string;
  readonly cell: {
    readonly taskId: string;
    readonly condition: string;
    readonly targetId: string;
    readonly repetition: number;
    readonly conditionHash: string;
  };
  readonly wallSeconds: number;
  readonly checkpointRoot: string;
}
export interface ProjectConfig {
  readonly schemaVersion: typeof SCHEMA_VERSION;
  readonly adapterId: typeof ADAPTER_ID;
  readonly adapterVersion: typeof ADAPTER_VERSION;
  readonly coreVersion: typeof CORE_VERSION;
  readonly packageRoot: string;
  readonly helperPath: "helpers/cli.ts" | "helpers/cli.js";
  readonly projectRoot: string;
  readonly contractPath: string;
  readonly bridgeArgv: readonly [executable: string, entryScript: string, ...args: string[]];
}
export interface Identity {
  readonly schemaVersion: typeof SCHEMA_VERSION;
  readonly provider: string;
  readonly profile: string;
  readonly accountFingerprint: string;
  readonly kind: "synthetic-local" | "managed";
  readonly auth: "not-applicable" | "attested";
  readonly observedAt: string;
  readonly expiresAt: string;
}
export interface Limit { readonly value: number; readonly required: boolean }
export interface Limits {
  readonly calls: Limit;
  readonly workers: Limit;
  readonly concurrency: Limit;
  readonly wallSeconds: Limit;
  readonly tokens: Limit | null;
  readonly currency: (Limit & { readonly unit: string }) | null;
}
export interface Quota {
  readonly status: "observed" | "unknown";
  readonly observedAt: string;
  readonly expiresAt: string;
  readonly reason: string;
  readonly source: string;
  readonly remainingCalls: number | null;
}
export interface Authorization {
  readonly runId: string;
  readonly purpose: Purpose;
  readonly accountFingerprint: string;
  readonly scope: "local-sentinel-only" | "managed-invocation";
  readonly invocationSha256: string;
  readonly acknowledgeUnknownQuota: boolean;
  readonly issuedAt: string;
  readonly expiresAt: string;
}
export interface Declaration {
  readonly schemaVersion: typeof SCHEMA_VERSION;
  readonly runId: string;
  readonly purpose: Purpose;
  readonly issuedAt: string;
  readonly expiresAt: string;
  readonly configSha256: string;
  readonly invocation: Invocation;
  readonly inputs: {
    readonly source: readonly FileBinding[];
    readonly config: readonly FileBinding[];
    readonly data: readonly FileBinding[];
    readonly identity: FileBinding;
  };
  readonly checkpoint: { readonly path: string };
  readonly limits: Limits;
  readonly quota: Quota;
  readonly authorizations: readonly Authorization[];
}
export interface FileFact extends FileBinding {
  readonly realPath: string;
  readonly device: string;
  readonly inode: string;
  readonly size: number;
  readonly modifiedNs: string;
}
export interface DirectoryFact {
  readonly path: string;
  readonly realPath: string;
  readonly device: string;
  readonly inode: string;
  readonly mode: number;
  readonly uid: number;
  readonly gid: number;
  readonly writable: boolean;
}
export interface Facts {
  readonly config: FileFact;
  readonly declaration: FileFact;
  readonly helper: FileFact;
  readonly source: readonly FileFact[];
  readonly configs: readonly FileFact[];
  readonly data: readonly FileFact[];
  readonly identityFile: FileFact;
  readonly identity: Identity;
  readonly checkpoint: DirectoryFact;
  readonly projectRoot: DirectoryFact;
  readonly packageRoot: DirectoryFact;
}
export interface Observation {
  readonly config: ProjectConfig;
  readonly declaration: Declaration;
  readonly facts: Facts;
}
export interface Capabilities {
  readonly wallSeconds: number;
  readonly runnerMaxSeconds: number;
  readonly calls: "caller-discipline";
  readonly workers: "caller-discipline";
  readonly concurrency: "caller-discipline";
  readonly tokens: "unsupported";
  readonly currency: "unsupported";
}
export interface AdmissionScope {
  readonly runId: string;
  readonly purpose: Purpose;
  readonly accountFingerprint: string;
  readonly authorization: Authorization;
  readonly invocation: Invocation;
}
export interface AdmissionRecord {
  readonly schemaVersion: typeof SCHEMA_VERSION;
  readonly coreVersion: typeof CORE_VERSION;
  readonly issuedAt: string;
  readonly expiresAt: string;
  readonly declarationSha256: string;
  readonly configSha256: string;
  readonly invocationSha256: string;
  readonly factsSha256: string;
  readonly scopeSha256: string;
  readonly recordSha256: string;
  readonly declaration: Declaration;
  readonly config: ProjectConfig;
  readonly facts: Facts;
  readonly scope: AdmissionScope;
  readonly capabilities: Capabilities;
}
export type Status = "ready" | "blocked" | "unknown";
export interface Response {
  readonly schemaVersion: typeof SCHEMA_VERSION;
  readonly coreVersion: typeof CORE_VERSION;
  readonly status: Status;
  readonly reasons: readonly string[];
  readonly quota: Quota | null;
  readonly admission: AdmissionRecord | null;
  readonly admitted: boolean;
}
export interface BridgeResult {
  readonly schemaVersion: typeof SCHEMA_VERSION;
  readonly coreVersion: typeof CORE_VERSION;
  readonly status: "terminal-receipt-unavailable" | "blocked";
  readonly managedSpawns: 0 | 1;
  readonly providerCalls: 0;
  readonly reasons: readonly string[];
}
export interface ProbeResponse extends Response { readonly probe: BridgeResult | null }
export type Hash = (text: string) => string;
