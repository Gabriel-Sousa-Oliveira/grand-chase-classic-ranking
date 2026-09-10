const REPOSITORY = "Gabriel-Sousa-Oliveira/grand-chase-classic-ranking";

export type RunSubmission = {
  videoUrl: string;
  character?: string;
  dungeon?: string;
  notes?: string;
};

export function isYouTubeUrl(value: string) {
  try {
    const url = new URL(value.trim());
    const host = url.hostname.toLowerCase().replace(/^www\./, "");
    if (host === "youtu.be") return url.pathname.length > 1;
    if (host !== "youtube.com" && host !== "m.youtube.com") return false;
    return (url.pathname === "/watch" && Boolean(url.searchParams.get("v")))
      || /^\/(shorts|live)\/[^/]+/.test(url.pathname);
  } catch {
    return false;
  }
}

export function buildGitHubSubmissionUrl(submission: RunSubmission) {
  const videoUrl = submission.videoUrl.trim();
  const character = submission.character?.trim() || "Não informado";
  const dungeon = submission.dungeon?.trim() || "Não informada";
  const notes = submission.notes?.trim() || "Nenhuma";
  const body = [
    "## Envio de run pela comunidade",
    "",
    `- Vídeo: ${videoUrl}`,
    `- Personagem informado: ${character}`,
    `- Dungeon informada: ${dungeon}`,
    "",
    "### Observações",
    notes,
    "",
    "_Criado pelo formulário público do GC Run Radar._",
  ].join("\n");
  const title = `[Run submission] ${character} · ${dungeon}`;
  const params = new URLSearchParams({ title, body, labels: "run-submission" });
  return `https://github.com/${REPOSITORY}/issues/new?${params.toString()}`;
}
