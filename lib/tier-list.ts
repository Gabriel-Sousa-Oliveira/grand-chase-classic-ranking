import type {RankingRow} from "./ranking";

export type PerformanceTier = "S" | "A" | "B" | "C" | "D";
export type TierEntry = RankingRow & {
  rank: number;
  tier: PerformanceTier;
  gap_percent: number;
};

const tierNames: PerformanceTier[] = ["S", "A", "B", "C", "D"];

export function buildPerformanceTiers(
  rows: RankingRow[], category: string, floor: number, era: string,
) {
  const fastestByCharacter = new Map<string, RankingRow>();
  for (const row of rows) {
    if (row.category !== category || row.floor !== floor || (era !== "all" && row.era_key !== era)) continue;
    const current = fastestByCharacter.get(row.character);
    if (!current || row.time_ms < current.time_ms || (row.time_ms === current.time_ms && row.id < current.id)) {
      fastestByCharacter.set(row.character, row);
    }
  }

  const fastest = [...fastestByCharacter.values()]
    .sort((left, right) => left.time_ms - right.time_ms || left.character.localeCompare(right.character));
  const bestTime = fastest[0]?.time_ms ?? 0;
  const entries: TierEntry[] = fastest.map((row, index) => ({
    ...row,
    rank: index + 1,
    tier: tierNames[Math.min(4, Math.floor(index * 5 / fastest.length))],
    gap_percent: bestTime ? ((row.time_ms - bestTime) / bestTime) * 100 : 0,
  }));

  return {
    entries,
    tiers: tierNames.map(tier => ({tier, entries: entries.filter(entry => entry.tier === tier)})),
    representedCharacters: entries.length,
    coveragePercent: Math.round(entries.length / 25 * 100),
    provisional: entries.length < 15,
  };
}
