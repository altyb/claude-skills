---
name: solana-wallet-scan
description: Scans a Solana wallet address's on-chain trade history and reports win rate, realized PnL, hold times, and copy-trade risk flags (funding-cluster/wallet-farm pattern, sniper timing, suspiciously high win rate). Use when the user gives a Solana wallet address and asks to scan, analyze, check, or decide whether to copy-trade it.
---

# Solana wallet scan

Run `scripts/scan_wallet.py <WALLET_ADDRESS>` with Bash. It's stdlib-only Python 3, no install step.

```
python3 scripts/scan_wallet.py <WALLET_ADDRESS>
```

It hits Solana RPC directly (public endpoint by default, or `~/.secrets/helius.token` / `$SOLANA_RPC_URL`
if set) and prints a JSON report to stdout with progress on stderr. Scanning ~1000 signatures does
one `getTransaction` call per signature, so it can take a minute or two — that's expected, don't
kill it early.

If it fails with an HTTP 429/403: the public RPC rate-limits or blocks some networks. Point
`SOLANA_RPC_URL` at a real endpoint (Helius free tier is enough) or route through whatever tunnel
the user already has for this (ask them, don't assume).

## Reading the report

- `win_rate` / `realized_pnl_sol` are computed only over **closed** positions (token balance back
  near zero) — open positions aren't counted since PnL isn't realized yet.
- `avg_hold_time_minutes` under a few minutes means you're looking at a bot, not a hand-traded
  signal — you cannot react fast enough to copy it manually, and an automated copy-bot will still
  trail it by at least a block.
- `risk_flags` is the important part — surface these to the user plainly, don't bury them:
  - **funding cluster**: the wallet's first funding transaction came from an address that funded
    several other wallets around the same time. This is the wallet-farm / exit-liquidity setup —
    one "trader" wallet the public follows, several hidden siblings that do the actual dumping.
  - **suspiciously high win rate**: >=90% over 10+ trades is not what organic trading looks like.
    Don't take this as "great trader," take it as "verify before copying."

## After the scan

Don't just paste the JSON back. Give a plain verdict: safe-ish to study / red flags present / not
enough data (few closed trades). If `funder_cluster_check.checked` is false (no funding tx found in
the scanned window), say so explicitly — that's a "raise the --limit" case, not a clean bill of health.

This is a heuristic scan over recent history, not a guarantee — say that too. It approximates
per-token PnL from SOL balance deltas around token balance changes in the same tx; multi-token
swaps in a single tx can blur the split between them.
