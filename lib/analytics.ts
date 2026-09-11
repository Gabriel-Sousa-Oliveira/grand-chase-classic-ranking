import {topRankingsByCharacter, type RankingRow} from "./ranking.ts";

export type DungeonDefinition = {
  key: string;
  category: string;
  floor: number;
  label: string;
};

export type ProcessingMetrics = {
  discovered: number;
  classified: number;
  timed: number;
  approved: number;
  ranked: number;
  pending_manual: number;
  ocr_attempted: number;
  ocr_matched: number;
  ocr_unresolved: number;
  title_times: number;
  human_times: number;
  last_updated: string | null;
};

export function processingRate(value: number, total: number) {
  return total > 0 ? Math.round((value / total) * 100) : 0;
}

export const gameCharacters = [
  "Elesis", "Lire", "Arme", "Lass", "Ryan", "Ronan", "Amy", "Jin",
  "Sieghart", "Mari", "Dio", "Zero", "Ley/Rey", "Rufus/Lupus", "Rin/Lin",
  "Asin", "Lime/Holy", "Edel", "Veigas", "Uno", "Decanee", "Kallia", "Ai",
  "Iris", "Ereb",
] as const;

export function buildAnalytics(rows: RankingRow[], dungeons: DungeonDefinition[], era: string) {
  const selectedRows = rows.filter(row => era === "all" || row.era_key === era);
  const boards = dungeons.map(dungeon => {
    const groups = topRankingsByCharacter(rows, dungeon.category, dungeon.floor, era);
    const byCharacter = new Map(groups.map(group => [group.character, group.runs.length]));
    const filledSlots = groups.reduce((total, group) => total + group.runs.length, 0);
    return {
      ...dungeon,
      byCharacter,
      filledSlots,
      representedCharacters: groups.length,
      coveragePercent: Math.round((filledSlots / (gameCharacters.length * 4)) * 100),
    };
  });
  const representedCharacters = new Set(selectedRows.map(row => row.character));
  const uniquePlayers = new Set(selectedRows.map(row => row.player_nick.trim().toLocaleLowerCase()));
  const totalFilledSlots = boards.reduce((total, board) => total + board.filledSlots, 0);

  return {
    verifiedRuns: selectedRows.length,
    representedCharacters: representedCharacters.size,
    uniquePlayers: uniquePlayers.size,
    activeDungeons: boards.filter(board => board.filledSlots > 0).length,
    totalFilledSlots,
    totalSlots: dungeons.length * gameCharacters.length * 4,
    overallCoveragePercent: Math.round((totalFilledSlots / (dungeons.length * gameCharacters.length * 4)) * 100),
    boards,
  };
}
