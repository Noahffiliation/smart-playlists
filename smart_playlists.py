import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime, timedelta
from os import getenv, makedirs
from os.path import join
from dotenv import load_dotenv
import time
import pylast
import logging
import random
from collections import defaultdict
from functools import wraps

load_dotenv()

CLIENT_ID = getenv('CLIENT_ID')
CLIENT_SECRET = getenv('CLIENT_SECRET')
REDIRECT_URI = getenv('REDIRECT_URI')
LASTFM_API_KEY = getenv('LASTFM_API_KEY')
LASTFM_USERNAME = getenv('LASTFM_USERNAME')

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope='playlist-modify-public playlist-read-private user-library-read'
))

network = pylast.LastFMNetwork(
    api_key=LASTFM_API_KEY,
    username=LASTFM_USERNAME
)

date_format = '%Y-%m-%dT%H:%M:%SZ'


class PrintAndLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            print(msg)
        except UnicodeEncodeError:
            # Fallback to ascii if terminal doesn't support Unicode
            msg = self.format(record).encode('ascii', 'replace').decode()
            print(msg)

# Create logs directory if it doesn't exist
LOGS_DIR = join('logs')
makedirs(LOGS_DIR, exist_ok=True)

# Configure logging with timestamp in filename
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
log_file = join(LOGS_DIR, f'smart_playlists_{timestamp}.log')
formatter = logging.Formatter('%(message)s')

# File handler with unique filename and UTF-8 encoding
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setFormatter(formatter)

# Custom print handler
print_handler = PrintAndLogHandler()
print_handler.setFormatter(formatter)

# Setup logger
logger = logging.getLogger('smart_playlists')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(print_handler)

def retry_on_rate_limit(max_retries=3, initial_delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                except pylast.WSError as e:
                    if str(e.status) == "29":  # Rate limit exceeded
                        retries += 1
                        if retries > max_retries:
                            logger.error(f"Last.fm rate limit exceeded after {max_retries} retries.")
                            raise
                        wait_time = initial_delay * (2 ** (retries - 1))
                        logger.warning(f"Last.fm rate limit exceeded. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Last.fm API error: {e}")
                        raise
                except Exception as e:
                    logger.error(f"Last.fm API error: {e}")
                    raise
            return None
        return wrapper
    return decorator

def get_all_playlist_tracks(playlist_id):
    tracks = []
    offset = 0
    limit = 100
    while True:
        try:
            results = sp.playlist_tracks(playlist_id, offset=offset, limit=limit)
            tracks.extend([item for item in results['items'] if item and item.get('track')])
            if not results['next']:
                break
            offset += limit
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"Error fetching playlist tracks: {e}")
            break
    return tracks

def get_liked_songs():
    liked_tracks = []
    offset = 0
    limit = 50
    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        if not results['items']:
            break
        liked_tracks.extend([{
            'track': item['track'],
            'added_at': item['added_at']
        } for item in results['items']])
        offset += limit
    return liked_tracks

def get_recent_tracks_from_playlists(playlist_ids):
    one_month_ago = datetime.now() - timedelta(days=30)
    logger.info(f"Finding tracks added since {one_month_ago.date()}")
    playlist_tracks = _get_recent_playlist_tracks(playlist_ids, one_month_ago)
    liked_tracks = _get_recent_liked_tracks(one_month_ago)
    all_tracks = playlist_tracks + liked_tracks
    return _process_and_sort_tracks(all_tracks)

def _get_recent_playlist_tracks(playlist_ids, cutoff_date):
    recent_tracks = []
    for playlist_id in playlist_ids:
        try:
            playlist = sp.playlist(playlist_id)
            logger.info(f"Processing playlist: {playlist['name']}")
            tracks = get_all_playlist_tracks(playlist_id)
            recent_tracks.extend(_process_playlist_tracks(tracks, cutoff_date))
        except Exception as e:
            logger.error(f"Error processing playlist {playlist_id}: {e}")
    return recent_tracks

