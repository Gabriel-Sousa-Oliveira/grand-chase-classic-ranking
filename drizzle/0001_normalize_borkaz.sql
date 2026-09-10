UPDATE `candidates`
SET `player_nick` = 'Borkaz', `updated_at` = CURRENT_TIMESTAMP
WHERE lower(trim(`player_nick`)) = 'bork';
--> statement-breakpoint
UPDATE `rankings`
SET `player_nick` = 'Borkaz'
WHERE lower(trim(`player_nick`)) = 'bork';
