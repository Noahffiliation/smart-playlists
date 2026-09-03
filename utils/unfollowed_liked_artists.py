from __future__ import annotations

import sys
from pathlib import Path

# Add project root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import logging
from collections import defaultdict
from os import getenv
from typing import Any

import spotipy
from dotenv import load_dotenv

from utils.common import get_spotify_client, setup_logger

load_dotenv()

MIN_LIKED_SONGS = int(getenv("MIN_LIKED_SONGS", "10"))


def _collect_artist_ids(artists_data: dict[str, Any], target_set: set[str]) -> None:
    """Extract and add artist IDs from an artists page object into a set."""
    for artist in artists_data.get("items", []):
        if artist and artist.get("id"):
            target_set.add(artist["id"])


def get_followed_artist_ids(sp: spotipy.Spotify) -> set[str]:
    """Get all artist IDs the user follows."""
    followed: set[str] = set()
    results = sp.current_user_followed_artists(limit=50)
    if not results or not results.get("artists"):
        return followed

    artists_data = results["artists"]
    _collect_artist_ids(artists_data, followed)

    while artists_data.get("next"):
        next_results = sp.next(artists_data)
        if not next_results or not next_results.get("artists"):
            break
        artists_data = next_results["artists"]
        _collect_artist_ids(artists_data, followed)

    return followed


def _process_saved_track_item(
    item: dict[str, Any] | None, counts: dict[str, int], names: dict[str, str]
) -> None:
    """Extract primary artist from a saved track item and update counts."""
    if not item:
        return
    track = item.get("track")
    if not track or not track.get("artists"):
        return

    artist = track["artists"][0]
    if not artist or not artist.get("id"):
        return

    artist_id = artist["id"]
    counts[artist_id] += 1
    names[artist_id] = artist.get("name", "Unknown")


def count_liked_songs_by_artist(sp: spotipy.Spotify) -> tuple[dict[str, int], dict[str, str]]:
    """Count liked songs per primary artist from the user's liked songs."""
    counts: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    offset = 0
    limit = 50

    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        if not results or not results.get("items"):
            break

        for item in results["items"]:
            _process_saved_track_item(item, counts, names)

        if not results.get("next"):
            break
        offset += limit

    return counts, names


def find_unfollowed_liked_artists(
    counts: dict[str, int], names: dict[str, str], followed_ids: set[str], min_liked: int
) -> list[dict[str, Any]]:
    """Filter and sort artists who are not followed but have at least min_liked songs."""
    candidates: list[dict[str, Any]] = []
    for artist_id, liked_count in counts.items():
        if artist_id in followed_ids:
            continue
        if liked_count >= min_liked:
            candidates.append(
                {
                    "id": artist_id,
                    "name": names[artist_id],
                    "liked_count": liked_count,
                }
            )

    return sorted(candidates, key=lambda x: (-x["liked_count"], x["name"].lower()))


def main(
    args_list: list[str] | None = None,
    client: spotipy.Spotify | None = None,
    custom_logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """Main entrypoint for finding unfollowed artists with many liked songs."""
    parser = argparse.ArgumentParser(
        description="List artists you do not follow but have many liked songs."
    )
    parser.add_argument(
        "--min",
        type=int,
        default=MIN_LIKED_SONGS,
        help=f"Minimum liked songs per artist (default: {MIN_LIKED_SONGS})",
    )
    args = parser.parse_args(args_list)

    logger = custom_logger or setup_logger("unfollowed_liked_artists", "unfollowed_liked_artists")
    logger.info("=" * 60)
    logger.info("Unfollowed artists with many liked songs")
    logger.info("=" * 60)

    sp = client or get_spotify_client()

    logger.info("Fetching followed artists...")
    followed_ids = get_followed_artist_ids(sp)
    logger.info(f"Following {len(followed_ids)} artists")

    logger.info("Counting liked songs by artist...")
    counts, names = count_liked_songs_by_artist(sp)
    logger.info(f"Found {sum(counts.values())} liked songs across {len(counts)} artists")

    results = find_unfollowed_liked_artists(counts, names, followed_ids, args.min)

    logger.info("")
    logger.info(f"Artists not followed with {args.min}+ liked songs: {len(results)}")
    logger.info("-" * 60)

    if not results:
        logger.info("No artists matched your criteria.")
    else:
        for i, artist in enumerate(results, 1):
            logger.info(f"{i:3}. {artist['name']} ({artist['liked_count']} liked songs)")

    logger.info("-" * 60)
    logger.info("Done")
    logger.info("=" * 60)
    return results


if __name__ == "__main__":
    main()