def _process_playlist_tracks(tracks, cutoff_date):
    processed_tracks = []
    for item in tracks:
        try:
            track_data = _extract_track_data(item, cutoff_date)
            if track_data:
                processed_tracks.append(track_data)
        except Exception as e:
            logger.error(f"Error processing track: {e}")
    return processed_tracks

def _extract_track_data(item, cutoff_date):
    if not item or not item.get('track') or not item.get('added_at'):
        logger.warning(f"Skipping invalid track item: {item}")
        return None
    added_at = datetime.strptime(item['added_at'], date_format)
    if added_at <= cutoff_date:
        return None
    return {
        'uri': item['track']['uri'],
        'added_at': added_at,
        'name': item['track'].get('name', 'Unknown'),
        'artist': item['track']['artists'][0]['name'] if item['track'].get('artists') else 'Unknown'
    }

def _get_recent_liked_tracks(cutoff_date):
    logger.info("Fetching tracks from Liked Songs")
    liked_tracks = get_liked_songs()
    return [
        {'uri': item['track']['uri'], 'added_at': datetime.strptime(item['added_at'], date_format)}
        for item in liked_tracks
        if datetime.strptime(item['added_at'], date_format) > cutoff_date
    ]

def _process_and_sort_tracks(tracks):
    unique_tracks = {}
    for track in tracks:
        uri = track['uri']
        if uri not in unique_tracks or track['added_at'] > unique_tracks[uri]['added_at']:
            unique_tracks[uri] = track
    return [track['uri'] for track in sorted(
        unique_tracks.values(),
        key=lambda x: x['added_at'],
        reverse=True
    )]

def update_recent_tracks_playlist(source_playlist_ids, target_playlist_name):
    recent_tracks = get_recent_tracks_from_playlists(source_playlist_ids)
    playlists = sp.current_user_playlists()['items']
    target_playlist = next((p for p in playlists if p['name'] == target_playlist_name), None)
    if target_playlist:
        sp.playlist_replace_items(target_playlist['id'], [])
    else:
        user_id = sp.current_user()['id']
        target_playlist = sp.user_playlist_create(user_id, target_playlist_name, public=True)
    if recent_tracks:
        batch_size = 100
        for i in range(0, len(recent_tracks), batch_size):
            batch = recent_tracks[i:i + batch_size]
            sp.playlist_add_items(target_playlist['id'], batch)
            logger.info(f"Added batch of {len(batch)} tracks")
        logger.info(f"Updated {target_playlist_name} with {len(recent_tracks)} recent tracks")
    else:
        logger.info("No recent tracks found to add.")

def _create_track_dict(track):
    """Create a standardized track dictionary"""
    if not track or not track.get('uri'):
        return None

    artist = track['artists'][0]['name'] if track.get('artists') else 'Unknown'
    name = track.get('name', 'Unknown')

    return {
        'uri': track['uri'],
        'name': name,
        'artist': artist,
        'key': f"{artist.lower()}|||{name.lower()}"
    }

def _add_liked_songs_to_library(all_tracks):
    """Add liked songs to the track library"""
    logger.info("Fetching liked songs...")
    liked = get_liked_songs()

    for item in liked:
        track_dict = _create_track_dict(item['track'])
        if track_dict:
            all_tracks[track_dict['uri']] = track_dict

    logger.info(f"Found {len(all_tracks)} liked songs")

def _add_playlist_tracks_to_library(all_tracks, playlist_ids):
    """Add playlist tracks to the track library"""
    for playlist_id in playlist_ids:
        try:
            playlist = sp.playlist(playlist_id)
            logger.info(f"Fetching tracks from: {playlist['name']}")
            tracks = get_all_playlist_tracks(playlist_id)

            for item in tracks:
                if item and item.get('track'):
                    track_dict = _create_track_dict(item['track'])
                    if track_dict and track_dict['uri'] not in all_tracks:
                        all_tracks[track_dict['uri']] = track_dict
        except Exception as e:
            logger.error(f"Error processing playlist {playlist_id}: {e}")

