export type ApprovalCandidate = {
  status?: string | null;
  character?: string | null;
  category?: string | null;
  floor?: number | null;
  time_ms?: number | null;
  confidence?: number | null;
};

const TITLE_APPROVAL_CONFIDENCE = 0.95;

/**
 * Automatically approve only complete, high-confidence title parses.
 * OCR tops out below this threshold, so video-derived times remain manual.
 */
export function shouldAutoApproveTitle(candidate: ApprovalCandidate): boolean {
  return candidate.status === "ready_for_review"
    && Boolean(candidate.character)
    && Boolean(candidate.category)
    // Some supported categories have no floor and are represented by zero.
    && Number.isInteger(candidate.floor)
    && (candidate.floor ?? -1) >= 0
    && Number.isInteger(candidate.time_ms)
    && (candidate.time_ms ?? 0) > 0
    && typeof candidate.confidence === "number"
    && candidate.confidence >= TITLE_APPROVAL_CONFIDENCE;
}
