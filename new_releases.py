import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime, timedelta
from os import getenv
from dotenv import load_dotenv
import logging
from pathlib import Path

load_dotenv()

# Spotify API credentials
SPOTIPY_CLIENT_ID = getenv('CLIENT_ID')
SPOTIPY_CLIENT_SECRET = getenv('CLIENT_SECRET')
SPOTIPY_REDIRECT_URI = getenv('REDIRECT_URI')

# Comma-separated playlist IDs to check (in addition to liked songs)
SOURCE_PLAYLIST_IDS = getenv('SOURCE_PLAYLIST_IDS', '')

# Scopes needed for the script
SCOPE = 'user-follow-read user-library-read playlist-modify-public playlist-modify-private'

def setup_logging():
    """Set up logging to file and console"""
    # Create logs directory if it doesn't exist
    logs_dir = Path('logs')
    logs_dir.mkdir(exist_ok=True)

    # Create log filename with timestamp
    log_filename = logs_dir / f"spotify_releases_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # Configure logging with UTF-8 encoding
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    return logging.getLogger(__name__)

def get_spotify_client():
    """Initialize and return Spotify client with OAuth"""
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SCOPE
    ))

def get_followed_artists(sp, logger):
    """Get all artists the user follows"""
    logger.info("Fetching followed artists...")
    artists = []
    results = sp.current_user_followed_artists(limit=50)
    artists.extend(results['artists']['items'])

    while results['artists']['next']:
        results = sp.next(results['artists'])
        artists.extend(results['artists']['items'])

    logger.info(f"Found {len(artists)} followed artists")
    return artists

def get_artist_new_releases(sp, artist_id, since_date):
    """Get albums/singles released by artist since given date"""
    new_releases = []
    results = sp.artist_albums(artist_id, album_type='album,single', limit=50)

    for album in results['items']:
        release_date = album['release_date']
        # Handle different date formats (YYYY, YYYY-MM, YYYY-MM-DD)
        if len(release_date) == 4:  # Year only
            release_date += '-01-01'
        elif len(release_date) == 7:  # Year-Month
            release_date += '-01'

        release_datetime = datetime.strptime(release_date, '%Y-%m-%d')

        if release_datetime >= since_date:
            new_releases.append(album)

    return new_releases

def get_saved_tracks(sp, logger):
    """Get all track IDs from user's saved library (liked songs)"""
    logger.info("Fetching liked songs...")
    saved_track_ids = set()
    results = sp.current_user_saved_tracks(limit=50)

    for item in results['items']:
        saved_track_ids.add(item['track']['id'])

    while results['next']:
        results = sp.next(results)
        for item in results['items']:
            saved_track_ids.add(item['track']['id'])

    logger.info(f"Found {len(saved_track_ids)} liked songs")
    return saved_track_ids

def get_playlist_tracks(sp, playlist_id, logger):
    """Get all track IDs from a specific playlist"""
    logger.info(f"Fetching tracks from playlist ID: {playlist_id}")
    track_ids = set()

    try:
        results = sp.playlist_tracks(playlist_id, limit=100)

        for item in results['items']:
            if item['track'] and item['track']['id']:
                track_ids.add(item['track']['id'])

        while results['next']:
            results = sp.next(results)
            for item in results['items']:
                if item['track'] and item['track']['id']:
                    track_ids.add(item['track']['id'])

        logger.info(f"Found {len(track_ids)} tracks in playlist")
    except Exception as e:
        logger.error(f"Error fetching playlist {playlist_id}: {e}")

    return track_ids

def get_all_library_tracks(sp, source_playlist_ids, logger):
    """Get all track IDs from liked songs and source playlists"""
    all_tracks = set()

    # Get liked songs
    liked_tracks = get_saved_tracks(sp, logger)
    all_tracks.update(liked_tracks)

    # Get tracks from source playlists
    if source_playlist_ids:
        playlist_ids = [pid.strip() for pid in source_playlist_ids.split(',') if pid.strip()]
        logger.info(f"Checking {len(playlist_ids)} source playlist(s)")

        for playlist_id in playlist_ids:
            playlist_tracks = get_playlist_tracks(sp, playlist_id, logger)
            all_tracks.update(playlist_tracks)

    logger.info(f"Total unique tracks in library: {len(all_tracks)}")
    return all_tracks

