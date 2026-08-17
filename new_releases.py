from __future__ import annotations

import logging
from datetime import datetime, timedelta
from os import getenv
from typing import Any

import spotipy
from dotenv import load_dotenv

from utils.common import get_spotify_client, setup_logger

load_dotenv()

# Comma-separated playlist IDs to check (in addition to liked songs)
SOURCE_PLAYLIST_IDS = getenv("SOURCE_PLAYLIST_IDS", "")


def get_followed_artists(sp: spotipy.Spotify, logger: logging.Logger) -> list[dict[str, Any]]:
    """Get all artists the user follows with pagination."""
    logger.info("Fetching followed artists...")
    artists: list[dict[str, Any]] = []
    results = sp.current_user_followed_artists(limit=50)
    artists.extend(results["artists"]["items"])

    while results["artists"]["next"]:
        results = sp.next(results["artists"])
        artists.extend(results["artists"]["items"])

    logger.info(f"Found {len(artists)} followed artists")
    return artists


def parse_release_date(release_date: str | None) -> datetime | None:
    """Parse Spotify release date string (YYYY, YYYY-MM, YYYY-MM-DD) into datetime object."""
    if not release_date:
        return None
    date_str = release_date.strip()
    if len(date_str) == 4:
        date_str += "-01-01"
    elif len(date_str) == 7:
        date_str += "-01"
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def get_artist_new_releases(
    sp: spotipy.Spotify, artist_id: str, since_date: datetime, album_type: str = "album,single"
) -> list[dict[str, Any]]:
    """Get albums/singles released by artist since given date."""
    new_releases: list[dict[str, Any]] = []
    seen_album_ids: set[str] = set()

    results = sp.artist_albums(artist_id, album_type=album_type, limit=50)

    while results:
        for album in results.get("items", []):
            album_id = album.get("id")
            if not album_id or album_id in seen_album_ids:
                continue

            release_datetime = parse_release_date(album.get("release_date", ""))
            if release_datetime and release_datetime >= since_date:
                seen_album_ids.add(album_id)
                new_releases.append(album)

        results = sp.next(results) if results.get("next") else None

    return new_releases


def get_saved_tracks(sp: spotipy.Spotify, logger: logging.Logger) -> set[str]:
    """Get all track IDs from user's saved library (liked songs)."""
    logger.info("Fetching liked songs...")
    saved_track_ids: set[str] = set()
    results = sp.current_user_saved_tracks(limit=50)

    for item in results["items"]:
        if item.get("track") and item["track"].get("id"):
            saved_track_ids.add(item["track"]["id"])

    while results["next"]:
        results = sp.next(results)
        for item in results["items"]:
            if item.get("track") and item["track"].get("id"):
                saved_track_ids.add(item["track"]["id"])

    logger.info(f"Found {len(saved_track_ids)} liked songs")
    return saved_track_ids


def get_playlist_tracks(sp: spotipy.Spotify, playlist_id: str, logger: logging.Logger) -> set[str]:
    """Get all track IDs from a specific playlist."""
    logger.info(f"Fetching tracks from playlist ID: {playlist_id}")
    track_ids: set[str] = set()

    try:
        results = sp.playlist_tracks(playlist_id, limit=100)

        for item in results["items"]:
            if item.get("track") and item["track"].get("id"):
                track_ids.add(item["track"]["id"])

        while results["next"]:
            results = sp.next(results)
            for item in results["items"]:
                if item.get("track") and item["track"].get("id"):
                    track_ids.add(item["track"]["id"])

        logger.info(f"Found {len(track_ids)} tracks in playlist")
    except Exception as e:
        logger.exception(f"Error fetching playlist {playlist_id}: {e}")

    return track_ids


def get_all_library_tracks(
    sp: spotipy.Spotify, source_playlist_ids: str, logger: logging.Logger
) -> set[str]:
    """Get all track IDs from liked songs and source playlists."""
    all_tracks: set[str] = set()

    # Get liked songs
    liked_tracks = get_saved_tracks(sp, logger)
    all_tracks.update(liked_tracks)

    # Get tracks from source playlists
    if source_playlist_ids:
        playlist_ids = [pid.strip() for pid in source_playlist_ids.split(",") if pid.strip()]
        logger.info(f"Checking {len(playlist_ids)} source playlist(s)")

        for playlist_id in playlist_ids:
            playlist_tracks = get_playlist_tracks(sp, playlist_id, logger)
            all_tracks.update(playlist_tracks)

    logger.info(f"Total unique tracks in library: {len(all_tracks)}")
    return all_tracks


def get_album_tracks(sp: spotipy.Spotify, album_id: str) -> list[str]:
    """Get all track IDs from an album."""
    tracks: list[dict[str, Any]] = []
    results = sp.album_tracks(album_id, limit=50)
    tracks.extend(results["items"])

    while results["next"]:
        results = sp.next(results)
        tracks.extend(results["items"])

    return [track["id"] for track in tracks if track.get("id")]


