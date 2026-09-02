from __future__ import annotations

import sys
from pathlib import Path

# Add project root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import Any

import spotipy

from utils.common import get_spotify_client


def generate_master_cache(
    client: spotipy.Spotify | None = None,
    open_browser: bool = True,
) -> dict[str, Any]:
    """Generate and return master Spotify cache for current user."""
    print("Generating Master Spotify Cache...")

    sp = client or get_spotify_client(open_browser=open_browser)

    if sp.auth_manager and hasattr(sp.auth_manager, "get_authorize_url"):
        auth_url = sp.auth_manager.get_authorize_url()
        print("\n" + "=" * 70)
        print("SPOTIFY AUTHORIZATION STEP")
        print("=" * 70)
        print("IMPORTANT: Do NOT navigate directly to 127.0.0.1 or localhost.")
        print("You must start by opening the Spotify authorization URL:")
        print(f"\n  {auth_url}\n")
        print("1. Open the URL above in your browser.")
        print("2. Log in to Spotify and click 'Agree' to grant permissions.")
        if open_browser:
            print(f"3. Spotify will automatically redirect to: {sp.auth_manager.redirect_uri}")
        else:
            print(
                "3. Copy the full redirected URL from your browser address bar and paste it below."
            )
        print("=" * 70 + "\n")

    # Making a simple API call forces the library to authenticate and build the .cache file
    user = sp.current_user()
    if not user:
        raise RuntimeError("Failed to retrieve current Spotify user.")

    print(f"Success! Master cache generated for user: {user['id']}")
    return user


def main(args_list: list[str] | None = None) -> dict[str, Any]:
    """CLI entrypoint for generating master cache."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate master Spotify cache.")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Use manual URL copy-paste mode instead of automatic local server redirect.",
    )
    args = parser.parse_args(args_list)
    return generate_master_cache(open_browser=not args.manual)


if __name__ == "__main__":
    main()
