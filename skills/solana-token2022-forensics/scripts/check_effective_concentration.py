#!/usr/bin/env python3
"""Effective vs naive holder concentration on a Solana token.

top_10_holder_rate only catches concentration when it's held in a FEW large
wallets. It structurally cannot see one entity that split its stake across
hundreds or thousands of small wallets (each individually below the top-10
cutoff) that still trade normally and look independent one at a time — the
exact evasion this script exists to catch.

Method: sum GMGN's own wallet-tag-classified holders (bundler / sniper /
rat_trader / fresh_wallet — each computed server-side from funding/behavior
patterns, not from us) as a proxy for "coordinated," dedupe by address so a
wallet carrying two tags isn't double-counted, and compare the union against
the naive top-10 number. A big gap between the two IS the "40% split across
2000 wallets" pattern made visible.

Usage: python3 check_effective_concentration.py <MINT_ADDRESS> [--chain sol]
Needs gmgn-cli configured (GMGN_API_KEY) — same as the other gmgn-* skills.
"""
import json
import subprocess
import sys
import time
from typing import Optional

RISK_TAGS = ["bundler", "sniper", "rat_trader", "fresh_wallet"]


def gmgn_holders(chain: str, address: str, tag: Optional[str] = None, limit: int = 100, retries: int = 3):
    cmd = ["gmgn-cli", "token", "holders", "--chain", chain, "--address", address, "--limit", str(limit), "--raw"]
    if tag:
        cmd += ["--tag", tag]
    for attempt in range(retries):
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if out.returncode == 0:
            return json.loads(out.stdout).get("list", [])
        if "RATE_LIMIT" in out.stderr and attempt < retries - 1:
            time.sleep(15 * (attempt + 1))
            continue
        raise RuntimeError(f"gmgn-cli failed: {out.stderr.strip()}")
    raise RuntimeError("gmgn-cli failed: exhausted retries on rate limit")


def gmgn_security(chain: str, address: str) -> dict:
    out = subprocess.run(
        ["gmgn-cli", "token", "security", "--chain", chain, "--address", address, "--raw"],
        capture_output=True, text=True, timeout=30,
    )
    return json.loads(out.stdout) if out.returncode == 0 else {}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    address = sys.argv[1]
    chain = "sol"
    if "--chain" in sys.argv:
        chain = sys.argv[sys.argv.index("--chain") + 1]

    security = gmgn_security(chain, address)
    naive_top10 = float(security.get("top_10_holder_rate") or 0) * 100

    print(f"=== {address} ({chain}) ===")
    print(f"Naive top_10_holder_rate: {naive_top10:.2f}%  (this is what most rug-checkers report and stop at)\n")

    combined: dict[str, dict] = {}
    failed_tags: list[str] = []
    for i, tag in enumerate(RISK_TAGS):
        if i > 0:
            time.sleep(2)  # pace requests, GMGN's free tier rate-limits fast
        try:
            rows = gmgn_holders(chain, address, tag=tag)
        except Exception as e:
            print(f"  [{tag}] fetch failed: {e}")
            failed_tags.append(tag)
            continue
        pct = sum(r.get("amount_percentage", 0) for r in rows)
        print(f"[{tag:12s}] {len(rows):3d} wallets, {pct*100:6.2f}% of supply")
        for r in rows:
            addr = r.get("address")
            combined.setdefault(addr, {"pct": r.get("amount_percentage", 0), "tags": set()})
            combined[addr]["tags"].add(tag)

    if failed_tags:
        print(
            f"\n=== INCOMPLETE — {len(failed_tags)}/{len(RISK_TAGS)} tag queries failed "
            f"({', '.join(failed_tags)}) ==="
        )
        print(
            "Do NOT read this as a clean result. A failed fetch is missing data, not zero "
            "concentration — re-run once the rate limit clears rather than trusting a partial scan."
        )
        sys.exit(1)

    union_pct = sum(v["pct"] for v in combined.values()) * 100
    print(f"\n=== EFFECTIVE CONCENTRATION (deduped union of tagged wallets) ===")
    print(f"{len(combined)} distinct wallets, {union_pct:.2f}% of supply combined")
    print(f"Naive top-10 check said: {naive_top10:.2f}%")

    gap = union_pct - naive_top10
    print(f"\nGap: {gap:+.2f} percentage points")
    if gap > 15:
        print(
            "SIGNIFICANT GAP — a large share of supply is in GMGN-tagged coordinated wallets "
            "that the top-10 concentration check does not see because no single one of them "
            "ranks in the top 10. Treat the naive top_10_holder_rate as understating real risk here."
        )
    elif gap > 5:
        print("Moderate gap — worth noting, not necessarily disqualifying on its own.")
    else:
        print("Small gap — the naive top-10 number is a reasonable proxy for this token.")

    multi_tag = {a: v for a, v in combined.items() if len(v["tags"]) > 1}
    if multi_tag:
        print(f"\n{len(multi_tag)} wallet(s) carry more than one risk tag simultaneously (stacked risk):")
        for a, v in list(multi_tag.items())[:10]:
            print(f"  {a}  {v['pct']*100:.3f}%  tags={sorted(v['tags'])}")


if __name__ == "__main__":
    main()
