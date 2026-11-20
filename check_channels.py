#!/usr/bin/env python3
"""
Validate only DStv channels (channel_id ends with '.dstv_com') in hugftre.json.
- Removes DStv channels whose streamUrl fails.
- Keeps working DStv channels.
- ALWAYS keeps any channel whose streamUrl contains "bobtv" (never checked, never removed).
- Leaves all other channels (UK, NZ, etc.) completely untouched.
- Stores removed DStv entries in known_dead.json so they can be re-added if they recover.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests

CHANNELS_FILE = Path("hugftre.json")
DEAD_FILE     = Path("known_dead.json")
TIMEOUT       = 15
MAX_WORKERS   = 15
DSTV_SUFFIX   = ".dstv_com"
PROTECTED_TOKEN = "bobtv"   # any streamUrl containing this is never checked or removed

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0 Safari/537.36"
)


def is_dstv(channel: dict) -> bool:
    """True only for DStv channels."""
    return str(channel.get("channel_id", "")).endswith(DSTV_SUFFIX)


def is_protected(channel: dict) -> bool:
    """True if streamUrl contains the protected token (e.g. bobtv)."""
    url = str(channel.get("streamUrl", "")).lower()
    return PROTECTED_TOKEN in url


def is_stream_alive(url: str) -> bool:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT, stream=True)
        if r.status_code != 200:
            return False

        chunk = next(r.iter_content(chunk_size=2048), b"")
        content_type = r.headers.get("Content-Type", "").lower()
        r.close()

        if not chunk:
            return False

        text = chunk.decode("utf-8", errors="ignore").lstrip("\ufeff")

        if text.startswith("#EXTM3U"):
            if "#EXT-X-STREAM-INF" in text:
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        variant_url = urljoin(url, line)
                        try:
                            vr = requests.get(
                                variant_url, headers=headers,
                                timeout=TIMEOUT, stream=True,
                            )
                            ok = vr.status_code == 200
                            vr.close()
                            return ok
                        except Exception:
                            return False
            return "#EXTINF" in text or "#EXT-X-TARGETDURATION" in text

        if "mpegts" in content_type or "mp2t" in content_type:
            return True

        return False
    except Exception:
        return False


def check_channel(channel: dict) -> tuple[dict, bool]:
    url = channel.get("streamUrl", "")
    if not url:
        return channel, False
    return channel, is_stream_alive(url)


def load_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.load(path.open(encoding="utf-8"))
    except Exception:
        return []


def save_json_list(path: Path, data: list) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if not CHANNELS_FILE.exists():
        print(f"ERROR: {CHANNELS_FILE} not found", file=sys.stderr)
        return 1

    channels = load_json_list(CHANNELS_FILE)

    # DStv channels split into protected (bobtv) and checkable
    dstv_protected = [c for c in channels if is_dstv(c) and is_protected(c)]
    dstv_checkable = [c for c in channels if is_dstv(c) and not is_protected(c)]
    non_dstv       = [c for c in channels if not is_dstv(c)]

    print(f"Total channels: {len(channels)}")
    print(f"  DStv protected (bobtv, never removed): {len(dstv_protected)}")
    print(f"  DStv will be checked:                  {len(dstv_checkable)}")
    print(f"  Other (untouched):                     {len(non_dstv)}")

    if not dstv_checkable and not dstv_protected:
        print("No DStv channels found; nothing to do.")
        return 0

    # --- 1. Check current checkable DStv channels ---
    working, dead = [], []
    if dstv_checkable:
        print(f"\nChecking {len(dstv_checkable)} DStv channels with {MAX_WORKERS} workers...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(check_channel, ch): ch for ch in dstv_checkable}
            for i, fut in enumerate(as_completed(futures), 1):
                ch, ok = fut.result()
                print(f"[{i:>3}/{len(dstv_checkable)}] {'OK  ' if ok else 'DEAD'} {ch.get('name','?')}")
                (working if ok else dead).append(ch)

    # Preserve original order
    working_urls = {c.get("streamUrl") for c in working}
    ordered_working_dstv = [c for c in dstv_checkable if c.get("streamUrl") in working_urls]

    # --- 2. Merge dead entries into known_dead.json (exclude protected) ---
    existing_dead = load_json_list(DEAD_FILE)
    merged_dead = {
        c["streamUrl"]: c
        for c in existing_dead
        if is_dstv(c) and not is_protected(c) and "streamUrl" in c
    }
    for c in dead:
        if "streamUrl" in c:
            merged_dead[c["streamUrl"]] = c

    # --- 3. Re-check previously dead DStv channels (never protected) ---
    live_urls = {c.get("streamUrl") for c in ordered_working_dstv}
    candidates = [c for c in merged_dead.values() if c["streamUrl"] not in live_urls]

    recovered, still_dead = [], []
    if candidates:
        print(f"\nRe-checking {len(candidates)} previously dead DStv channels...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(check_channel, ch): ch for ch in candidates}
            for fut in as_completed(futures):
                ch, ok = fut.result()
                (recovered if ok else still_dead).append(ch)
        for ch in recovered:
            print(f"RECOVERED: {ch.get('name')}")

    # --- 4. Rebuild hugftre.json preserving original slot ---
    # Protected + working + recovered are all kept.
    keep_by_url = {}
    for c in dstv_protected + ordered_working_dstv + recovered:
        keep_by_url[c["streamUrl"]] = c

    final_channels = []
    seen_kept_urls = set()
    for c in channels:
        if is_dstv(c):
            url = c.get("streamUrl")
            if is_protected(c):
                # Always keep, even if URL wasn't in keep_by_url (defensive)
                final_channels.append(c)
                seen_kept_urls.add(url)
            elif url in keep_by_url:
                final_channels.append(keep_by_url[url])
                seen_kept_urls.add(url)
            # else: dropped
        else:
            final_channels.append(c)

    # Append any recovered DStv channels not already present
    for url, c in keep_by_url.items():
        if url not in seen_kept_urls:
            final_channels.append(c)

    # --- 5. Persist ---
    save_json_list(CHANNELS_FILE, final_channels)
    save_json_list(DEAD_FILE, still_dead)

    print(
        f"\nDone: {len(ordered_working_dstv)} DStv kept, "
        f"{len(dead)} removed, {len(recovered)} recovered, "
        f"{len(dstv_protected)} protected (bobtv)."
    )
    print(f"Non-DStv channels untouched: {len(non_dstv)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
