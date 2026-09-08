import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  if (!request.headers.get("oai-authenticated-user-id")) {
    return Response.json({ error: "Authentication required" }, { status: 401 });
  }
  const { id } = await context.params;
  const candidateId = Number(id);
  const payload = await request.json() as { approved?: boolean; reason?: string; time_ms?: number };
  if (!Number.isInteger(candidateId)) return Response.json({ error: "Invalid candidate" }, { status: 400 });
  const database = env.DB;
  const candidate = await database.prepare("SELECT * FROM candidates WHERE id = ?").bind(candidateId).first<Record<string, unknown>>();
  if (!candidate) return Response.json({ error: "Candidate not found" }, { status: 404 });
  const timeMs = payload.time_ms ?? candidate.time_ms as number | null;
  if (payload.approved && (!candidate.character || !candidate.category || !candidate.floor || !timeMs)) {
    return Response.json({ error: "Complete character, category, floor and time before approval" }, { status: 400 });
  }
  const status = payload.approved ? "approved" : "rejected";
  const updates = database.prepare(`UPDATE candidates SET status = ?, rejection_reason = ?,
    time_ms = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?`)
    .bind(status, payload.reason ?? null, timeMs, candidateId);
  if (!payload.approved) {
    await updates.run();
  } else {
    const ranking = database.prepare(`INSERT OR REPLACE INTO rankings
      (candidate_id, character, category, floor, time_ms, player_nick, era_key)
      VALUES (?, ?, ?, ?, ?, ?, ?)`)
      .bind(candidateId, candidate.character, candidate.category, candidate.floor,
        timeMs, candidate.player_nick ?? candidate.channel ?? "Desconhecido",
        candidate.era_key ?? "current");
    await database.batch([updates, ranking]);
  }
  return Response.json({ id: candidateId, status });
}
