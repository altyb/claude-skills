#!/usr/bin/env python3
"""Creator snipe-and-dump detector.

A wallet's aggregate win rate can look healthy while hiding a specific scam
pattern: it creates its own tokens, buys its own launch in the first seconds
(guaranteed advantageous entry no outsider gets), and dumps within minutes —
before the token dies. That performance isn't trading skill, it's creator
advantage, and it quietly inflates the same win-rate number a copy-trade
decision would rely on. Proven live on a real wallet: launch at 19:46:03,
self-buy same second, sell 7 seconds later, $455 out.

This script: pulls every token a wallet created, checks that wallet's OWN
buy-to-sell gap on each one, and reports what fraction come back inside a
"rapid dump" window (default 5 minutes — matches the 30-second-to-5-minute
pattern this was built to catch).

Usage: python3 check_creator_dump.py <WALLET_ADDRESS> [--chain sol]
                                      [--dump-seconds 300] [--sample 20]
Needs gmgn-cli configured (GMGN_API_KEY).
"""
import json
import subprocess
import sys
import time

DEFAULT_DUMP_SECONDS = 300  # 5 minutes
DEFAULT_SAMPLE = 20


def gmgn_cli(args, retries=3):
    for attempt in range(retries):
        out = subprocess.run(["gmgn-cli", *args, "--raw"], capture_output=True, text=True, timeout=30)
        if out.returncode == 0:
            return json.loads(out.stdout)
        if "RATE_LIMIT" in out.stderr and attempt < retries - 1:
            time.sleep(15 * (attempt + 1))
            continue
        raise RuntimeError(out.stderr.strip())
    raise RuntimeError("exhausted retries on rate limit")


def get_created_tokens(chain: str, wallet: str):
    d = gmgn_cli(["portfolio", "created-tokens", "--chain", chain, "--wallet", wallet])
    return d.get("list") or d.get("tokens") or (d if isinstance(d, list) else [])


def get_own_buy_sell_gap(chain: str, wallet: str, token_address: str):
    """First buy/launch timestamp vs first sell timestamp by THIS wallet on
    THIS token. Returns (gap_seconds, first_buy_ts, first_sell_ts) or None if
    there's no sell yet (still held, or dumped via a route this doesn't see)."""
    d = gmgn_cli(["portfolio", "activity", "--chain", chain, "--wallet", wallet, "--token", token_address, "--limit", "50"])
    rows = d.get("activities") or d.get("list") or []
    buys = [r["timestamp"] for r in rows if r.get("event_type") in ("buy", "launch")]
    sells = [r["timestamp"] for r in rows if r.get("event_type") == "sell"]
    if not buys or not sells:
        return None
    first_buy = min(buys)
    first_sell = min(sells)
    if first_sell < first_buy:
        return None  # sold before buying makes no sense here, skip as noisy data
    return first_sell - first_buy, first_buy, first_sell


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    wallet = sys.argv[1]
    chain = "sol"
    dump_seconds = DEFAULT_DUMP_SECONDS
    sample = DEFAULT_SAMPLE
    if "--chain" in sys.argv:
        chain = sys.argv[sys.argv.index("--chain") + 1]
    if "--dump-seconds" in sys.argv:
        dump_seconds = int(sys.argv[sys.argv.index("--dump-seconds") + 1])
    if "--sample" in sys.argv:
        sample = int(sys.argv[sys.argv.index("--sample") + 1])

    print(f"=== {wallet} ({chain}) — creator snipe-and-dump check ===")
    created = get_created_tokens(chain, wallet)
    print(f"Created {len(created)} token(s) total. Checking up to {sample}.\n")

    if not created:
        print("This wallet hasn't created any tokens — this check doesn't apply. "
              "Its win rate isn't inflated by creator advantage (at least not this way).")
        return

    checked = 0
    dumped = []
    no_sell_yet = 0
    for t in created[:sample]:
        addr = t.get("token_address") or t.get("address")
        symbol = t.get("symbol", "?")
        if not addr:
            continue
        time.sleep(1.5)  # pace requests, GMGN rate-limits fast
        try:
            result = get_own_buy_sell_gap(chain, wallet, addr)
        except Exception as e:
            print(f"  [{symbol}] check failed: {e}")
            continue
        checked += 1
        if result is None:
            no_sell_yet += 1
            print(f"  [{symbol}] no sell found by this wallet on its own token (still holding, or exited another way)")
            continue
        gap = result[0]
        flag = "RAPID DUMP" if gap <= dump_seconds else "normal"
        print(f"  [{symbol}] buy->sell gap: {gap}s ({gap/60:.1f}m)  [{flag}]")
        if gap <= dump_seconds:
            dumped.append((symbol, gap))

    print(f"\n=== VERDICT ===")
    print(f"Checked {checked} of {len(created)} created tokens, {no_sell_yet} had no self-sell on record.")
    dump_rate = len(dumped) / checked if checked else 0
    print(f"Rapid self-dump (<= {dump_seconds}s / {dump_seconds/60:.0f}min): {len(dumped)}/{checked} ({dump_rate*100:.0f}%)")
    if dumped:
        fastest = sorted(dumped, key=lambda x: x[1])[:5]
        print("Fastest dumps: " + ", ".join(f"{s} ({g}s)" for s, g in fastest))

    if dump_rate >= 0.3:
        print(
            "\nFLAG: a significant share of this wallet's own token creations show a rapid "
            "self-buy-then-dump pattern. Any win rate that includes these trades is inflated "
            "by creator advantage, not repeatable trading skill. Do not copy-trade on the "
            "strength of an aggregate win-rate number for this wallet without excluding these."
        )
    elif dump_rate > 0:
        print(f"\n{len(dumped)} rapid dump(s) found — not a dominant pattern, but worth knowing about.")
    else:
        print("\nNo rapid self-dump pattern found in the sample checked.")


if __name__ == "__main__":
    main()
