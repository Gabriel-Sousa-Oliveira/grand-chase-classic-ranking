export type VideoPreview = {
  platform: string;
  watchUrl: string;
  thumbnailUrl: string | null;
};

const youtubeIdPattern = /^[A-Za-z0-9_-]{11}$/;

export function getVideoPreview(value: string): VideoPreview {
  try {
    const url = new URL(value);
    const host = url.hostname.toLocaleLowerCase().replace(/^www\./, "");
    let youtubeId: string | null = null;

    if (host === "youtu.be") youtubeId = url.pathname.split("/").filter(Boolean)[0] ?? null;
    if (host === "youtube.com" || host.endsWith(".youtube.com")) {
      youtubeId = url.searchParams.get("v");
      if (!youtubeId) {
        const [kind, id] = url.pathname.split("/").filter(Boolean);
        if (["embed", "shorts", "live"].includes(kind)) youtubeId = id ?? null;
      }
    }

    if (youtubeId && youtubeIdPattern.test(youtubeId)) {
      return {
        platform: "YouTube",
        watchUrl: value,
        thumbnailUrl: `https://i.ytimg.com/vi/${youtubeId}/hqdefault.jpg`,
      };
    }

    const platform = host.includes("chzzk") ? "CHZZK"
      : host.includes("bilibili") ? "Bilibili"
      : host.includes("sooplive") || host.includes("afreecatv") ? "SOOP"
      : host;
    return {platform, watchUrl: value, thumbnailUrl: null};
  } catch {
    return {platform: "Vídeo", watchUrl: value, thumbnailUrl: null};
  }
}
