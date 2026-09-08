import { sql } from "drizzle-orm";
import { index, integer, real, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const candidates = sqliteTable("candidates", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  videoId: text("video_id").notNull(),
  videoUrl: text("video_url").notNull(),
  title: text("title").notNull(),
  channel: text("channel"),
  playerNick: text("player_nick"),
  publishedAt: text("published_at"),
  character: text("character"),
  category: text("category"),
  floor: integer("floor"),
  timeMs: integer("time_ms"),
  confidence: real("confidence").notNull().default(0),
  status: text("status").notNull(),
  rejectionReason: text("rejection_reason"),
  eraKey: text("era_key").notNull().default("current"),
  rawMetadata: text("raw_metadata").notNull().default("{}"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (table) => [
  uniqueIndex("idx_candidates_video_id").on(table.videoId),
  index("idx_candidates_queue").on(table.status, table.character, table.category),
]);

export const rankings = sqliteTable("rankings", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  candidateId: integer("candidate_id").notNull().references(() => candidates.id),
  character: text("character").notNull(),
  category: text("category").notNull(),
  floor: integer("floor").notNull(),
  timeMs: integer("time_ms").notNull(),
  playerNick: text("player_nick").notNull(),
  eraKey: text("era_key").notNull().default("current"),
  approvedAt: text("approved_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (table) => [
  uniqueIndex("idx_rankings_candidate").on(table.candidateId),
  index("idx_rankings_character_time").on(
    table.eraKey, table.category, table.floor, table.character, table.timeMs
  ),
]);
