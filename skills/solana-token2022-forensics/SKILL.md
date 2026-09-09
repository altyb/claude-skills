---
name: solana-token2022-forensics
description: Independently verifies a Solana token's mint/freeze authorities and scans for dangerous Token-2022 extensions (permanentDelegate, transferHook, nonTransferable, defaultAccountState) directly on-chain via RPC — catches a fraud surface that GMGN's own rug-check fields (renounced_mint/renounced_freeze_account) don't ask about at all. Use when the user wants a second, independent opinion on a Solana token's safety, especially after a rug-check tool already called it clean, or whenever the user says a coin "looks good" and wants to know what a surface-level check might miss.
---

# Solana Token-2022 forensics

Why this exists: every rug-check skill in this collection (`gmgn-contract-dd`, the memecoin scanner)
is downstream of GMGN's API. GMGN's own calibration data showed its composite score calling
labelled rugs "relatively clean" in 3 of 10 measured cases. This skill doesn't ask an API's
opinion at all — it reads the mint account directly off the chain.

## Run it

```
python3 scripts/check_extensions.py <MINT_ADDRESS>
```

No API key, no signup. Uses the public Solana RPC by default (fine for this single low-volume
call; set `SOLANA_RPC_URL` to a real endpoint if it 429s from repeated use).

## What it actually catches that GMGN-based checks miss

Solana's newer token program, **Token-2022**, adds optional "extensions" on top of the classic
mint. A token can have `renounced_mint: true` and `renounced_freeze_account: true` — passing
every check `gmgn-contract-dd` runs — and still carry:

- **`permanentDelegate`** — an authority that can transfer or burn *any* holder's tokens,
  anytime, no permission needed. This is a worse rug vector than freeze authority and it is
  invisible to a classic renounced-mint/renounced-freeze check.
- **`transferHook`** — every transfer must call an external program first. That program can
  implement a hidden honeypot (block sells under arbitrary conditions) independent of freeze
  authority entirely.
- **`nonTransferable`** — the token literally cannot be sold. Absolute honeypot.
- **`defaultAccountState: frozen`** — new holders start frozen and need manual thawing.

None of these show up in `renounced_mint`/`renounced_freeze_account`. They are why a token can
look clean on every check we've built so far and still be structured to rob you.

## Reading the output

- **CRITICAL** findings (`permanentDelegate`, `transferHook`, `nonTransferable`) mean stop and
  treat the token as a probable rug regardless of anything else about it — win rate, liquidity,
  insider activity, none of it matters if any holder's tokens can be moved without their consent.
- **CAUTION** findings (`transferFeeConfig`, `defaultAccountState`, `mintCloseAuthority`,
  `confidentialTransferMint`) are not automatically bad — read the `state` field. A
  `transferFeeConfig` with both authorities `null` is a fixed, locked, disclosed fee (some
  legitimate projects use this for treasury/buybacks). The same extension with a live
  `transferFeeConfigAuthority` means the fee percentage can be *changed later*, including to
  something extractive — that is the part worth flagging to the user, not the extension's mere
  presence.
- **A non-null mint or freeze authority is not automatically bad either.** USDC's are both
  live — Circle legitimately controls them for redemptions and compliance freezes. What matters
  is *who* holds the authority and *why*, which this script cannot tell you (it reports the
  address, not the identity behind it) — that's a judgment call for the person reading the
  report, not something to auto-flag.
- **UNKNOWN** extensions (anything not in the script's list) mean exactly that — don't assume
  safe just because it wasn't flagged CRITICAL. Solana adds new extensions over time; look up
  whatever shows here before trusting it.

## What this does NOT check

- LP lock legitimacy (which program actually holds the LP tokens, is it a reputable locker, when
  does it unlock) — not built. `lock_summary` from `gmgn-cli token security` is still the source
  for that, with the same caveat that it's trusting GMGN's read of it.
- Funding-cluster / Sybil holder analysis (are the top holders actually independent wallets, or
  all funded from one source) — that's `solana-wallet-scan` in this same repo, run per top holder,
  not built into this skill.
- Anything on EVM chains — Token-2022 is Solana-specific. A `0x...` address isn't in scope here.

This is one more independent check, not a complete audit. Combine it with `gmgn-contract-dd` and
`gmgn-holder-analysis` rather than instead of them.
