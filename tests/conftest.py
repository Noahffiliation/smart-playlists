import os

# Set dummy Spotify and Last.fm environment variables for test suites running in CI or environments without .env
os.environ.setdefault("CLIENT_ID", "mock_client_id")
os.environ.setdefault("CLIENT_SECRET", "mock_client_secret")
os.environ.setdefault("REDIRECT_URI", "http://localhost:8888/callback")
os.environ.setdefault("LASTFM_API_KEY", "mock_lastfm_api_key")
os.environ.setdefault("LASTFM_USERNAME", "mock_lastfm_username")
os.environ.setdefault("SPOTIPY_CLIENT_ID", "mock_client_id")
os.environ.setdefault("SPOTIPY_CLIENT_SECRET", "mock_client_secret")
os.environ.setdefault("SPOTIPY_REDIRECT_URI", "http://localhost:8888/callback")
