import { compareSnapshots, isSuccessfulProof } from "../core/index.ts";
import type { Applicability, Receipt, Snapshot } from "../core/index.ts";
import { captureSnapshot, loadConfiguration, resolveRepository } from "./scope.ts";

export interface ReceiptProjection {
  executionId: string;
  status: Receipt["result"]["status"];
  applicability: Applicability;
  proof: boolean;
  output: Pick<Receipt["artifact"], "sha256" | "capturedBytes" | "totalBytes" | "truncated">;
}

export interface EvidenceScope {
  repositoryRoot: string;
  configPath: string;
}

export async function projectReceipt(receipt: Receipt, scope: EvidenceScope, key: Uint8Array): Promise<ReceiptProjection> {
  let current: Snapshot | null = null;
  try {
    const repository = await resolveRepository(scope.repositoryRoot);
    const config = await loadConfiguration(repository.worktreeRoot, scope.configPath);
    if (repository.repositoryId === receipt.plan.repository.repositoryId
      && repository.worktreeId === receipt.plan.repository.worktreeId
      && config.configPath === receipt.plan.configPath) {
      current = await captureSnapshot(repository.worktreeRoot, receipt.plan.gate.scope, config.configPath, key);
    }
  } catch { /* Historical applicability must not substitute for a current observation. */ }
  const applicability = receipt.applicability === "unknown" ? "unknown" : compareSnapshots(receipt.plan.before, current);
  return {
    executionId: receipt.plan.executionId, status: receipt.result.status, applicability,
    proof: isSuccessfulProof(receipt, current),
    output: { sha256: receipt.artifact.sha256, capturedBytes: receipt.artifact.capturedBytes, totalBytes: receipt.artifact.totalBytes, truncated: receipt.artifact.truncated },
  };
}
