from __future__ import annotations

import sys
from pathlib import Path

# Add project root directory to sys.path so smart_playlists can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from os import getenv
from typing import Any

from dotenv import load_dotenv

from smart_playlists import (
    create_or_update_playlist,
    get_all_spotify_library_tracks,
    get_lastfm_track_playcount,
    logger,
    match_spotify_with_lastfm,
)
from utils.common import format_elapsed_time

load_dotenv()


MIN_TRACK_DURATION_MS = 30_000


def generate_unplayed_playlist(
    spotify_library: dict[str, dict[str, Any]],
    unplayed_playlist_name: str,
    min_duration_ms: int = MIN_TRACK_DURATION_MS,
) -> list[dict[str, Any]]:
    """Create/update playlist with tracks that have 0 playcount on Last.fm and are longer than min_duration_ms."""
    logger.info("\n" + "=" * 50)
    logger.info("CREATING UNPLAYED TRACKS PLAYLIST")
    logger.info("=" * 50)

    matched_tracks = match_spotify_with_lastfm(spotify_library)

    def _get_duration(t: dict[str, Any]) -> int:
        dur = t.get("duration_ms")
        if dur is None or dur == 0:
            dur = spotify_library.get(t.get("uri", ""), {}).get("duration_ms", 0)
        try:
            return int(dur)
        except (ValueError, TypeError):
            return 0

    # Filter tracks with 0 plays in bulk cache and duration > min_duration_ms
    unplayed_tracks = [
        t for t in matched_tracks if t["playcount"] == 0 and _get_duration(t) > min_duration_ms
    ]

    logger.info(
        f"\nFound {len(unplayed_tracks)} tracks with 0 playcount in cache (> {min_duration_ms / 1000:.0f}s). Verifying with API..."
    )

    verified_unplayed: list[dict[str, Any]] = []
    lock = threading.Lock()

    def verify_track(track_info: dict[str, Any]) -> None:
        pc = get_lastfm_track_playcount(track_info["artist"], track_info["name"])
        if pc == 0:
            with lock:
                verified_unplayed.append(track_info)
        else:
            logger.info(
                f"  -> False positive: {track_info['artist']} - {track_info['name']} has {pc} plays"
            )

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(verify_track, t) for t in unplayed_tracks]
        for completed, f in enumerate(as_completed(futures), 1):
            if completed % 10 == 0 or completed == len(unplayed_tracks):
                logger.info(f"Verified {completed}/{len(unplayed_tracks)} tracks...")
            f.result()

    logger.info(f"\nFinal count: {len(verified_unplayed)} tracks with verified 0 playcount.")

    # A Spotify playlist can hold a lot of tracks, we'll add them all
    unplayed_track_uris = [t["uri"] for t in verified_unplayed]

    create_or_update_playlist(unplayed_playlist_name, unplayed_track_uris)
    return verified_unplayed


def main(
    source_playlist_ids: list[str] | None = None,
    unplayed_playlist_name: str | None = None,
    min_duration_ms: int | None = None,
) -> None:
    """Main execution function for generating unplayed playlist."""
    script_start = time.time()
    logger.info(f"Unplayed tracks script started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if source_playlist_ids is None:
        env_source_ids = getenv("SOURCE_PLAYLIST_IDS", "")
        source_playlist_ids = [pid.strip() for pid in env_source_ids.split(",") if pid.strip()]

    target_name = unplayed_playlist_name or getenv("UNPLAYED_PLAYLIST_NAME") or "Unplayed Tracks"

    if min_duration_ms is None:
        env_min_duration = getenv("MIN_TRACK_DURATION_MS")
        duration_threshold = (
            int(env_min_duration)
            if env_min_duration and env_min_duration.isdigit()
            else MIN_TRACK_DURATION_MS
        )
    else:
        duration_threshold = min_duration_ms

    # 1. Fetch library once
    logger.info("Fetching Spotify library...")
    full_library = get_all_spotify_library_tracks(source_playlist_ids)

    # 2. Generate unplayed playlist
    operation_start = time.time()
    generate_unplayed_playlist(full_library, target_name, min_duration_ms=duration_threshold)
    operation_time = time.time() - operation_start
    logger.info(
        f"\nUnplayed tracks playlist update completed in {format_elapsed_time(operation_time)}"
    )

    total_runtime = time.time() - script_start
    logger.info("\n" + "=" * 50)
    logger.info(f"Script completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Total runtime: {format_elapsed_time(total_runtime)}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
