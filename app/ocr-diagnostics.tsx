"use client";
import { failureLabel, type FailureSummary } from "@/lib/ocr-diagnostics";
import type { Locale } from "@/lib/i18n";

const labels = {
  pt: { title: "Diagnóstico das falhas de OCR", count: "candidatos ainda sem tempo",
    note: "Última tentativa de cada candidato pendente, incluindo todas as páginas da fila.",
    empty: "Nenhuma falha pendente registrada.", reason: "Motivo", attempts: "Tentativas",
    last: "Última tentativa", version: "Versão do OCR" },
  en: { title: "OCR failure diagnostics", count: "candidates still missing a time",
    note: "Latest attempt per pending candidate, across all queue pages.",
    empty: "No pending failures recorded.", reason: "Reason", attempts: "Attempts",
    last: "Last attempt", version: "OCR version" },
  ko: { title: "OCR 실패 진단", count: "시간이 없는 후보",
    note: "모든 대기열 페이지에서 후보별 마지막 시도입니다.",
    empty: "기록된 대기 실패가 없습니다.", reason: "이유", attempts: "시도 횟수",
    last: "마지막 시도", version: "OCR 버전" },
  th: { title: "การวินิจฉัย OCR ที่ล้มเหลว", count: "รายการที่ยังไม่มีเวลา",
    note: "ความพยายามล่าสุดของแต่ละรายการที่รอดำเนินการจากทุกหน้าคิว",
    empty: "ไม่มีความล้มเหลวที่รอดำเนินการ", reason: "เหตุผล", attempts: "จำนวนครั้ง",
    last: "ความพยายามล่าสุด", version: "เวอร์ชัน OCR" },
};

export function OcrFailurePanel({summary, locale}: {summary: FailureSummary; locale: Locale}) {
  const text = labels[locale];
  return <section className="ocrFailurePanel" aria-label={text.title}>
    <div><h2>{text.title}</h2><strong>{summary.total_failed} {text.count}</strong></div>
    <p>{text.note}</p>
    {summary.total_failed ? <ul>{Object.entries(summary.breakdown).map(([reason, count]) =>
      <li key={reason}><span>{failureLabel(reason,locale)}</span><b>{count}</b></li>)}</ul>
      : <p>{text.empty}</p>}
  </section>;
}

export type OcrDetails = { failure_reason?: string | null; ocr_attempts?: number | null;
  ocr_attempted_at?: string | null; ocr_version?: string | null };
export function OcrAttemptDetails({candidate, locale}: {candidate: OcrDetails; locale: Locale}) {
  if (!candidate.ocr_attempted_at && !candidate.failure_reason) return null;
  const text = labels[locale];
  const timestamp = candidate.ocr_attempted_at ? new Date(candidate.ocr_attempted_at) : null;
  const formatted = timestamp && Number.isFinite(timestamp.valueOf())
    ? new Intl.DateTimeFormat({pt:"pt-BR",en:"en-US",ko:"ko-KR",th:"th-TH"}[locale],
      {dateStyle:"short",timeStyle:"short",timeZone:"America/Sao_Paulo"}).format(timestamp) : "—";
  return <dl className="ocrAttemptDetails">
    {candidate.failure_reason && <><dt>{text.reason}</dt><dd>{failureLabel(candidate.failure_reason,locale)}</dd></>}
    <dt>{text.attempts}</dt><dd>{candidate.ocr_attempts ?? "—"}</dd>
    <dt>{text.last}</dt><dd>{formatted} (UTC−3)</dd>
    <dt>{text.version}</dt><dd>{candidate.ocr_version ?? "—"}</dd>
  </dl>;
}
