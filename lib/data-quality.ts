export type QualityIssue =
  | "classification"
  | "time"
  | "ocr_error"
  | "ocr_no_consensus"
  | "duplicate"
  | "outlier"
  | "low_confidence";

export type QualityFilter = "all" | QualityIssue | "risk";

export type QualityCandidate = {
  character: string | null;
  category: string | null;
  floor: number | null;
  time_ms: number | null;
  confidence: number;
  ocr_outcome?: string | null;
  possible_duplicate?: number | boolean;
  benchmark_ms?: number | null;
  benchmark_count?: number | null;
};

export function qualityIssues(candidate: QualityCandidate): QualityIssue[] {
  const issues: QualityIssue[] = [];
  if (!candidate.character || !candidate.category || candidate.floor === null) issues.push("classification");
  if (!candidate.time_ms || candidate.time_ms <= 0) issues.push("time");
  if (candidate.ocr_outcome === "error") issues.push("ocr_error");
  if (candidate.ocr_outcome === "no_consensus") issues.push("ocr_no_consensus");
  if (Boolean(candidate.possible_duplicate)) issues.push("duplicate");
  if (candidate.time_ms && candidate.benchmark_ms && (candidate.benchmark_count ?? 0) >= 3) {
    const ratio = candidate.time_ms / candidate.benchmark_ms;
    if (ratio < 0.55 || ratio > 1.8) issues.push("outlier");
  }
  if (candidate.confidence < 0.8) issues.push("low_confidence");
  return issues;
}

export function matchesQualityFilter(candidate: QualityCandidate, filter: QualityFilter) {
  if (filter === "all") return true;
  const issues = qualityIssues(candidate);
  return filter === "risk"
    ? issues.some(issue => ["duplicate", "outlier", "low_confidence"].includes(issue))
    : issues.includes(filter);
}

export function qualityPriority(candidate: QualityCandidate) {
  const weights: Record<QualityIssue, number> = {
    ocr_error: 70,
    classification: 60,
    time: 50,
    ocr_no_consensus: 40,
    duplicate: 30,
    outlier: 20,
    low_confidence: 10,
  };
  return Math.max(0, ...qualityIssues(candidate).map(issue => weights[issue]));
}
