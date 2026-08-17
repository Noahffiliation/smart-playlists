from __future__ import annotations

import sys
from pathlib import Path

# Add project root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import Any

import spotipy

from utils.common import get_spotify_client


def generate_master_cache(client: spotipy.Spotify | None = None) -> dict[str, Any]:
    """Generate and return master Spotify cache for current user."""
    print("Generating Master Spotify Cache...")

    sp = client or get_spotify_client(
        scope="user-follow-read user-library-read playlist-read-private playlist-modify-public playlist-modify-private"
    )

    # Making a simple API call forces the library to authenticate and build the .cache file
    user = sp.current_user()
    print(f"Success! Master cache generated for user: {user['id']}")
    return user


if __name__ == "__main__":
    generate_master_cache()
