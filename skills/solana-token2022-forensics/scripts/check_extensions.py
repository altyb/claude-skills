#!/usr/bin/env python3
"""Independently verify a Solana token's mint/freeze authorities and Token-2022
extension risks DIRECTLY via RPC — does not trust any third-party API's claim
(GMGN's renounced_mint/renounced_freeze_account fields don't ask about
Token-2022 extensions at all, which is exactly how a token can look clean on
those checks while still carrying a permanentDelegate or transferHook).

Usage: python3 check_extensions.py <MINT_ADDRESS> [--rpc-url URL]

RPC: $SOLANA_RPC_URL env var, else the public endpoint (fine for the single
low-volume call this script makes; it will 429 under repeated/scripted use —
see network-sanctions-tunnel notes if that happens).
"""
import json
import sys
import os
import urllib.request

DANGEROUS = {
    "permanentDelegate": (
        "CRITICAL - this authority can transfer or burn ANY holder's tokens "
        "without their permission, at any time. Worse than freeze authority "
        "and NOT covered by a 'renounced_freeze_account' check."
    ),
    "transferHook": (
        "CRITICAL - every transfer must pass through an external program that "
        "can implement arbitrary logic (a hidden honeypot mechanism), "
        "independent of freeze authority. Read the hook program before trusting it."
    ),
    "nonTransferable": (
        "CRITICAL - this token can never be transferred/sold at all (soulbound). "
        "Absolute honeypot if you weren't expecting that."
    ),
}
CAUTION = {
    "defaultAccountState": (
        "CAUTION - new token accounts can start FROZEN by default; check the "
        "state value below. If frozen, holders can't receive/send until "
        "manually thawed by an authority."
    ),
    "transferFeeConfig": (
        "CAUTION - every transfer pays a fee. Check whether the fee-config "
        "authority and withdraw authority below are null (locked) or a live "
        "address (fee % can be changed later, or proceeds withdrawn)."
    ),
    "mintCloseAuthority": (
        "CAUTION - this authority can close the mint account. Rarely malicious, "
        "worth knowing about."
    ),
    "confidentialTransferMint": (
        "CAUTION - supports confidential (hidden-amount) transfers. Unusual for "
        "a meme coin; can obscure real balances/flows."
    ),
}
INFO = {"metadataPointer", "tokenMetadata", "groupPointer", "groupMemberPointer", "interestBearingConfig"}

TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
LEGACY_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def rpc(url: str, method: str, params: list):
    req = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read())
        if "error" in body:
            raise RuntimeError(f"RPC error: {body['error']}")
        return body["result"]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    mint = sys.argv[1]
    rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

    info = rpc(rpc_url, "getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    if not info or not info.get("value"):
        print(f"No account found for {mint} — not a valid mint address, or this RPC has no data for it.")
        sys.exit(1)

    val = info["value"]
    program = val.get("owner")
    parsed = val.get("data", {}).get("parsed", {})
    tinfo = parsed.get("info", {})

    print(f"=== {mint} ===")
    print(f"Owning program: {program}")

    if program == LEGACY_TOKEN_PROGRAM:
        print("Legacy SPL Token — no extensions possible (classic mint/freeze authority model only).")
    elif program != TOKEN_2022_PROGRAM:
        print(f"NOT a recognized token program ({program}) — this may not be a standard fungible token mint.")

    mint_auth = tinfo.get("mintAuthority")
    freeze_auth = tinfo.get("freezeAuthority")
    print(f"\nmintAuthority (on-chain, direct):   {mint_auth or 'null (renounced)'}")
    print(f"freezeAuthority (on-chain, direct): {freeze_auth or 'null (renounced)'}")
    print("(Cross-check these against whatever a third-party API told you — they should match.)")

    extensions = tinfo.get("extensions", [])
    if not extensions:
        print("\nNo Token-2022 extensions present.")
        return

    print(f"\n{len(extensions)} Token-2022 extension(s) found:")
    findings = []
    for ext in extensions:
        name = ext.get("extension")
        state = ext.get("state")
        if name in DANGEROUS:
            findings.append(("CRITICAL", name, DANGEROUS[name], state))
        elif name in CAUTION:
            findings.append(("CAUTION", name, CAUTION[name], state))
        elif name in INFO:
            findings.append(("INFO", name, "informational, not a risk signal by itself", state))
        else:
            findings.append(
                ("UNKNOWN", name, "not in this script's known list — review manually, don't assume it's safe", state)
            )

    order = {"CRITICAL": 0, "CAUTION": 1, "UNKNOWN": 2, "INFO": 3}
    findings.sort(key=lambda f: order[f[0]])
    for level, name, desc, state in findings:
        print(f"\n[{level}] {name}")
        print(f"  {desc}")
        print(f"  state: {json.dumps(state)}")

    crit = [f for f in findings if f[0] == "CRITICAL"]
    caution = [f for f in findings if f[0] == "CAUTION"]
    unknown = [f for f in findings if f[0] == "UNKNOWN"]

    print("\n=== VERDICT ===")
    if crit:
        print(f"CRITICAL: {len(crit)} dangerous extension(s) found — {', '.join(f[1] for f in crit)}")
    elif unknown:
        print(
            f"UNKNOWN extension(s) present ({', '.join(f[1] for f in unknown)}) — "
            "not in this script's known-safe/known-dangerous list. Don't assume safe, look it up."
        )
    elif caution:
        print(f"CAUTION: {len(caution)} extension(s) worth understanding before buying — {', '.join(f[1] for f in caution)}")
    else:
        print("No dangerous or caution-worthy extensions found among the known list.")


if __name__ == "__main__":
    main()
