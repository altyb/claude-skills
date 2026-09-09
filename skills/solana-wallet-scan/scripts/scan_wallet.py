#!/usr/bin/env python3
"""Scan a Solana wallet's trade history for copy-trade risk signals.

No dependencies beyond stdlib. Usage:
    python3 scan_wallet.py <WALLET_ADDRESS> [--limit 1000]

RPC endpoint resolution (first match wins):
  1. $SOLANA_RPC_URL env var
  2. ~/.secrets/helius.token -> https://mainnet.helius-rpc.com/?api-key=<token>
  3. public https://api.mainnet-beta.solana.com (rate-limited, may 403/429
     from sanctioned exit IPs -- see network-sanctions-tunnel notes)
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict
from pathlib import Path

LAMPORTS_PER_SOL = 1_000_000_000


def rpc_url() -> str:
    if env := os.environ.get("SOLANA_RPC_URL"):
        return env
    helius = Path.home() / ".secrets" / "helius.token"
    if helius.exists():
        key = helius.read_text().strip()
        return f"https://mainnet.helius-rpc.com/?api-key={key}"
    return "https://api.mainnet-beta.solana.com"


def rpc_call(url: str, method: str, params: list, retries: int = 3):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read())
                if "error" in body:
                    raise RuntimeError(f"RPC error on {method}: {body['error']}")
                return body["result"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 403) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(
                f"HTTP {e.code} calling {method} at {url}. "
                "Public RPC often 429/403s from this network -- try a Helius key "
                "(~/.secrets/helius.token) or the provider-proxy tunnel."
            ) from e
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(1.0)
                continue
            raise RuntimeError(f"Network error calling {method}: {e}") from e


def get_signatures(url: str, address: str, limit: int):
    out, before = [], None
    while len(out) < limit:
        batch_size = min(1000, limit - len(out))
        params = [address, {"limit": batch_size}]
        if before:
            params[1]["before"] = before
        batch = rpc_call(url, "getSignaturesForAddress", params)
        if not batch:
            break
        out.extend(batch)
        before = batch[-1]["signature"]
        if len(batch) < batch_size:
            break
    return out


def get_transactions(url: str, signatures: list):
    txs = []
    for sig_info in signatures:
        tx = rpc_call(url, "getTransaction", [
            sig_info["signature"],
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
        ])
        if tx:
            tx["_signature"] = sig_info["signature"]
            tx["_blockTime"] = sig_info.get("blockTime")
            txs.append(tx)
    return txs


def sol_delta(tx: dict, wallet: str) -> float:
    """Net lamport change for `wallet` in this tx, in SOL."""
    keys = tx["transaction"]["message"]["accountKeys"]
    idx = next((i for i, k in enumerate(keys) if k.get("pubkey") == wallet), None)
    if idx is None:
        return 0.0
    pre = tx["meta"]["preBalances"][idx]
    post = tx["meta"]["postBalances"][idx]
    return (post - pre) / LAMPORTS_PER_SOL


def token_deltas(tx: dict, wallet: str) -> dict:
    """{mint: token amount delta} for `wallet` in this tx."""
    deltas = defaultdict(float)
    pre = {b["mint"]: b for b in tx["meta"].get("preTokenBalances", []) if b.get("owner") == wallet}
    post = {b["mint"]: b for b in tx["meta"].get("postTokenBalances", []) if b.get("owner") == wallet}
    for mint in set(pre) | set(post):
        pre_amt = float(pre[mint]["uiTokenAmount"]["uiAmountString"] or 0) if mint in pre else 0.0
        post_amt = float(post[mint]["uiTokenAmount"]["uiAmountString"] or 0) if mint in post else 0.0
        if post_amt != pre_amt:
            deltas[mint] += post_amt - pre_amt
    return deltas


def analyze(wallet: str, txs: list):
    txs = sorted((t for t in txs if t.get("_blockTime")), key=lambda t: t["_blockTime"])
    per_token = defaultdict(lambda: {"sol_in": 0.0, "sol_out": 0.0, "first_ts": None, "last_ts": None, "token_bal": 0.0})

    for tx in txs:
        sd = sol_delta(tx, wallet)
        tds = token_deltas(tx, wallet)
        if not tds:
            continue
        for mint, amt in tds.items():
            rec = per_token[mint]
            rec["token_bal"] += amt
            rec["first_ts"] = rec["first_ts"] or tx["_blockTime"]
            rec["last_ts"] = tx["_blockTime"]
            # crude split: if buying this token, count the SOL leg as spent on it;
            # good enough as an approximation, not exact multi-token-tx accounting.
            if amt > 0:
                rec["sol_out"] += max(-sd, 0) if sd < 0 else 0
            else:
                rec["sol_in"] += max(sd, 0)

    closed = {m: r for m, r in per_token.items() if abs(r["token_bal"]) < 1e-6 and (r["sol_in"] or r["sol_out"])}
    open_positions = {m: r for m, r in per_token.items() if m not in closed}

    wins = sum(1 for r in closed.values() if r["sol_in"] > r["sol_out"])
    total_realized_pnl = sum(r["sol_in"] - r["sol_out"] for r in closed.values())
    hold_times = [r["last_ts"] - r["first_ts"] for r in closed.values() if r["last_ts"] and r["first_ts"]]

    funding_tx = next((t for t in txs if sol_delta(t, wallet) > 0), None)
    funder = None
    if funding_tx:
        keys = funding_tx["transaction"]["message"]["accountKeys"]
        payer = next((k["pubkey"] for k in keys if k.get("signer")), None)
        if payer and payer != wallet:
            funder = payer

    return {
        "wallet": wallet,
        "tokens_traded": len(per_token),
        "closed_positions": len(closed),
        "open_positions": len(open_positions),
        "win_rate": round(wins / len(closed), 3) if closed else None,
        "realized_pnl_sol": round(total_realized_pnl, 4),
        "avg_hold_time_minutes": round(sum(hold_times) / len(hold_times) / 60, 1) if hold_times else None,
        "funding_wallet": funder,
        "first_seen": txs[0]["_blockTime"] if txs else None,
        "last_seen": txs[-1]["_blockTime"] if txs else None,
        "tx_scanned": len(txs),
    }


def check_funder_cluster(url: str, funder: str, around_ts: int, window_s: int = 3600):
    """How many *other* wallets did `funder` fund in a window around around_ts?
    A funder that seeds many wallets in a short window is the wallet-farm tell."""
    if not funder:
        return {"checked": False}
    sigs = get_signatures(url, funder, limit=200)
    nearby = [s for s in sigs if s.get("blockTime") and abs(s["blockTime"] - around_ts) < window_s]
    txs = get_transactions(url, nearby[:50])
    funded = set()
    for tx in txs:
        keys = [k["pubkey"] for k in tx["transaction"]["message"]["accountKeys"]]
        for k in keys:
            if k != funder and sol_delta(tx, k) > 0:
                funded.add(k)
    return {"checked": True, "distinct_wallets_funded_nearby": len(funded), "sample": list(funded)[:10]}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    wallet = sys.argv[1]
    limit = 1000
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    url = rpc_url()
    print(f"[scan_wallet] RPC: {url.split('?')[0]}", file=sys.stderr)
    print(f"[scan_wallet] fetching up to {limit} signatures for {wallet}...", file=sys.stderr)
    sigs = get_signatures(url, wallet, limit)
    print(f"[scan_wallet] fetching {len(sigs)} transactions (this is the slow part)...", file=sys.stderr)
    txs = get_transactions(url, sigs)

    report = analyze(wallet, txs)

    cluster = {"checked": False}
    if report["funding_wallet"] and report["first_seen"]:
        print(f"[scan_wallet] checking funder {report['funding_wallet']} for cluster funding...", file=sys.stderr)
        cluster = check_funder_cluster(url, report["funding_wallet"], report["first_seen"])
    report["funder_cluster_check"] = cluster

    flags = []
    if cluster.get("checked") and cluster["distinct_wallets_funded_nearby"] >= 5:
        flags.append(
            f"FUNDING CLUSTER: funder also seeded {cluster['distinct_wallets_funded_nearby']} other wallets "
            "in the hour around this wallet's first funding tx -- classic wallet-farm pattern."
        )
    if report["avg_hold_time_minutes"] is not None and report["avg_hold_time_minutes"] < 5:
        flags.append("SNIPER/SCALP TIMING: avg hold time under 5 minutes -- likely bot, not a signal you can react to fast enough to copy.")
    if report["win_rate"] is not None and report["win_rate"] >= 0.9 and report["closed_positions"] >= 10:
        flags.append("SUSPICIOUSLY HIGH WIN RATE: >=90% over 10+ closed trades is rare for organic trading -- verify this isn't a proxy/insider wallet before copying.")
    report["risk_flags"] = flags

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