def create_or_get_playlist(sp: spotipy.Spotify, playlist_name: str, logger: logging.Logger) -> str:
    """Create a new playlist or get existing one."""
    user_id = sp.current_user()["id"]
    playlists = sp.current_user_playlists(limit=50)

    # Check if playlist already exists
    for playlist in playlists["items"]:
        if playlist["name"] == playlist_name:
            logger.info(f"Using existing playlist: {playlist_name}")
            return playlist["id"]

    # Create new playlist if it doesn't exist
    logger.info(f"Creating new playlist: {playlist_name}")
    playlist = sp.user_playlist_create(
        user_id, playlist_name, public=False, description="New releases from artists I follow"
    )
    return playlist["id"]


def collect_new_release_tracks(
    sp: spotipy.Spotify,
    artists: list[dict[str, Any]],
    since_date: datetime,
    library_tracks: set[str],
    logger: logging.Logger,
) -> set[str]:
    """Check followed artists for new releases and collect tracks not yet in library."""
    new_tracks_to_add: set[str] = set()
    albums_processed: set[str] = set()
    albums_found = 0

    logger.info("")
    logger.info("Checking for new releases...")
    logger.info("-" * 60)

    for i, artist in enumerate(artists, 1):
        logger.info(f"[{i}/{len(artists)}] Checking {artist['name']}...")
        new_releases = get_artist_new_releases(sp, artist["id"], since_date)

        for album in new_releases:
            if album["id"] in albums_processed:
                logger.info(f"  [SKIP] Already processed: {album['name']}")
                continue

            albums_processed.add(album["id"])
            albums_found += 1
            logger.info(f"  [+] Found: {album['name']} ({album['release_date']})")
            album_tracks = get_album_tracks(sp, album["id"])

            new_tracks = [tid for tid in album_tracks if tid not in library_tracks]
            new_tracks_to_add.update(new_tracks)

            if new_tracks:
                logger.info(f"    -> {len(new_tracks)} new track(s) to add")

    logger.info("-" * 60)
    logger.info(f"Summary: Found {albums_found} new release(s)")
    return new_tracks_to_add


def add_tracks_to_playlist(
    sp: spotipy.Spotify, playlist_id: str, new_tracks_to_add: set[str], logger: logging.Logger
) -> None:
    """Add unique new tracks to Spotify playlist in batches of 100."""
    if not new_tracks_to_add:
        logger.info("No new tracks found to add.")
        return

    tracks_list = list(new_tracks_to_add)
    logger.info(f"Adding {len(tracks_list)} new tracks to playlist...")
    for i in range(0, len(tracks_list), 100):
        batch = tracks_list[i : i + 100]
        sp.playlist_add_items(playlist_id, batch)
        logger.info(f"  Added batch {i // 100 + 1} ({len(batch)} tracks)")
    logger.info("[SUCCESS] Successfully added all tracks!")


def main(
    sp_client: spotipy.Spotify | None = None,
    custom_logger: logging.Logger | None = None,
    source_playlist_ids: str | None = None,
    lookback_days_override: int | None = None,
) -> None:
    """Main execution function for tracking Spotify new releases."""
    logger = custom_logger or setup_logger("spotify_releases", "spotify_releases")
    logger.info("=" * 60)
    logger.info("Starting Spotify New Releases Tracker")
    logger.info("=" * 60)

    try:
        logger.info("Initializing Spotify client...")
        sp = sp_client or get_spotify_client()

        now = datetime.now()
        lookback_days = (
            lookback_days_override
            if lookback_days_override is not None
            else int(getenv("LOOKBACK_DAYS", "2"))
        )
        yesterday = now - timedelta(days=lookback_days)
        since_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        logger.info(
            f"Looking for releases since: {since_date.strftime('%Y-%m-%d %H:%M:%S')} ({lookback_days} days lookback)"
        )

        # Get followed artists
        artists = get_followed_artists(sp, logger)

        # Create or get playlist
        playlist_name = "The News"
        playlist_id = create_or_get_playlist(sp, playlist_name, logger)

        # Get all library tracks (liked songs + source playlists)
        p_ids = source_playlist_ids if source_playlist_ids is not None else SOURCE_PLAYLIST_IDS
        library_tracks = get_all_library_tracks(sp, p_ids, logger)

        # Add tracks from the target playlist itself to exclude them
        logger.info(
            f"Fetching tracks from target playlist '{playlist_name}' to avoid duplicates..."
        )
        target_playlist_tracks = get_playlist_tracks(sp, playlist_id, logger)
        library_tracks.update(target_playlist_tracks)
        logger.info(f"Total tracks to exclude: {len(library_tracks)}")

        # Collect new releases and add to playlist
        new_tracks = collect_new_release_tracks(sp, artists, since_date, library_tracks, logger)
        add_tracks_to_playlist(sp, playlist_id, new_tracks, logger)

        logger.info("=" * 60)
        logger.info("Completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()