def get_album_tracks(sp, album_id):
    """Get all track IDs from an album"""
    tracks = []
    results = sp.album_tracks(album_id, limit=50)
    tracks.extend(results['items'])

    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])

    return [track['id'] for track in tracks]

def create_or_get_playlist(sp, playlist_name, logger):
    """Create a new playlist or get existing one"""
    user_id = sp.current_user()['id']
    playlists = sp.current_user_playlists(limit=50)

    # Check if playlist already exists
    for playlist in playlists['items']:
        if playlist['name'] == playlist_name:
            logger.info(f"Using existing playlist: {playlist_name}")
            return playlist['id']

    # Create new playlist if it doesn't exist
    logger.info(f"Creating new playlist: {playlist_name}")
    playlist = sp.user_playlist_create(
        user_id,
        playlist_name,
        public=False,
        description='New releases from artists I follow'
    )
    return playlist['id']

def main():
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("Starting Spotify New Releases Tracker")
    logger.info("=" * 60)

    try:
        logger.info("Initializing Spotify client...")
        sp = get_spotify_client()

        # Get date from 24 hours ago
        one_day_ago = datetime.now() - timedelta(hours=24)
        logger.info(f"Looking for releases since: {one_day_ago.strftime('%Y-%m-%d %H:%M:%S')}")

        # Get followed artists
        artists = get_followed_artists(sp, logger)

        # Create or get playlist
        playlist_name = "The News"
        playlist_id = create_or_get_playlist(sp, playlist_name, logger)

        # Get all library tracks (liked songs + source playlists)
        library_tracks = get_all_library_tracks(sp, SOURCE_PLAYLIST_IDS, logger)

        # Add tracks from the target playlist itself to exclude them
        logger.info(f"Fetching tracks from target playlist '{playlist_name}' to avoid duplicates...")
        target_playlist_tracks = get_playlist_tracks(sp, playlist_id, logger)
        library_tracks.update(target_playlist_tracks)
        logger.info(f"Total tracks to exclude: {len(library_tracks)}")

        # Find new releases
        new_tracks_to_add = set()  # Use set to avoid duplicates
        albums_processed = set()  # Track processed albums to avoid duplicates
        albums_found = 0

        logger.info("")
        logger.info("Checking for new releases...")
        logger.info("-" * 60)

        for i, artist in enumerate(artists, 1):
            logger.info(f"[{i}/{len(artists)}] Checking {artist['name']}...")

            new_releases = get_artist_new_releases(sp, artist['id'], one_day_ago)

            for album in new_releases:
                # Skip if we've already processed this album
                if album['id'] in albums_processed:
                    logger.info(f"  [SKIP] Already processed: {album['name']}")
                    continue

                albums_processed.add(album['id'])
                albums_found += 1
                logger.info(f"  [+] Found: {album['name']} ({album['release_date']})")
                album_tracks = get_album_tracks(sp, album['id'])

                # Filter out tracks already in library
                new_tracks = [tid for tid in album_tracks if tid not in library_tracks]
                new_tracks_to_add.update(new_tracks)

                if new_tracks:
                    logger.info(f"    -> {len(new_tracks)} new track(s) to add")

        logger.info("-" * 60)
        logger.info(f"Summary: Found {albums_found} new release(s)")

        # Add tracks to playlist (Spotify API limits to 100 tracks per request)
        if new_tracks_to_add:
            # Convert set to list for batch processing
            tracks_list = list(new_tracks_to_add)
            logger.info(f"Adding {len(tracks_list)} new tracks to playlist...")
            for i in range(0, len(tracks_list), 100):
                batch = tracks_list[i:i+100]
                sp.playlist_add_items(playlist_id, batch)
                logger.info(f"  Added batch {i//100 + 1} ({len(batch)} tracks)")
            logger.info("[SUCCESS] Successfully added all tracks!")
        else:
            logger.info("No new tracks found to add.")

        logger.info("=" * 60)
        logger.info("Completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()
