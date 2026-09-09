---
name: solana-wallet-scan
description: Scans a Solana wallet address's on-chain trade history and reports win rate, realized PnL, hold times, and copy-trade risk flags (funding-cluster/wallet-farm pattern, sniper timing, suspiciously high win rate, creator snipe-and-dump on its own token launches). Use when the user gives a Solana wallet address and asks to scan, analyze, check, or decide whether to copy-trade it.
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

## Second script: creator snipe-and-dump check

A wallet's aggregate win rate can look genuinely good (high win rate, no reliance on lucky
outliers) while hiding a specific inflating pattern: it creates its own tokens, buys its own
launch in the first second (an entry no outsider gets), and dumps within minutes before the
token dies. That's not trading skill, it's creator advantage, and it counts toward the same win
rate number a copy-trade decision would rely on. **Measured live**: a wallet screened as a strong
59% win-rate candidate turned out to have created 84 tokens, all now dead, with 93% of a sampled
batch showing a self-buy-to-self-sell gap under 5 minutes — fastest one was 5 seconds.

```
python3 scripts/check_creator_dump.py <WALLET_ADDRESS> [--chain sol] [--dump-seconds 300] [--sample 20]
```

Pulls every token the wallet created (`gmgn-cli portfolio created-tokens`), then for a sample of
them checks that same wallet's own first-buy-to-first-sell gap on its own launch
(`gmgn-cli portfolio activity --token <addr>`). Reports what fraction come back inside the dump
window (default 5 minutes) and flags the wallet if it's 30%+.

**Run this whenever `portfolio stats`/`common.created_token_count` on the main scan shows any
non-zero created-token count before trusting that wallet's win rate.** A wallet that created zero
tokens can't have this problem — this check only applies when there's something to check.
Rate-paced (1.5s between token checks) and retries through GMGN's holder/activity rate limit the
same way the concentration checker in the token2022-forensics skill does.
