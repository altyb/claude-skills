# claude-skills

Claude Code skills. Drop a skill folder into `~/.claude/skills/` to install it, or add this repo
as a plugin marketplace source.

## Skills

- **[solana-wallet-scan](skills/solana-wallet-scan/SKILL.md)** — scan a Solana wallet's trade
  history for copy-trade risk signals (win rate, realized PnL, wallet-farm funding clusters,
  sniper timing).

## Install

```
cp -r skills/solana-wallet-scan ~/.claude/skills/
```

Then in Claude Code, give it a wallet address and ask it to scan/analyze it.
