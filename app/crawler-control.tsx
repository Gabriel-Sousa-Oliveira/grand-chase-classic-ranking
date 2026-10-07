"use client";

import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { CRAWLER_LOOKBACK_DAYS, type CrawlerLookbackDays } from "@/lib/crawler-control";
import { translator, type MessageKey } from "@/lib/i18n";
import "./crawler-control.css";

type T = ReturnType<typeof translator>;
type Run = {
  id: number;
  status: "queued" | "in_progress" | "completed";
  conclusion: string | null;
  url: string;
  created_at: string;
};
type CrawlReport = {
  channels_expanded?: number;
  discovered_unique?: number;
  duplicates?: number;
  ignored?: number;
  created?: number;
};

async function responseBody(response: Response): Promise<{ error?: string; run?: Run | null; report?: CrawlReport | null; retry_after_seconds?: number }> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return await response.json() as { error?: string; run?: Run | null; retry_after_seconds?: number };
  }
  const text = await response.text();
  const summary = text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 160);
  return { error: `Crawler API returned HTTP ${response.status}${summary ? `: ${summary}` : ""}` };
}

export function CrawlerControl({ t }: { t: T }) {
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState<CrawlerLookbackDays>(3);
  const [run, setRun] = useState<Run | null>(null);
  const [report, setReport] = useState<CrawlReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refreshStatus = async () => {
    try {
      const response = await fetch("/api/crawler", { cache: "no-store" });
      const body = await responseBody(response);
      if (!response.ok) throw new Error(body.error ?? t("crawlerStatusError"));
      setRun(body.run ?? null);
      setReport(body.report ?? null);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("crawlerStatusError"));
    }
  };

  useEffect(() => {
    if (!open) return;
    void refreshStatus();
  }, [open]);

  useEffect(() => {
    if (!open || (run?.status !== "queued" && run?.status !== "in_progress")) return;
    const timer = window.setInterval(() => void refreshStatus(), 12000);
    return () => window.clearInterval(timer);
  }, [open, run?.status]);

  const start = async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/crawler", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days }),
      });
      const body = await responseBody(response);
      if (!response.ok) {
        if (body.run) setRun(body.run);
        if (response.status === 429 && body.retry_after_seconds) {
          throw new Error(t("crawlerCooldown", { minutes: Math.ceil(body.retry_after_seconds / 60) }));
        }
        throw new Error(body.error ?? t("crawlerStartError"));
      }
      setRun(current => current ? { ...current, status: "queued", conclusion: null } : null);
      window.setTimeout(() => void refreshStatus(), 2500);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("crawlerStartError"));
    } finally {
      setLoading(false);
    }
  };

  const statusKey: MessageKey = run?.status === "queued"
    ? "crawlerQueued"
    : run?.status === "in_progress"
      ? "crawlerRunning"
      : run?.conclusion === "success"
        ? "crawlerSucceeded"
        : run
          ? "crawlerFailed"
          : "crawlerNeverRun";
  const active = run?.status === "queued" || run?.status === "in_progress";

  return <>
    <button className="crawlerOpenButton" type="button" onClick={() => setOpen(true)}>⌁ {t("searchVideos")}</button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="crawlerDialog">
        <DialogHeader>
          <span className="crawlerEyebrow">{t("crawlerControl")}</span>
          <DialogTitle>{t("searchVideos")}</DialogTitle>
          <DialogDescription>{t("crawlerDescription")}</DialogDescription>
        </DialogHeader>
        <label className="crawlerPeriod">{t("crawlerPeriod")}
          <select value={days} onChange={event => setDays(Number(event.target.value) as CrawlerLookbackDays)}>
            {CRAWLER_LOOKBACK_DAYS.map(value => <option value={value} key={value}>{t("crawlerDays", { count: value })}</option>)}
          </select>
        </label>
        <section className={`crawlerStatus ${active ? "active" : ""}`} aria-live="polite">
          <i aria-hidden="true" />
          <div><small>{t("crawlerLatestRun")}</small><b>{t(statusKey)}</b>{run?.created_at && <span>{new Date(run.created_at).toLocaleString()}</span>}</div>
          {run?.url && <a href={run.url} target="_blank" rel="noreferrer">{t("crawlerDetails")} ↗</a>}
        </section>
        {report && <section className="crawlerFunnel" aria-label="Resultado da última busca">
          <div><b>{report.discovered_unique ?? 0}</b><span>Encontrados</span></div>
          <div><b>{report.channels_expanded ?? 0}</b><span>Canais</span></div>
          <div><b>{report.duplicates ?? 0}</b><span>Duplicados</span></div>
          <div><b>{report.ignored ?? 0}</b><span>Ignorados</span></div>
          <div><b>{report.created ?? 0}</b><span>Novos</span></div>
        </section>}
        {error && <p className="crawlerError">{error}</p>}
        <div className="crawlerActions">
          <button type="button" className="crawlerSecondary" onClick={() => void refreshStatus()} disabled={loading}>{t("refresh")}</button>
          <button type="button" className="crawlerStart" onClick={() => void start()} disabled={loading || active}>{loading ? t("crawlerStarting") : active ? t("crawlerAlreadyRunning") : t("crawlerStart")}</button>
        </div>
        <p className="crawlerNote">{t("crawlerLimitNote")}</p>
      </DialogContent>
    </Dialog>
  </>;
}
