/** Shared persisted contract. Unknown legacy failures stay explicitly generic. */
export const failureReasons = [
  "results_screen_not_found", "timer_not_found", "conflicting_reads",
  "insufficient_stable_frames", "not_supported_layout", "download_error",
  "technical_error", "diagnostic_unavailable", "timer_not_frozen_or_not_readable",
] as const;
export type FailureReason = typeof failureReasons[number];
export type FailureSummary = { total_failed: number; breakdown: Record<string, number> };

export const pendingStatuses = "('ready_for_review','time_required','classification_required')";
const ocrKeys = ["ocr_outcome", "ocr_attempted_at", "ocr_attempts", "ocr_history",
  "failure_reason", "ocr_version", "ocr_diagnostics", "ocr_time_ms", "ocr_confidence",
  "ocr", "evidence_frame", "evidence_seconds_from_end", "evidence_seconds",
  "evidence_image", "ocr_roi", "processing_reason"];

// Four incoming-JSON bindings. A crawler refresh still updates ordinary
// metadata, but older/absent OCR timestamps cannot erase newer OCR diagnostics.
export const mergeMetadataSql = `json_set(json_patch(
  CASE WHEN json_valid(raw_metadata) THEN raw_metadata ELSE '{}' END,
  CASE WHEN json_extract(raw_metadata, '$.ocr_attempted_at') IS NOT NULL
    AND COALESCE(json_extract(?, '$.ocr_attempted_at'), '') <=
        json_extract(raw_metadata, '$.ocr_attempted_at')
    THEN json_remove(?, ${ocrKeys.map(key => `'$.${key}'`).join(', ')})
    ELSE ? END
), '$.ocr_attempts', MAX(
  COALESCE(CAST(json_extract(raw_metadata, '$.ocr_attempts') AS INTEGER), 0),
  COALESCE(CAST(json_extract(?, '$.ocr_attempts') AS INTEGER), 0)
))`;

export const failureAggregationSql = `SELECT
  COALESCE(NULLIF(json_extract(raw_metadata, '$.failure_reason'), ''),
    CASE WHEN json_extract(raw_metadata, '$.ocr_outcome') = 'error'
      THEN 'technical_error' ELSE 'timer_not_frozen_or_not_readable' END) AS reason,
  COUNT(*) AS count
  FROM candidates WHERE status IN ${pendingStatuses}
    AND time_ms IS NULL
    AND json_extract(raw_metadata, '$.ocr_outcome') IN ('no_consensus','error')
  GROUP BY reason ORDER BY count DESC, reason`;

export const outcomeUpdateSql = `UPDATE candidates SET raw_metadata =
  json_set(json_patch(CASE WHEN json_valid(raw_metadata) THEN raw_metadata ELSE '{}' END,
    json(?)), '$.ocr_attempts', MAX(
      COALESCE(CAST(json_extract(raw_metadata, '$.ocr_attempts') AS INTEGER), 0), ?)),
    updated_at = CURRENT_TIMESTAMP
  WHERE video_id = ? AND status IN ${pendingStatuses}
    AND COALESCE(json_extract(raw_metadata, '$.ocr_attempted_at'), '') <= ?`;

export const failureLabels: Record<string, Record<string, string>> = {
  ko: { results_screen_not_found: "결과 화면을 인식하지 못함", timer_not_found: "시간을 읽지 못함",
    conflicting_reads: "서로 다른 판독값", insufficient_stable_frames: "안정된 프레임 부족",
    not_supported_layout: "지원되지 않는 화면", download_error: "다운로드 실패",
    technical_error: "기술 오류", diagnostic_unavailable: "진단 정보 없음",
    timer_not_frozen_or_not_readable: "상세 진단이 없는 이전 실패" },
  th: { results_screen_not_found: "ไม่พบหน้าผลลัพธ์", timer_not_found: "อ่านเวลาไม่ได้",
    conflicting_reads: "อ่านค่าไม่ตรงกัน", insufficient_stable_frames: "เฟรมที่คงที่ไม่เพียงพอ",
    not_supported_layout: "ไม่รองรับรูปแบบหน้าจอ", download_error: "ดาวน์โหลดล้มเหลว",
    technical_error: "ข้อผิดพลาดทางเทคนิค", diagnostic_unavailable: "ไม่มีข้อมูลวินิจฉัย",
    timer_not_frozen_or_not_readable: "ความล้มเหลวเดิมที่ไม่มีรายละเอียด" },
  pt: { results_screen_not_found: "Placar não reconhecido", timer_not_found: "Tempo não lido",
    conflicting_reads: "Leituras divergentes", insufficient_stable_frames: "Poucos frames estáveis",
    not_supported_layout: "Layout não suportado", download_error: "Falha no download",
    technical_error: "Erro técnico", diagnostic_unavailable: "Diagnóstico indisponível",
    timer_not_frozen_or_not_readable: "Falha antiga sem diagnóstico detalhado" },
  en: { results_screen_not_found: "Results panel not recognized", timer_not_found: "Timer not read",
    conflicting_reads: "Conflicting readings", insufficient_stable_frames: "Too few stable frames",
    not_supported_layout: "Unsupported layout", download_error: "Download failed",
    technical_error: "Technical error", diagnostic_unavailable: "Diagnostics unavailable",
    timer_not_frozen_or_not_readable: "Legacy failure without detailed diagnostics" },
};
export function failureLabel(reason: string, locale: string) {
  return (failureLabels[locale] ?? failureLabels.en)[reason] ?? reason;
}
