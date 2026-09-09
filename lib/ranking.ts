export type RankingRow = {
  id: number;
  character: string;
  category: string;
  floor: number;
  time_ms: number;
  player_nick: string;
  era_key: string;
  video_url?: string | null;
  channel?: string | null;
  published_at?: string | null;
  approved_at?: string | null;
};

export type RecordEvent = RankingRow & {
  previous_time_ms: number | null;
  improvement_ms: number | null;
  event_at: string | null;
};

export function buildRecordProgression(
  rows: RankingRow[], category: string, floor: number, character: string, era: string,
): RecordEvent[] {
  const eligible = rows
    .filter(row => row.category === category && row.floor === floor
      && (character === "all" || row.character === character)
      && (era === "all" || row.era_key === era))
    .sort((left, right) => {
      const leftDate = left.published_at ?? left.approved_at ?? "9999";
      const rightDate = right.published_at ?? right.approved_at ?? "9999";
      return leftDate.localeCompare(rightDate) || left.id - right.id;
    });
  const bestByCharacter = new Map<string, number>();
  const events: RecordEvent[] = [];
  for (const row of eligible) {
    const previous = bestByCharacter.get(row.character) ?? null;
    if (previous === null || row.time_ms < previous) {
      events.push({
        ...row,
        previous_time_ms: previous,
        improvement_ms: previous === null ? null : previous - row.time_ms,
        event_at: row.published_at ?? row.approved_at ?? null,
      });
      bestByCharacter.set(row.character, row.time_ms);
    }
  }
  return events.sort((left, right) => {
    const leftDate = left.event_at ?? "9999";
    const rightDate = right.event_at ?? "9999";
    return rightDate.localeCompare(leftDate) || right.id - left.id;
  });
}

export function topRankingsByCharacter(
  rows: RankingRow[],
  category: string,
  floor: number,
  era: string,
  limit = 4,
) {
  const grouped = new Map<string, { character: string; runs: RankingRow[]; nicks: Set<string> }>();
  const eligible = rows
    .filter(row => row.category === category && row.floor === floor
      && (era === "all" || row.era_key === era))
    .sort((left, right) => left.time_ms - right.time_ms || left.id - right.id);

  for (const row of eligible) {
    const group = grouped.get(row.character) ?? {
      character: row.character,
      runs: [],
      nicks: new Set<string>(),
    };
    const normalizedNick = row.player_nick.trim().toLocaleLowerCase();
    if (group.runs.length < limit && !group.nicks.has(normalizedNick)) {
      group.runs.push(row);
      group.nicks.add(normalizedNick);
    }
    grouped.set(row.character, group);
  }

  return [...grouped.values()]
    .sort((left, right) => left.character.localeCompare(right.character, "pt-BR"))
    .map(({ character, runs }) => ({ character, runs }));
}
