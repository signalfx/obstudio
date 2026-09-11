"""
Collect passive adoption signals from public APIs.

Sources:
  - GitHub Releases: per-asset download counts across all releases
  - VS Code Marketplace: install + update counts for the extension

Outputs a JSON report to stdout (or a file via --output). Exits non-zero on
any fetch failure so CI can catch regressions.

Usage:
  python3 scripts/collect_adoption_signals.py
  python3 scripts/collect_adoption_signals.py --output signals.json
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date

GITHUB_OWNER = "signalfx"
GITHUB_REPO = "obstudio"
VSCODE_PUBLISHER = "Splunk"
VSCODE_EXTENSION = "observability-studio"

VSCODE_MARKETPLACE_API = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"


def _get(url: str, *, headers: dict | None = None, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching {url}") from e
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"Failed to fetch {url}: {e}") from e


def collect_github_releases() -> dict:
    """Per-asset download counts across all GitHub releases."""
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    releases_raw = _get(url, headers=headers)

    releases = []
    total_downloads = 0
    for release in releases_raw:
        assets = []
        for asset in release.get("assets", []):
            count = asset.get("download_count", 0)
            total_downloads += count
            assets.append({"name": asset["name"], "download_count": count})
        releases.append({
            "tag": release.get("tag_name"),
            "published_at": release.get("published_at"),
            "prerelease": release.get("prerelease", False),
            "assets": assets,
            "release_download_total": sum(a["download_count"] for a in assets),
        })

    return {
        "repo": f"{GITHUB_OWNER}/{GITHUB_REPO}",
        "total_downloads": total_downloads,
        "releases": releases,
    }


def collect_vscode_marketplace() -> dict:
    """Install and update counts from the VS Code Marketplace."""
    # Statistic types: 1=install, 3=averageRating, 4=ratingCount, 8=trendingWeekly, 18=downloadCount
    payload = json.dumps({
        "filters": [{"criteria": [
            {"filterType": 7, "value": f"{VSCODE_PUBLISHER}.{VSCODE_EXTENSION}"},
        ]}],
        "flags": 914,  # includes statistics, versions, properties
    }).encode()

    req = urllib.request.Request(
        VSCODE_MARKETPLACE_API,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json;api-version=7.2-preview.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching VS Code Marketplace") from e
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"Failed to fetch VS Code Marketplace: {e}") from e

    try:
        extension = data["results"][0]["extensions"][0]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Marketplace response shape: {e}") from e

    stats = {s["statisticName"]: s["value"] for s in extension.get("statistics", [])}
    versions = [v["version"] for v in extension.get("versions", [])[:5]]

    return {
        "publisher": VSCODE_PUBLISHER,
        "extension": VSCODE_EXTENSION,
        "display_name": extension.get("displayName"),
        "latest_versions": versions,
        "installs": int(stats.get("install", 0)),
        "updates": int(stats.get("updateCount", 0)),
        "average_rating": stats.get("averagerating"),
        "rating_count": int(stats.get("ratingcount", 0)),
        "trending_weekly": stats.get("trendingweekly"),
    }


SOURCES = [
    ("github_releases", collect_github_releases),
    ("vscode_marketplace", collect_vscode_marketplace),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", help="Write JSON to this file instead of stdout")
    args = parser.parse_args()

    report: dict = {"collected_at": date.today().isoformat(), "sources": {}}
    succeeded, failed = [], []

    for name, fn in SOURCES:
        try:
            report["sources"][name] = fn()
            succeeded.append(name)
        except RuntimeError as e:
            report["sources"][name] = {"error": str(e)}
            failed.append((name, str(e)))

    report["summary"] = {
        "total": len(SOURCES),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "succeeded_sources": succeeded,
        "failed_sources": [name for name, _ in failed],
    }

    output = json.dumps(report, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)

    print(
        f"\nCollection summary: {len(succeeded)}/{len(SOURCES)} sources succeeded"
        f"{', ' + str(len(failed)) + ' failed' if failed else ''}.",
        file=sys.stderr,
    )
    for name in succeeded:
        print(f"  OK    {name}", file=sys.stderr)
    for name, err in failed:
        print(f"  FAIL  {name}: {err}", file=sys.stderr)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
