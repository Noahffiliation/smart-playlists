import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime, timedelta
from os import getenv
from dotenv import load_dotenv
import time

load_dotenv()

CLIENT_ID = getenv('CLIENT_ID')
CLIENT_SECRET = getenv('CLIENT_SECRET')
REDIRECT_URI = getenv('REDIRECT_URI')  # Must match your Spotify app settings

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope='playlist-modify-public playlist-read-private user-library-read'
))

date_format = '%Y-%m-%dT%H:%M:%SZ'

def get_all_playlist_tracks(playlist_id):

	# Fetch all tracks in the playlist, 100 at a time since that's the maximum limit for spotipy
    tracks = []
    offset = 0
    limit = 100
    while True:
        try:
            results = sp.playlist_tracks(playlist_id, offset=offset, limit=limit)

			# Filter out None items and tracks that are None
            tracks.extend([item for item in results['items'] if item and item.get('track')])
            if not results['next']:
                break

            offset += limit
            time.sleep(0.1)

        except Exception as e:
            print(f"Error fetching playlist tracks: {e}")
            break

    return tracks

def get_liked_songs():

	# Fetch all liked songs, 50 at a time since that's the maximum limit for spotipy
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
    print(f"\nFinding tracks added since {one_month_ago.date()}\n")

    # Process regular playlists
    playlist_tracks = _get_recent_playlist_tracks(playlist_ids, one_month_ago)

    # Process liked songs
    liked_tracks = _get_recent_liked_tracks(one_month_ago)

    # Combine and process all tracks
    all_tracks = playlist_tracks + liked_tracks
    return _process_and_sort_tracks(all_tracks)

def _get_recent_playlist_tracks(playlist_ids, cutoff_date):
    recent_tracks = []
    for playlist_id in playlist_ids:
        try:
            playlist = sp.playlist(playlist_id)
            print(f"Processing playlist: {playlist['name']}")
            tracks = get_all_playlist_tracks(playlist_id)
            recent_tracks.extend(_process_playlist_tracks(tracks, cutoff_date))
        except Exception as e:
            print(f"Error processing playlist {playlist_id}: {e}")
    return recent_tracks

def _process_playlist_tracks(tracks, cutoff_date):
    processed_tracks = []
    for item in tracks:
        try:
            track_data = _extract_track_data(item, cutoff_date)
            if track_data:
                processed_tracks.append(track_data)
        except Exception as e:
            print(f"Error processing track: {e}")
    return processed_tracks

def _extract_track_data(item, cutoff_date):
    if not item or not item.get('track') or not item.get('added_at'):
        print(f"Skipping invalid track item: {item}")
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
    print("Fetching tracks from Liked Songs")
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

		# Add in batches of 100 since that's the limit for Spotify API
        batch_size = 100
        for i in range(0, len(recent_tracks), batch_size):
            batch = recent_tracks[i:i + batch_size]
            sp.playlist_add_items(target_playlist['id'], batch)
            print(f"Added batch of {len(batch)} tracks")

        print(f"Updated {target_playlist_name} with {len(recent_tracks)} recent tracks")
    else:
        print("No recent tracks found to add.")

if __name__ == "__main__":
    SOURCE_PLAYLIST_IDS = getenv('SOURCE_PLAYLIST_IDS').split(',')
    TARGET_PLAYLIST_NAME = getenv('TARGET_PLAYLIST_NAME')

    update_recent_tracks_playlist(SOURCE_PLAYLIST_IDS, TARGET_PLAYLIST_NAME)
