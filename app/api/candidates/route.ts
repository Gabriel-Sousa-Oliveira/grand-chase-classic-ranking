import { env } from "cloudflare:workers";
import { shouldAutoApproveTitle } from "@/lib/candidate-policy";
import { canonicalizePlayerNick } from "@/lib/player-nick";

import { mergeMetadataSql, failureAggregationSql } from "@/lib/ocr-diagnostics";

export const dynamic = "force-dynamic";

type IncomingCandidate = {
  video_id?: string; video_url?: string; title?: string; channel?: string | null;
  player_nick?: string | null; published_at?: string | null; character?: string | null;
  category?: string | null; floor?: number | null; time_ms?: number | null;
  confidence?: number; status?: string; era_key?: string; raw_metadata?: unknown;
};

function db() {
  if (!env.DB) throw new Error("Database unavailable");
  return env.DB;
}

async function backfillApprovedTitles() {
  const database = db();
  const eligible = `status = 'ready_for_review'
    AND character IS NOT NULL AND category IS NOT NULL
    AND floor IS NOT NULL AND floor >= 0
    AND time_ms IS NOT NULL AND time_ms > 0
    AND confidence >= 0.95`;
  await database.batch([
    database.prepare(`UPDATE candidates SET status = 'approved',
      updated_at = CURRENT_TIMESTAMP WHERE ${eligible}`),
    database.prepare(`INSERT OR IGNORE INTO rankings
      (candidate_id, character, category, floor, time_ms, player_nick, era_key)
      SELECT id, character, category, floor, time_ms,
        COALESCE(player_nick, channel, 'Desconhecido'), era_key
      FROM candidates WHERE status = 'approved'
        AND character IS NOT NULL AND category IS NOT NULL
        AND floor IS NOT NULL AND floor >= 0
        AND time_ms IS NOT NULL AND time_ms > 0
        AND confidence >= 0.95`),
  ]);
}

