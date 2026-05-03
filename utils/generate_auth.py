import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os

print("Generating Master Spotify Cache...")

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv('CLIENT_ID'),
    client_secret=os.getenv('CLIENT_SECRET'),
    redirect_uri=os.getenv('REDIRECT_URI'),
    scope='user-follow-read user-library-read playlist-read-private playlist-modify-public playlist-modify-private'
))

# Making a simple API call forces the library to authenticate and build the .cache file
user = sp.current_user()
print(f"Success! Master cache generated for user: {user['id']}")
