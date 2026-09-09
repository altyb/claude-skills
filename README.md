# claude-skills

Claude Code skills. Drop a skill folder into `~/.claude/skills/` to install it, or add this repo
as a plugin marketplace source.

## Skills

- **[solana-wallet-scan](skills/solana-wallet-scan/SKILL.md)** — scan a Solana wallet's trade
  history for copy-trade risk signals (win rate, realized PnL, wallet-farm funding clusters,
  sniper timing).
- **[solana-token2022-forensics](skills/solana-token2022-forensics/SKILL.md)** — independently
  verify a token's mint/freeze authorities and Token-2022 extensions (permanentDelegate,
  transferHook, nonTransferable) directly on-chain, catching fraud vectors that API-based
  rug-checkers don't ask about.

## Install

```
cp -r skills/solana-wallet-scan ~/.claude/skills/
cp -r skills/solana-token2022-forensics ~/.claude/skills/
```

Then in Claude Code, give it a wallet address and ask it to scan/analyze it.