export async function GET() {
  try {
    await backfillApprovedTitles();
    const [queue, rankings, history, processing, failures] = await Promise.all([
      db().prepare(`SELECT c.id, c.video_id, c.video_url, c.title, c.channel, c.player_nick,
        c.published_at, c.created_at, c.character, c.category, c.floor, c.time_ms,
        c.confidence, c.status, c.era_key,
        json_extract(c.raw_metadata, '$.ocr_outcome') AS ocr_outcome,
        json_extract(c.raw_metadata, '$.ocr_time_ms') AS ocr_time_ms,
        json_extract(c.raw_metadata, '$.ocr_confidence') AS ocr_confidence,
        json_extract(c.raw_metadata, '$.evidence_frame') AS evidence_frame,
        json_extract(c.raw_metadata, '$.evidence_seconds_from_end') AS evidence_seconds_from_end,
        json_extract(c.raw_metadata, '$.evidence_image') AS evidence_image,
        json_extract(c.raw_metadata, '$.ocr_roi') AS ocr_roi,
        json_extract(c.raw_metadata, '$.processing_reason') AS processing_reason,
        COALESCE(json_extract(c.raw_metadata, '$.failure_reason'),
          CASE json_extract(c.raw_metadata, '$.ocr_outcome')
            WHEN 'error' THEN 'technical_error'
            WHEN 'no_consensus' THEN 'timer_not_frozen_or_not_readable' END) AS failure_reason,
        json_extract(c.raw_metadata, '$.ocr_attempted_at') AS ocr_attempted_at,
        json_extract(c.raw_metadata, '$.ocr_attempts') AS ocr_attempts,
        json_extract(c.raw_metadata, '$.ocr_version') AS ocr_version,
        json_extract(c.raw_metadata, '$.ocr_diagnostics') AS ocr_diagnostics,
        json_extract(c.raw_metadata, '$.evidence_seconds') AS evidence_seconds,
        EXISTS(SELECT 1 FROM candidates duplicate
          WHERE duplicate.id <> c.id AND c.time_ms IS NOT NULL
            AND duplicate.time_ms = c.time_ms
            AND duplicate.character = c.character
            AND duplicate.category = c.category
            AND duplicate.floor = c.floor
            AND lower(COALESCE(duplicate.player_nick, duplicate.channel, '')) =
              lower(COALESCE(c.player_nick, c.channel, ''))
        ) AS possible_duplicate,
        benchmark.avg_time AS benchmark_ms,
        benchmark.sample_size AS benchmark_count
        FROM candidates c
        LEFT JOIN (
          SELECT character, category, floor, AVG(time_ms) AS avg_time,
            COUNT(*) AS sample_size
          FROM rankings GROUP BY character, category, floor
        ) benchmark ON benchmark.character = c.character
          AND benchmark.category = c.category AND benchmark.floor = c.floor
        WHERE c.status IN ('ready_for_review','time_required','classification_required')
          AND COALESCE(json_extract(c.raw_metadata, '$.ocr_outcome'), '') != 'matched'
        ORDER BY c.confidence DESC, c.created_at ASC LIMIT 500`).all(),
      db().prepare(`SELECT id, character, category, floor, time_ms,
        player_nick, era_key, video_url, channel, published_at, approved_at FROM (
          SELECT r.id, r.character, r.category, r.floor, r.time_ms,
            r.player_nick, r.era_key, c.video_url, c.channel, c.published_at, r.approved_at,
            ROW_NUMBER() OVER (
              PARTITION BY r.era_key, r.category, r.floor, r.character, r.player_nick
              ORDER BY r.time_ms ASC, r.approved_at ASC, r.id ASC
            ) AS nick_position
          FROM rankings r JOIN candidates c ON c.id = r.candidate_id
        ) WHERE nick_position = 1
        ORDER BY category, floor, character, time_ms ASC, era_key DESC`).all(),
      db().prepare(`SELECT r.id, r.character, r.category, r.floor, r.time_ms,
        r.player_nick, r.era_key, c.video_url, c.channel, c.published_at, r.approved_at
        FROM rankings r JOIN candidates c ON c.id = r.candidate_id
        ORDER BY COALESCE(c.published_at, r.approved_at) ASC, r.id ASC`).all(),
      db().prepare(`SELECT
        COUNT(*) AS discovered,
        COALESCE(SUM(CASE WHEN character IS NOT NULL AND category IS NOT NULL
          AND floor IS NOT NULL THEN 1 ELSE 0 END), 0) AS classified,
        COALESCE(SUM(CASE WHEN character IS NOT NULL AND category IS NOT NULL
          AND floor IS NOT NULL AND time_ms IS NOT NULL AND time_ms > 0
          THEN 1 ELSE 0 END), 0) AS timed,
        COALESCE(SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END), 0) AS approved,
        (SELECT COUNT(*) FROM rankings) AS ranked,
        COALESCE(SUM(CASE WHEN status IN
          ('ready_for_review','time_required','classification_required')
          THEN 1 ELSE 0 END), 0) AS pending_manual,
        COALESCE(SUM(CASE WHEN COALESCE(json_extract(raw_metadata, '$.ocr_outcome'), '')
          <> '' THEN 1 ELSE 0 END), 0) AS ocr_attempted,
        COALESCE(SUM(CASE WHEN json_extract(raw_metadata, '$.ocr_outcome') = 'matched'
          THEN 1 ELSE 0 END), 0) AS ocr_matched,
        COALESCE(SUM(CASE WHEN json_extract(raw_metadata, '$.ocr_outcome')
          IN ('no_consensus','error') THEN 1 ELSE 0 END), 0) AS ocr_unresolved,
        COALESCE(SUM(CASE WHEN time_ms IS NOT NULL
          AND COALESCE(json_extract(raw_metadata, '$.ocr_outcome'), '') <> 'matched'
          AND confidence >= 0.95 THEN 1 ELSE 0 END), 0) AS title_times,
        COALESCE(SUM(CASE WHEN time_ms IS NOT NULL
          AND COALESCE(json_extract(raw_metadata, '$.ocr_outcome'), '') <> 'matched'
          AND confidence < 0.95 THEN 1 ELSE 0 END), 0) AS human_times,
        MAX(updated_at) AS last_updated
        FROM candidates`).first(),
      db().prepare(failureAggregationSql).all<{ reason: string; count: number }>(),
    ]);
    return Response.json({
      candidates: queue.results,
      rankings: rankings.results,
      history: history.results,
      processing,
      ocr_failures: {
        total_failed: failures.results.reduce((sum, row) => sum + row.count, 0),
        breakdown: Object.fromEntries(failures.results.map(row => [row.reason, row.count])),
      },
    });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Database error" }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const expected = (env as unknown as { INGEST_API_TOKEN?: string }).INGEST_API_TOKEN;
  const supplied = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  if (!expected || supplied !== expected) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  const payload = await request.json() as { candidates?: IncomingCandidate[] };
  const items = Array.isArray(payload.candidates) ? payload.candidates.slice(0, 500) : [];
  let inserted = 0;
  let updated = 0;
  let autoApproved = 0;
  for (const item of items) {
    if (!item.video_id || !item.video_url || !item.title || !item.status) continue;
    const playerNick = canonicalizePlayerNick(item.player_nick ?? item.channel) ?? null;
    const autoApprove = item.status === "ready_for_review" && shouldAutoApproveTitle(item);
    const effectiveStatus = autoApprove ? "approved" : item.status;
    let metadata: unknown;
    try { metadata = typeof item.raw_metadata === "string"
      ? JSON.parse(item.raw_metadata) : item.raw_metadata ?? {}; }
    catch { continue; }
    if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) continue;
    const rawMetadata = JSON.stringify(metadata);
    const result = await db().prepare(`INSERT OR IGNORE INTO candidates
      (video_id, video_url, title, channel, player_nick, published_at, character,
       category, floor, time_ms, confidence, status, era_key, raw_metadata)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(item.video_id, item.video_url, item.title, item.channel ?? null,
        playerNick, item.published_at ?? null,
        item.character ?? null, item.category ?? null, item.floor ?? null,
        item.time_ms ?? null, item.confidence ?? 0, effectiveStatus,
        item.era_key ?? "current", rawMetadata).run();
    if ((result.meta.changes ?? 0) > 0) {
      inserted += 1;
    } else {
      const update = await db().prepare(`UPDATE candidates SET
          video_url = ?, title = ?, channel = COALESCE(?, channel),
          player_nick = COALESCE(?, player_nick), published_at = COALESCE(?, published_at),
          character = ?, category = ?, floor = ?, time_ms = ?, confidence = ?, status = ?,
          raw_metadata = CASE
            WHEN (character IS NOT NULL AND character IS NOT ?)
              OR (category IS NOT NULL AND category IS NOT ?)
              OR (floor IS NOT NULL AND floor IS NOT ?)
              OR era_key IS NOT ? THEN ?
            ELSE ${mergeMetadataSql} END,
          updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
          AND status IN ('ready_for_review','time_required','classification_required')`)
        .bind(item.video_url, item.title, item.channel ?? null,
          playerNick, item.published_at ?? null,
          item.character ?? null, item.category ?? null, item.floor ?? null,
          item.time_ms ?? null, item.confidence ?? 0, effectiveStatus,
          item.character ?? null, item.category ?? null, item.floor ?? null,
          item.era_key ?? "current", rawMetadata,
          rawMetadata, rawMetadata, rawMetadata, rawMetadata, item.video_id).run();
      updated += update.meta.changes ?? 0;
    }
    if (autoApprove) {
      const ranking = await db().prepare(`INSERT OR IGNORE INTO rankings
        (candidate_id, character, category, floor, time_ms, player_nick, era_key)
        SELECT id, character, category, floor, time_ms,
          COALESCE(player_nick, channel, 'Desconhecido'), era_key
        FROM candidates
        WHERE video_id = ? AND status = 'approved'
          AND character IS NOT NULL AND category IS NOT NULL
          AND floor IS NOT NULL AND time_ms IS NOT NULL`).bind(item.video_id).run();
      autoApproved += ranking.meta.changes ?? 0;
    }
  }
  return Response.json({ received: items.length, inserted, updated, auto_approved: autoApproved });
}
