export type RankingRow = {
  id: number;
  character: string;
  category: string;
  floor: number;
  time_ms: number;
  player_nick: string;
  era_key: string;
};

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