def get_all_spotify_library_tracks(playlist_ids):
    """Get all unique tracks from Spotify library (liked songs + playlists)"""
    logger.info("\n=== Building Spotify Library ===")

    all_tracks = {}
    _add_liked_songs_to_library(all_tracks)
    _add_playlist_tracks_to_library(all_tracks, playlist_ids)

    logger.info(f"\nTotal unique tracks in library: {len(all_tracks)}\n")
    return all_tracks

@retry_on_rate_limit()
def get_lastfm_track_playcount(artist, track):
    """Get playcount for a specific track from Last.fm"""
    try:
        lastfm_track = network.get_track(artist, track)
        playcount = lastfm_track.get_userplaycount()
        return playcount if playcount else 0
    except Exception:
        return 0

def get_all_lastfm_playcounts():
    """Fetch all playcounts from Last.fm library in bulk using streaming API"""
    logger.info("=== Fetching all Last.fm playcounts in bulk ===")
    user = network.get_user(LASTFM_USERNAME)
    playcounts = {}

    try:
        # pylast v7.x provides a streaming generator that handles pagination automatically.
        # We iterate over this to get all tracks without manual page management.
        top_tracks = user.get_top_tracks(period=pylast.PERIOD_OVERALL, stream=True)

        for top_track in top_tracks:
            artist = top_track.item.artist.name.lower()
            track_name = top_track.item.title.lower()
            key = f"{artist}|||{track_name}"

            # Since we could potentially get thousands of tracks, we only store the weight
            playcounts[key] = int(top_track.weight)

            if len(playcounts) > 0 and len(playcounts) % 500 == 0:
                logger.info(f"Cached {len(playcounts)} tracks...")

    except pylast.WSError as e:
        if str(e.status) == "29":  # Rate limit exceeded
            logger.warning("Rate limit hit during bulk fetch.")
        else:
            logger.error(f"Error during bulk fetch: {e}")
    except Exception as e:
        logger.error(f"Error during bulk fetch: {e}")

    logger.info(f"Successfully cached {len(playcounts)} tracks from Last.fm")
    return playcounts

def match_spotify_with_lastfm(spotify_tracks):
    """Match Spotify tracks with Last.fm playcounts using bulk-fetched data"""
    logger.info("=== Matching Spotify tracks with Last.fm scrobbles ===")

    # Pre-fetch all Last.fm playcounts
    lastfm_library = get_all_lastfm_playcounts()

    matched_tracks = []
    total = len(spotify_tracks)
    missing_tracks = []

    for idx, (uri, track_data) in enumerate(spotify_tracks.items(), 1):
        artist = track_data['artist'].lower()
        name = track_data['name'].lower()
        key = f"{artist}|||{name}"

        playcount = lastfm_library.get(key)

        if playcount is None:
            # If not in top tracks, it might have 0 plays or be hard to match
            # We'll collect these for a second pass or just default to 0
            playcount = 0
            missing_tracks.append(track_data)

        matched_tracks.append({
            'uri': uri,
            'name': track_data['name'],
            'artist': track_data['artist'],
            'playcount': playcount
        })

        if idx % 100 == 0:
            logger.info(f"Processed {idx}/{total} tracks...")

    logger.info(f"\nMatched {len(matched_tracks)} tracks with Last.fm data")
    if missing_tracks:
        logger.info(f"Note: {len(missing_tracks)} tracks were not found in Last.fm library (0 plays assumed)")

    return matched_tracks

