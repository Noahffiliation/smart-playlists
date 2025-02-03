import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime, timedelta
from os import getenv
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = getenv('CLIENT_ID')
CLIENT_SECRET = getenv('CLIENT_SECRET')
REDIRECT_URI = getenv('REDIRECT_URI')  # Must match your Spotify app settings

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope='playlist-modify-public playlist-read-private'
))

def get_all_playlist_tracks(playlist_id):

	# Fetch all tracks in the playlist, 100 at a time since that's the maximum limit for spotipy
    tracks = []
    offset = 0
    limit = 100
    while True:
        results = sp.playlist_tracks(playlist_id, offset=offset, limit=limit)
        tracks.extend(results['items'])
        if results['next']:
            offset += limit
        else:
            break

    return tracks

def get_recent_tracks_from_playlists(playlist_ids):
    recent_tracks = []
    one_month_ago = datetime.now() - timedelta(days=30)
    print(f"One month ago: {one_month_ago}")

    for playlist_id in playlist_ids:
        print(f"Fetching tracks from playlist: {sp.playlist(playlist_id)['name']}")
        tracks = get_all_playlist_tracks(playlist_id)

        for item in tracks:
            added_at = datetime.strptime(item['added_at'], '%Y-%m-%dT%H:%M:%SZ')
            if added_at > one_month_ago:
                recent_tracks.append(item['track']['uri'])

    # Remove duplicate tracks
    recent_tracks = list(set(recent_tracks))
    return recent_tracks

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
        sp.playlist_add_items(target_playlist['id'], recent_tracks)
        print(f"Updated playlist '{target_playlist_name}' with {len(recent_tracks)} tracks.")
    else:
        print("No recent tracks found to add.")

if __name__ == "__main__":
    SOURCE_PLAYLIST_IDS = getenv('SOURCE_PLAYLIST_IDS').split(',')
    TARGET_PLAYLIST_NAME = getenv('TARGET_PLAYLIST_NAME')

    update_recent_tracks_playlist(SOURCE_PLAYLIST_IDS, TARGET_PLAYLIST_NAME)
