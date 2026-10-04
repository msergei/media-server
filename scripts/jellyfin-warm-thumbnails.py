#!/usr/bin/env python3
"""Pre-generate Jellyfin photo thumbnails so folders open without waiting.

Jellyfin resizes photos only when a client asks for them. This script asks for
every photo with the same parameters the web client uses, so the resized
images land in Jellyfin's cache (/cache/images/resized-images) in advance.

The web client asks for a size that depends on the browser window width
    /Items/{id}/Images/Primary?fillHeight=H&fillWidth=W&quality=96&tag=T
and Jellyfin caches every size separately. Traefik therefore redirects those
requests to one of two fixed sizes (see the thumbs-s/thumbs-l middlewares in
docker-compose.override.example.yml):
    /Items/{id}/Images/Primary?fillWidth=400|800&quality=96&tag=T
This script requests exactly those URLs. The cache key includes every
parameter and the output format, so they must match the redirect target.

The API key is read from JELLYFIN_API_KEY or from the .env next to
docker-compose.yml.

Usage:
    ./jellyfin-warm-thumbnails.py [--widths 400,800] [--path-prefix /share/...]
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CONTAINER = "media-server-jellyfin-1"
# Browsers advertise WebP, and Jellyfin picks the output format from Accept.
ACCEPT = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"


def default_url():
    ip = subprocess.check_output(
        ["docker", "inspect", "-f",
         "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", CONTAINER],
        text=True,
    ).split()[0]
    return f"http://{ip}:8096"


def api_key():
    key = os.environ.get("JELLYFIN_API_KEY")
    if key:
        return key
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    try:
        with open(env) as f:
            for line in f:
                if line.startswith("JELLYFIN_API_KEY="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return None


def get_json(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f'MediaBrowser Token="{key}"'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def list_photos(base, key, path_prefix):
    photos, start, page = [], 0, 1000
    while True:
        q = urllib.parse.urlencode({
            "IncludeItemTypes": "Photo",
            "Recursive": "true",
            "Fields": "Path",
            "EnableImageTypes": "Primary",
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "StartIndex": start,
            "Limit": page,
        })
        data = get_json(f"{base}/Items?{q}", key)
        items = data.get("Items", [])
        for it in items:
            tag = it.get("ImageTags", {}).get("Primary")
            if tag and (not path_prefix or it.get("Path", "").startswith(path_prefix)):
                photos.append((it["Id"], tag))
        start += len(items)
        if not items or start >= data.get("TotalRecordCount", 0):
            return photos


def warm(base, item_id, tag, width):
    # Same parameters in the same order as the Traefik redirect target.
    params = {"fillWidth": width, "quality": 96, "tag": tag}
    url = f"{base}/Items/{item_id}/Images/Primary?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": ACCEPT})
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=600) as r:
        # Jellyfin can leave a 0-byte cache entry behind and keep serving it.
        if not r.read():
            raise RuntimeError(f"empty image for item {item_id} (width {width})")
    return time.monotonic() - t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("JELLYFIN_URL"), help="Jellyfin base URL (default: container IP)")
    ap.add_argument("--widths", default="400,800", help="fillWidth values the Traefik redirects point to")
    ap.add_argument("--path-prefix", default="", help="only photos whose path starts with this, e.g. /share/Content/Phone/Camera")
    ap.add_argument("--workers", type=int, default=2, help="parallel requests (Jellyfin also limits encodes itself)")
    args = ap.parse_args()

    key = api_key()
    if not key:
        sys.exit("JELLYFIN_API_KEY is not set (environment or .env)")
    base = (args.url or default_url()).rstrip("/")
    widths = [int(w) for w in args.widths.split(",")]

    photos = list_photos(base, key, args.path_prefix)
    jobs = [(p, w) for p in photos for w in widths]
    print(f"{len(photos)} photos x {len(widths)} widths = {len(jobs)} thumbnails", flush=True)

    started, done, slow, failed = time.monotonic(), 0, 0, 0
    with ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(warm, base, *p, w) for p, w in jobs]
        for f in futures:
            try:
                # Cached thumbnails come back in milliseconds; anything slower was generated now.
                slow += f.result() > 0.5
            except Exception as e:
                failed += 1
                print(f"error: {e}", file=sys.stderr, flush=True)
            done += 1
            if done % 500 == 0:
                print(f"{done}/{len(jobs)} done, {slow} generated, {failed} failed, "
                      f"{time.monotonic() - started:.0f}s", flush=True)

    print(f"finished: {done} requested, {slow} generated, {failed} failed, "
          f"{time.monotonic() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
