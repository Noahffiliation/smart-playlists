from __future__ import annotations

import random
import re
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from functools import wraps
from os import getenv
from typing import Any

import pylast
import spotipy
from dotenv import load_dotenv

from utils.common import format_elapsed_time, get_spotify_client, setup_logger

load_dotenv()

CLIENT_ID = getenv("CLIENT_ID")
CLIENT_SECRET = getenv("CLIENT_SECRET")
REDIRECT_URI = getenv("REDIRECT_URI")
LASTFM_API_KEY = getenv("LASTFM_API_KEY")
LASTFM_USERNAME = getenv("LASTFM_USERNAME")


def get_lastfm_client(
    api_key: str | None = None, username: str | None = None
) -> pylast.LastFMNetwork:
    """Initialize and return Last.fm client."""
    return pylast.LastFMNetwork(
        api_key=api_key or getenv("LASTFM_API_KEY") or "",
        username=username or getenv("LASTFM_USERNAME") or "",
    )


# Module-level instances for direct access and backward-compatible test fixtures
sp: Any = None
try:
    sp = get_spotify_client()
except Exception:
    sp = None

network: Any = None
try:
    network = get_lastfm_client()
except Exception:
    network = None

date_format = "%Y-%m-%dT%H:%M:%SZ"
library_lock = threading.Lock()

# Setup logger using common utility
logger = setup_logger("smart_playlists", "smart_playlists")


def normalize_track_title(title: str | None) -> str:
    """Normalize a track title or artist name by stripping remaster/feat/live tags and extra whitespace."""
    if not title:
        return ""
    text = title.lower().strip()

    metadata_keywords = (
        "remaster",
        "live",
        "deluxe",
        "edition",
        "bonus",
        "radio edit",
        "original mix",
        "single version",
        "mono",
        "stereo",
        "mix",
        "feat",
        "featuring",
        "ft",
    )

    def _strip_bracket_tags(match: re.Match) -> str:
        content = match.group(0)
        if any(kw in content for kw in metadata_keywords):
            return ""
        return content

    # Strip bracketed metadata tags (e.g. "(2011 Remaster)", "[Live at Wembley]", "(feat. Artist)")
    text = re.sub(r"[\(\[\{][^)\]\}]*[\)\]\}]", _strip_bracket_tags, text)

    # Strip trailing hyphen tags (e.g. " - Remastered", " - feat. Artist")
    if " - " in text:
        parts = text.split(" - ")
        if len(parts) > 1 and any(kw in parts[-1] for kw in metadata_keywords):
            text = " - ".join(parts[:-1])

    # Strip quotation marks
    text = re.sub(r'["\']', "", text)
    # Normalize multiple whitespaces
    return re.sub(r"\s+", " ", text).strip()


