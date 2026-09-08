CREATE TABLE `candidates` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`video_id` text NOT NULL,
	`video_url` text NOT NULL,
	`title` text NOT NULL,
	`channel` text,
	`player_nick` text,
	`published_at` text,
	`character` text,
	`category` text,
	`floor` integer,
	`time_ms` integer,
	`confidence` real DEFAULT 0 NOT NULL,
	`status` text NOT NULL,
	`rejection_reason` text,
	`era_key` text DEFAULT 'current' NOT NULL,
	`raw_metadata` text DEFAULT '{}' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_candidates_video_id` ON `candidates` (`video_id`);--> statement-breakpoint
CREATE INDEX `idx_candidates_queue` ON `candidates` (`status`,`character`,`category`);--> statement-breakpoint
CREATE TABLE `rankings` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`candidate_id` integer NOT NULL,
	`character` text NOT NULL,
	`category` text NOT NULL,
	`floor` integer NOT NULL,
	`time_ms` integer NOT NULL,
	`player_nick` text NOT NULL,
	`era_key` text DEFAULT 'current' NOT NULL,
	`approved_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`candidate_id`) REFERENCES `candidates`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_rankings_candidate` ON `rankings` (`candidate_id`);--> statement-breakpoint
CREATE INDEX `idx_rankings_character_time` ON `rankings` (`era_key`,`category`,`floor`,`character`,`time_ms`);--> statement-breakpoint
PRAGMA optimize;
