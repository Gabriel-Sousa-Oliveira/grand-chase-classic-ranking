const PLAYER_NICK_ALIASES: Record<string, string> = {
  bork: "Borkaz",
};

export function canonicalizePlayerNick(value: string | null | undefined) {
  if (!value) return value;
  return PLAYER_NICK_ALIASES[value.trim().toLocaleLowerCase()] ?? value.trim();
}
