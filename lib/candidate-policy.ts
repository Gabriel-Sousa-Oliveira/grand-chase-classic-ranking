export type ApprovalCandidate = {
  status?: string | null;
  character?: string | null;
  category?: string | null;
  floor?: number | null;
  time_ms?: number | null;
  confidence?: number | null;
  raw_metadata?: unknown;
};

const TITLE_APPROVAL_CONFIDENCE = 0.95;

/**
 * Automatically approve complete title parses or OCR times backed by consensus
 * from at least two distinct frames.
 */
export function shouldAutoApproveTitle(candidate: ApprovalCandidate): boolean {
  let metadata: Record<string, unknown> = {};
  try {
    const value = typeof candidate.raw_metadata === "string"
      ? JSON.parse(candidate.raw_metadata) : candidate.raw_metadata;
    if (value && typeof value === "object") metadata = value as Record<string, unknown>;
  } catch {
    metadata = {};
  }
  const ocr = metadata.ocr && typeof metadata.ocr === "object"
    ? metadata.ocr as Record<string, unknown> : {};
  const ocrConsensus = metadata.ocr_outcome === "matched"
    && typeof ocr.matching_frames === "number" && ocr.matching_frames >= 2;
  return candidate.status === "ready_for_review"
    && Boolean(candidate.character)
    && Boolean(candidate.category)
    // Some supported categories have no floor and are represented by zero.
    && Number.isInteger(candidate.floor)
    && (candidate.floor ?? -1) >= 0
    && Number.isInteger(candidate.time_ms)
    && (candidate.time_ms ?? 0) > 0
    && typeof candidate.confidence === "number"
    && (candidate.confidence >= TITLE_APPROVAL_CONFIDENCE || ocrConsensus);
}