def create_or_update_playlist(playlist_name, track_uris):
    """Create or update a playlist with given tracks"""
    playlists = sp.current_user_playlists()['items']
    target_playlist = next((p for p in playlists if p['name'] == playlist_name), None)

    if target_playlist:
        sp.playlist_replace_items(target_playlist['id'], [])
    else:
        user_id = sp.current_user()['id']
        target_playlist = sp.user_playlist_create(user_id, playlist_name, public=True)

    if track_uris:
        batch_size = 100
        for i in range(0, len(track_uris), batch_size):
            batch = track_uris[i:i + batch_size]
            sp.playlist_add_items(target_playlist['id'], batch)
        logger.info(f"Updated '{playlist_name}' with {len(track_uris)} tracks")
    else:
        logger.info(f"No tracks to add to '{playlist_name}'")

def update_playcount_playlists(playlist_ids, top_playlist_name, bottom_playlist_name):
    """Create/update both top 25 and bottom 25 playlists with a single library fetch"""
    logger.info("\n" + "="*50)
    logger.info("CREATING PLAYCOUNT-BASED PLAYLISTS")
    logger.info("="*50)

    spotify_library = get_all_spotify_library_tracks(playlist_ids)
    matched_tracks = match_spotify_with_lastfm(spotify_library)

    # Filter tracks with at least 1 play
    played_tracks = [t for t in matched_tracks if t['playcount']]

    # Sort by playcount descending for top 25
    top_25 = sorted(played_tracks, key=lambda x: x['playcount'], reverse=True)[:25]

    # Group and shuffle for bottom 25 variety
    playcount_groups = defaultdict(list)
    for track in played_tracks:
        playcount_groups[track['playcount']].append(track)

    bottom_tracks = []
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

    top_track_uris = [t['uri'] for t in top_25]
    create_or_update_playlist(top_playlist_name, top_track_uris)

    # Display and create bottom 25 playlist
    logger.info("\n=== Top 25 Least Played Tracks ===")
    for i, track in enumerate(bottom_25, 1):
        logger.info(f"{i}. {track['artist']} - {track['name']} ({track['playcount']} plays)")

    bottom_track_uris = [t['uri'] for t in bottom_25]
    create_or_update_playlist(bottom_playlist_name, bottom_track_uris)

def format_elapsed_time(seconds):
    """Format elapsed seconds into a human readable string"""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours > 0:
        parts.append(f"{int(hours)}h")
    if minutes > 0:
        parts.append(f"{int(minutes)}m")
    parts.append(f"{int(seconds)}s")
    return " ".join(parts)

if __name__ == "__main__":
    script_start = time.time()
    logger.info(f"Script started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    SOURCE_PLAYLIST_IDS = getenv('SOURCE_PLAYLIST_IDS').split(',')
    TARGET_PLAYLIST_NAME = getenv('TARGET_PLAYLIST_NAME')
    TOP_25_PLAYLIST_NAME = getenv('TOP_25_PLAYLIST_NAME', 'Top 25 Most Played')
    BOTTOM_25_PLAYLIST_NAME = getenv('BOTTOM_25_PLAYLIST_NAME', 'Top 25 Least Played')

    # Update recent tracks playlist
    logger.info("\n" + "="*50)
    logger.info("UPDATING RECENT TRACKS PLAYLIST")
    logger.info("="*50)
    operation_start = time.time()
    update_recent_tracks_playlist(SOURCE_PLAYLIST_IDS, TARGET_PLAYLIST_NAME)
    operation_time = time.time() - operation_start
    logger.info(f"\nRecent tracks update completed in {format_elapsed_time(operation_time)}")

    operation_start = time.time()
    update_playcount_playlists(SOURCE_PLAYLIST_IDS, TOP_25_PLAYLIST_NAME, BOTTOM_25_PLAYLIST_NAME)
    operation_time = time.time() - operation_start
    logger.info(f"\nPlaycount update completed in {format_elapsed_time(operation_time)}")

    total_runtime = time.time() - script_start
    logger.info("\n" + "="*50)
    logger.info(f"Script completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Total runtime: {format_elapsed_time(total_runtime)}")
    logger.info("="*50)
