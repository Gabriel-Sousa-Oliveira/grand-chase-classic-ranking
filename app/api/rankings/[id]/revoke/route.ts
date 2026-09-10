import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  if (!request.headers.get("oai-authenticated-user-id")) {
    return Response.json({ error: "Authentication required" }, { status: 401 });
  }
  const { id } = await context.params;
  const rankingId = Number(id);
  if (!Number.isInteger(rankingId)) return Response.json({ error: "Invalid ranking" }, { status: 400 });

  const database = env.DB;
  const ranking = await database.prepare("SELECT candidate_id FROM rankings WHERE id = ?")
    .bind(rankingId).first<{ candidate_id: number }>();
  if (!ranking) return Response.json({ error: "Ranking not found" }, { status: 404 });

  await database.batch([
    database.prepare("DELETE FROM rankings WHERE id = ?").bind(rankingId),
    database.prepare(`UPDATE candidates SET status = 'rejected',
      rejection_reason = 'Approval revoked by administrator', updated_at = CURRENT_TIMESTAMP
      WHERE id = ?`).bind(ranking.candidate_id),
  ]);
  return Response.json({ id: rankingId, status: "rejected" });
}
