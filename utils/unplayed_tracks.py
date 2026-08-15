from __future__ import annotations

import sys
from pathlib import Path

# Add project root directory to sys.path so smart_playlists can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
from datetime import datetime
from os import getenv
from dotenv import load_dotenv

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from typing import Any, Optional

import spotipy
import pylast

from utils.common import format_elapsed_time
from smart_playlists import (
    get_all_spotify_library_tracks,
    match_spotify_with_lastfm,
    create_or_update_playlist,
    logger,
    get_lastfm_track_playcount,
)

load_dotenv()


def generate_unplayed_playlist(
    spotify_library: dict[str, dict[str, Any]],
    unplayed_playlist_name: str,
    client: Optional[spotipy.Spotify] = None,
    lastfm_network: Optional[pylast.LastFMNetwork] = None
) -> list[dict[str, Any]]:
    """Create/update playlist with tracks that have 0 playcount on Last.fm."""
    logger.info("\n" + "="*50)
    logger.info("CREATING UNPLAYED TRACKS PLAYLIST")
    logger.info("="*50)

    matched_tracks = match_spotify_with_lastfm(spotify_library, lastfm_network=lastfm_network)

    # Filter tracks with 0 plays in bulk cache
    unplayed_tracks = [t for t in matched_tracks if t['playcount'] == 0]

    logger.info(f"\nFound {len(unplayed_tracks)} tracks with 0 playcount in cache. Verifying with API...")

    verified_unplayed: list[dict[str, Any]] = []
    lock = threading.Lock()

    def verify_track(track_info: dict[str, Any]) -> None:
        pc = get_lastfm_track_playcount(track_info['artist'], track_info['name'], lastfm_network=lastfm_network)
        if pc == 0:
            with lock:
                verified_unplayed.append(track_info)
        else:
            logger.info(f"  -> False positive: {track_info['artist']} - {track_info['name']} has {pc} plays")

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(verify_track, t) for t in unplayed_tracks]
        completed = 0
        for f in as_completed(futures):
            completed += 1
            if completed % 10 == 0 or completed == len(unplayed_tracks):
                logger.info(f"Verified {completed}/{len(unplayed_tracks)} tracks...")
            f.result()

    logger.info(f"\nFinal count: {len(verified_unplayed)} tracks with verified 0 playcount.")

    # A Spotify playlist can hold a lot of tracks, we'll add them all
    unplayed_track_uris = [t['uri'] for t in verified_unplayed]

    create_or_update_playlist(unplayed_playlist_name, unplayed_track_uris, client=client)
    return verified_unplayed


def main(
    source_playlist_ids: Optional[list[str]] = None,
    unplayed_playlist_name: Optional[str] = None,
    client: Optional[spotipy.Spotify] = None,
    lastfm_network: Optional[pylast.LastFMNetwork] = None
) -> None:
    """Main execution function for generating unplayed playlist."""
    script_start = time.time()
    logger.info(f"Unplayed tracks script started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if source_playlist_ids is None:
        env_source_ids = getenv('SOURCE_PLAYLIST_IDS', '')
        source_playlist_ids = [pid.strip() for pid in env_source_ids.split(',') if pid.strip()]

    target_name = unplayed_playlist_name or getenv('UNPLAYED_PLAYLIST_NAME', 'Unplayed Tracks')

    # 1. Fetch library once
    logger.info("Fetching Spotify library...")
    full_library = get_all_spotify_library_tracks(source_playlist_ids, client=client)

    # 2. Generate unplayed playlist
    operation_start = time.time()
    generate_unplayed_playlist(full_library, target_name, client=client, lastfm_network=lastfm_network)
    operation_time = time.time() - operation_start
    logger.info(f"\nUnplayed tracks playlist update completed in {format_elapsed_time(operation_time)}")

    total_runtime = time.time() - script_start
    logger.info("\n" + "="*50)
    logger.info(f"Script completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Total runtime: {format_elapsed_time(total_runtime)}")
    logger.info("="*50)


if __name__ == "__main__":
    main()
