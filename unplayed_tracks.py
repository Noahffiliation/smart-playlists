import time
from datetime import datetime
from os import getenv
from dotenv import load_dotenv

from smart_playlists import (
    get_all_spotify_library_tracks,
    match_spotify_with_lastfm,
    create_or_update_playlist,
    logger,
    format_elapsed_time
)

load_dotenv()

def generate_unplayed_playlist(spotify_library, unplayed_playlist_name):
    """Create/update playlist with tracks that have 0 playcount on Last.fm"""
    logger.info("\n" + "="*50)
    logger.info("CREATING UNPLAYED TRACKS PLAYLIST")
    logger.info("="*50)

    matched_tracks = match_spotify_with_lastfm(spotify_library)

    # Filter tracks with 0 plays
    unplayed_tracks = [t for t in matched_tracks if t['playcount'] == 0]

    logger.info(f"\nFound {len(unplayed_tracks)} tracks with 0 playcount.")

    # A Spotify playlist can hold a lot of tracks, we'll add them all
    unplayed_track_uris = [t['uri'] for t in unplayed_tracks]

    create_or_update_playlist(unplayed_playlist_name, unplayed_track_uris)

def main():
    script_start = time.time()
    logger.info(f"Unplayed tracks script started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Ensure SOURCE_PLAYLIST_IDS is properly parsed
    env_source_ids = getenv('SOURCE_PLAYLIST_IDS', '')
    SOURCE_PLAYLIST_IDS = [pid.strip() for pid in env_source_ids.split(',')] if env_source_ids else []

    UNPLAYED_PLAYLIST_NAME = getenv('UNPLAYED_PLAYLIST_NAME', 'Unplayed Tracks')

    # 1. Fetch library once
    logger.info("Fetching Spotify library...")
    full_library = get_all_spotify_library_tracks(SOURCE_PLAYLIST_IDS)

    # 2. Generate unplayed playlist
    operation_start = time.time()
    generate_unplayed_playlist(full_library, UNPLAYED_PLAYLIST_NAME)
    operation_time = time.time() - operation_start
    logger.info(f"\\nUnplayed tracks playlist update completed in {format_elapsed_time(operation_time)}")

    total_runtime = time.time() - script_start
    logger.info("\\n" + "="*50)
    logger.info(f"Script completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Total runtime: {format_elapsed_time(total_runtime)}")
    logger.info("="*50)

if __name__ == "__main__":
    main()