def retry_on_rate_limit(max_retries: int = 3, initial_delay: float = 1.0) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            retries = 0
            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                except pylast.WSError as e:
                    if str(e.status) == "29":  # Rate limit exceeded
                        retries += 1
                        if retries > max_retries:
                            logger.error(
                                f"Last.fm rate limit exceeded after {max_retries} retries."
                            )
                            raise
                        wait_time = initial_delay * (2 ** (retries - 1))
                        logger.warning(f"Last.fm rate limit exceeded. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logger.exception(f"Last.fm API error: {e}")
                        raise
                except Exception as e:
                    logger.exception(f"Last.fm API error: {e}")
                    raise
            return None

        return wrapper

    return decorator


def get_all_playlist_tracks(
    playlist_id: str, client: spotipy.Spotify | None = None
) -> list[dict[str, Any]]:
    """Fetch all tracks from a Spotify playlist with pagination."""
    spotify = client or sp or get_spotify_client()
    tracks: list[dict[str, Any]] = []
    offset = 0
    limit = 100
    while True:
        try:
            results = spotify.playlist_tracks(playlist_id, offset=offset, limit=limit)
            tracks.extend([item for item in results["items"] if item and item.get("track")])
            if not results.get("next"):
                break
            offset += limit
        except Exception as e:
            logger.exception(f"Error fetching playlist tracks: {e}")
            break
    return tracks


def get_liked_songs(client: spotipy.Spotify | None = None) -> list[dict[str, Any]]:
    """Fetch all saved tracks for the current user."""
    spotify = client or sp or get_spotify_client()
    liked_tracks: list[dict[str, Any]] = []
    offset = 0
    limit = 50
    while True:
        results = spotify.current_user_saved_tracks(limit=limit, offset=offset)
        if not results["items"]:
            break
        liked_tracks.extend(
            [{"track": item["track"], "added_at": item["added_at"]} for item in results["items"]]
        )
        offset += limit
        if len(liked_tracks) > 0 and len(liked_tracks) % 500 == 0:
            logger.info(f"Fetched {len(liked_tracks)} liked songs...")
    return liked_tracks


def update_recent_tracks_playlist(
    full_library: dict[str, dict[str, Any]],
    target_playlist_name: str,
    client: spotipy.Spotify | None = None,
) -> None:
    """Update Recently Added playlist based on pre-fetched library."""
    logger.info("\n" + "=" * 50)
    logger.info("UPDATING RECENT TRACKS PLAYLIST")
    logger.info("=" * 50)

    # Filter for tracks added in last 30 days
    one_month_ago = datetime.now() - timedelta(days=30)
    logger.info(f"Filtering for tracks added since {one_month_ago.date()}")

    recent_tracks = [
        track
        for track in full_library.values()
        if track["added_at"] and track["added_at"] > one_month_ago
    ]

    # Sort by added_at descending
    sorted_tracks = sorted(recent_tracks, key=lambda x: x["added_at"], reverse=True)
    recent_uris = [track["uri"] for track in sorted_tracks]

    # Update the playlist
    create_or_update_playlist(target_playlist_name, recent_uris, client=client)


def _create_track_dict(
    track: dict[str, Any] | None, added_at: str | datetime | None = None
) -> dict[str, Any] | None:
    """Create a standardized track dictionary with normalized key."""
    if not track or not track.get("uri"):
        return None

    artist = track["artists"][0]["name"] if track.get("artists") else "Unknown"
    name = track.get("name", "Unknown")

    dt_added_at = None
    if added_at:
        if isinstance(added_at, str):
            dt_added_at = datetime.strptime(added_at, date_format)
        else:
            dt_added_at = added_at

    return {
        "uri": track["uri"],
        "name": name,
        "artist": artist,
        "added_at": dt_added_at,
        "key": f"{normalize_track_title(artist)}|||{normalize_track_title(name)}",
    }


def _update_library_with_track_item(
    all_tracks: dict[str, dict[str, Any]], item: dict[str, Any] | None
) -> None:
    """Update library map with a single track item, keeping the oldest added_at date."""
    if not item or not item.get("track"):
        return

    track_dict = _create_track_dict(item["track"], item.get("added_at"))
    if not track_dict:
        return

    uri = track_dict["uri"]
    new_date = track_dict["added_at"]

    with library_lock:
        if uri not in all_tracks:
            all_tracks[uri] = track_dict
            return

        # If it exists, check if the new date is older
        existing_date = all_tracks[uri].get("added_at")
        if new_date and (not existing_date or new_date < existing_date):
            all_tracks[uri]["added_at"] = new_date


def _add_liked_songs_to_library(
    all_tracks: dict[str, dict[str, Any]], client: spotipy.Spotify | None = None
) -> None:
    """Add liked songs to the track library, keeping the oldest added_at date."""
    logger.info("Fetching liked songs...")
    liked = get_liked_songs(client=client)

    for item in liked:
        _update_library_with_track_item(all_tracks, item)

    logger.info(f"Unique tracks after Liked Songs: {len(all_tracks)}")


def _add_playlist_tracks_to_library(
    all_tracks: dict[str, dict[str, Any]],
    playlist_ids: list[str],
    client: spotipy.Spotify | None = None,
) -> None:
    """Add playlist tracks to the track library, keeping the oldest added_at date."""
    spotify = client or sp or get_spotify_client()
    for playlist_id in playlist_ids:
        try:
            playlist = spotify.playlist(playlist_id)
            logger.info(f"Fetching tracks from: {playlist['name']}")
            tracks = get_all_playlist_tracks(playlist_id, client=spotify)

            for item in tracks:
                _update_library_with_track_item(all_tracks, item)
        except Exception as e:
            logger.exception(f"Error processing playlist {playlist_id}: {e}")


def get_all_spotify_library_tracks(
    playlist_ids: list[str], client: spotipy.Spotify | None = None
) -> dict[str, dict[str, Any]]:
    """Get all unique tracks from Spotify library using parallel fetching."""
    spotify = client or sp or get_spotify_client()
    logger.info("\n=== Building Spotify Library ===")
    start_time = time.time()

    # Pre-validate/refresh auth token before spinning up worker threads
    try:
        if spotify.auth_manager:
            spotify.auth_manager.get_access_token(as_dict=False)
    except Exception as e:
        logger.warning(f"Could not pre-refresh Spotify auth token: {e}")

    all_tracks: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        # Submit task for liked songs
        future_to_type = {
            executor.submit(_add_liked_songs_to_library, all_tracks, spotify): "liked_songs"
        }

        # Submit tasks for each playlist
        for playlist_id in playlist_ids:
            future_to_type[
                executor.submit(_add_playlist_tracks_to_library, all_tracks, [playlist_id], spotify)
            ] = f"playlist_{playlist_id}"

        for future in as_completed(future_to_type):
            task_type = future_to_type[future]
            try:
                future.result()
            except Exception as e:
                logger.exception(f"Task {task_type} generated an exception: {e}")

    elapsed = time.time() - start_time
    logger.info(f"\nTotal unique tracks in library: {len(all_tracks)}")
    logger.info(f"Library build completed in {format_elapsed_time(elapsed)}\n")
    return all_tracks


@retry_on_rate_limit()
def get_lastfm_track_playcount(
    artist: str, track: str, lastfm_network: pylast.LastFMNetwork | None = None
) -> int:
    """Get playcount for a specific track from Last.fm."""
    net = lastfm_network or network or get_lastfm_client()
    try:
        lastfm_track = net.get_track(artist, track)
        playcount = lastfm_track.get_userplaycount()
        return playcount if playcount else 0
    except Exception:
        return 0


def get_all_lastfm_playcounts(
    lastfm_network: pylast.LastFMNetwork | None = None, username: str | None = None
) -> dict[str, int]:
    """Fetch all playcounts from Last.fm library in bulk using streaming API."""
    logger.info("=== Fetching all Last.fm playcounts in bulk ===")
    net = lastfm_network or network or get_lastfm_client()
    user_name = username or LASTFM_USERNAME or getenv("LASTFM_USERNAME") or ""
    user = net.get_user(user_name)
    playcounts: dict[str, int] = {}

    try:
        # pylast streaming generator handles pagination automatically
        top_tracks = user.get_top_tracks(period=pylast.PERIOD_OVERALL, stream=True)

        for top_track in top_tracks:
            artist = normalize_track_title(top_track.item.artist.name)
            track_name = normalize_track_title(top_track.item.title)
            key = f"{artist}|||{track_name}"

            playcounts[key] = int(top_track.weight)

            if len(playcounts) > 0 and len(playcounts) % 500 == 0:
                logger.info(f"Cached {len(playcounts)} tracks...")

    except pylast.WSError as e:
        if str(e.status) == "29":  # Rate limit exceeded
            logger.warning("Rate limit hit during bulk fetch.")
        else:
            logger.exception(f"Error during bulk fetch: {e}")
    except Exception as e:
        logger.exception(f"Error during bulk fetch: {e}")

    logger.info(f"Successfully cached {len(playcounts)} tracks from Last.fm")
    return playcounts


def match_spotify_with_lastfm(
    spotify_tracks: dict[str, dict[str, Any]], lastfm_network: pylast.LastFMNetwork | None = None
) -> list[dict[str, Any]]:
    """Match Spotify tracks with Last.fm playcounts using bulk-fetched data and normalized matching."""
    logger.info("=== Matching Spotify tracks with Last.fm scrobbles ===")

    # Pre-fetch all Last.fm playcounts
    lastfm_library = get_all_lastfm_playcounts(lastfm_network=lastfm_network)

    matched_tracks: list[dict[str, Any]] = []
    total = len(spotify_tracks)
    missing_tracks: list[dict[str, Any]] = []

    for idx, (uri, track_data) in enumerate(spotify_tracks.items(), 1):
        artist = normalize_track_title(track_data["artist"])
        name = normalize_track_title(track_data["name"])
        key = f"{artist}|||{name}"

        playcount = lastfm_library.get(key)

        if playcount is None:
            playcount = 0
            missing_tracks.append(track_data)

        matched_tracks.append(
            {
                "uri": uri,
                "name": track_data["name"],
                "artist": track_data["artist"],
                "playcount": playcount,
            }
        )

        if idx % 100 == 0:
            logger.info(f"Processed {idx}/{total} tracks...")

    logger.info(f"\nMatched {len(matched_tracks)} tracks with Last.fm data")
    if missing_tracks:
        logger.info(
            f"Note: {len(missing_tracks)} tracks were not found in Last.fm library (0 plays assumed)"
        )

    return matched_tracks


def _get_or_create_playlist(spotify: spotipy.Spotify, playlist_name: str) -> str:
    """Find existing playlist and clear it, or create a new public playlist."""
    playlists = spotify.current_user_playlists()["items"]
    target_playlist = next((p for p in playlists if p["name"] == playlist_name), None)

    if target_playlist:
        spotify.playlist_replace_items(target_playlist["id"], [])
        return target_playlist["id"]

    user_id = spotify.current_user()["id"]
    new_playlist = spotify.user_playlist_create(user_id, playlist_name, public=True)
    return new_playlist["id"]


def _populate_playlist_tracks(
    spotify: spotipy.Spotify, playlist_id: str, playlist_name: str, track_uris: list[str]
) -> None:
    """Populate playlist with tracks in batches of 100."""
    if not track_uris:
        logger.info(f"No tracks to add to '{playlist_name}'")
        return

    batch_size = 100
    for i in range(0, len(track_uris), batch_size):
        batch = track_uris[i : i + batch_size]
        spotify.playlist_add_items(playlist_id, batch)
    logger.info(f"Updated '{playlist_name}' with {len(track_uris)} tracks")


def create_or_update_playlist(
    playlist_name: str, track_uris: list[str], client: spotipy.Spotify | None = None
) -> None:
    """Create or update a playlist with given tracks with automatic retry."""
    spotify = client or sp or get_spotify_client()
    for attempt in range(3):
        try:
            playlist_id = _get_or_create_playlist(spotify, playlist_name)
            _populate_playlist_tracks(spotify, playlist_id, playlist_name, track_uris)
            return
        except Exception as e:
            if attempt == 2:
                logger.exception(f"Error updating playlist '{playlist_name}' after 3 attempts: {e}")
                raise
            logger.warning(
                f"Connection issue updating playlist '{playlist_name}' (attempt {attempt + 1}/3): {e}. Retrying..."
            )
            time.sleep(1)


def update_playcount_playlists(
    spotify_library: dict[str, dict[str, Any]],
    top_playlist_name: str,
    bottom_playlist_name: str,
    client: spotipy.Spotify | None = None,
    lastfm_network: pylast.LastFMNetwork | None = None,
) -> None:
    """Create/update playlists using pre-fetched library."""
    logger.info("\n" + "=" * 50)
    logger.info("CREATING PLAYCOUNT-BASED PLAYLISTS")
    logger.info("=" * 50)

    matched_tracks = match_spotify_with_lastfm(spotify_library, lastfm_network=lastfm_network)

    # Filter tracks with at least 1 play
    played_tracks = [t for t in matched_tracks if t["playcount"]]

    # Sort by playcount descending for top 25
    top_25 = sorted(played_tracks, key=lambda x: x["playcount"], reverse=True)[:25]

    # Group and shuffle for bottom 25 variety
    playcount_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for track in played_tracks:
        playcount_groups[track["playcount"]].append(track)

    bottom_tracks: list[dict[str, Any]] = []
    # Sort playcounts ascending
    for pc in sorted(playcount_groups.keys()):
        group = playcount_groups[pc]
        random.SystemRandom().shuffle(group)
        bottom_tracks.extend(group)
        if len(bottom_tracks) >= 25:
            break

    bottom_25 = bottom_tracks[:25]

    # Display and create top 25 playlist
    logger.info("\n=== Top 25 Most Played Tracks ===")
    for i, track in enumerate(top_25, 1):
        logger.info(f"{i}. {track['artist']} - {track['name']} ({track['playcount']} plays)")

    top_track_uris = [t["uri"] for t in top_25]
    create_or_update_playlist(top_playlist_name, top_track_uris, client=client)

    # Display and create bottom 25 playlist
    logger.info("\n=== Top 25 Least Played Tracks ===")
    for i, track in enumerate(bottom_25, 1):
        logger.info(f"{i}. {track['artist']} - {track['name']} ({track['playcount']} plays)")

    bottom_track_uris = [t["uri"] for t in bottom_25]
    create_or_update_playlist(bottom_playlist_name, bottom_track_uris, client=client)


def main(
    source_playlist_ids: list[str] | None = None,
    target_playlist_name: str | None = None,
    top_25_playlist_name: str | None = None,
    bottom_25_playlist_name: str | None = None,
    client: spotipy.Spotify | None = None,
    lastfm_network: pylast.LastFMNetwork | None = None,
) -> None:
    """Main execution function for playlist synchronization."""
    script_start = time.time()
    logger.info(f"Script started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if source_playlist_ids is None:
        env_source_ids = getenv("SOURCE_PLAYLIST_IDS", "")
        source_playlist_ids = [pid.strip() for pid in env_source_ids.split(",") if pid.strip()]

    target_name = target_playlist_name or getenv("TARGET_PLAYLIST_NAME") or "Recently Added"
    top_name = top_25_playlist_name or getenv("TOP_25_PLAYLIST_NAME") or "Top 25 Most Played"
    bottom_name = (
        bottom_25_playlist_name or getenv("BOTTOM_25_PLAYLIST_NAME") or "Top 25 Least Played"
    )

    # 1. Fetch library once
    full_library = get_all_spotify_library_tracks(source_playlist_ids, client=client)

    # 2. Update recent tracks playlist
    operation_start = time.time()
    update_recent_tracks_playlist(full_library, target_name, client=client)
    operation_time = time.time() - operation_start
    logger.info(f"\nRecent tracks update completed in {format_elapsed_time(operation_time)}")

    # 3. Update playcount playlists
    operation_start = time.time()
    update_playcount_playlists(
        full_library, top_name, bottom_name, client=client, lastfm_network=lastfm_network
    )
    operation_time = time.time() - operation_start
    logger.info(f"\nPlaycount update completed in {format_elapsed_time(operation_time)}")

    total_runtime = time.time() - script_start
    logger.info("\n" + "=" * 50)
    logger.info(f"Script completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Total runtime: {format_elapsed_time(total_runtime)}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
