from __future__ import annotations

import sys
from pathlib import Path

# Add project root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import spotipy
from collections import defaultdict
from os import getenv
from dotenv import load_dotenv
import logging
from typing import Any, Optional

from utils.common import setup_logger, get_spotify_client

load_dotenv()

MIN_LIKED_SONGS = int(getenv('MIN_LIKED_SONGS', '10'))


def get_followed_artist_ids(sp: spotipy.Spotify) -> set[str]:
    """Get all artist IDs the user follows."""
    followed: set[str] = set()
    results = sp.current_user_followed_artists(limit=50)

    for artist in results['artists']['items']:
        followed.add(artist['id'])

    while results['artists']['next']:
        results = sp.next(results['artists'])
        for artist in results['artists']['items']:
            followed.add(artist['id'])

    return followed


def count_liked_songs_by_artist(sp: spotipy.Spotify) -> tuple[dict[str, int], dict[str, str]]:
    """Count liked songs per primary artist from the user's liked songs."""
    counts: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    offset = 0
    limit = 50

    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        if not results['items']:
            break

        for item in results['items']:
            track = item.get('track')
            if not track or not track.get('artists'):
                continue

            artist = track['artists'][0]
            artist_id = artist['id']
            counts[artist_id] += 1
            names[artist_id] = artist['name']

        if not results.get('next'):
            break
        offset += limit

    return counts, names


def find_unfollowed_liked_artists(
    counts: dict[str, int],
    names: dict[str, str],
    followed_ids: set[str],
    min_liked: int
) -> list[dict[str, Any]]:
    """Filter and sort artists who are not followed but have at least min_liked songs."""
    candidates: list[dict[str, Any]] = []
    for artist_id, liked_count in counts.items():
        if artist_id in followed_ids:
            continue
        if liked_count >= min_liked:
            candidates.append({
                'id': artist_id,
                'name': names[artist_id],
                'liked_count': liked_count,
            })

    return sorted(candidates, key=lambda x: (-x['liked_count'], x['name'].lower()))


def main(
    args_list: Optional[list[str]] = None,
    client: Optional[spotipy.Spotify] = None,
    custom_logger: Optional[logging.Logger] = None
) -> list[dict[str, Any]]:
    """Main entrypoint for finding unfollowed artists with many liked songs."""
    parser = argparse.ArgumentParser(
        description='List artists you do not follow but have many liked songs.'
    )
    parser.add_argument(
        '--min',
        type=int,
        default=MIN_LIKED_SONGS,
        help=f'Minimum liked songs per artist (default: {MIN_LIKED_SONGS})',
    )
    args = parser.parse_args(args_list)

    logger = custom_logger or setup_logger('unfollowed_liked_artists', 'unfollowed_liked_artists')
    logger.info('=' * 60)
    logger.info('Unfollowed artists with many liked songs')
    logger.info('=' * 60)

    sp = client or get_spotify_client(scope='user-follow-read user-library-read')

    logger.info('Fetching followed artists...')
    followed_ids = get_followed_artist_ids(sp)
    logger.info(f'Following {len(followed_ids)} artists')

    logger.info('Counting liked songs by artist...')
    counts, names = count_liked_songs_by_artist(sp)
    logger.info(f'Found {sum(counts.values())} liked songs across {len(counts)} artists')

    results = find_unfollowed_liked_artists(counts, names, followed_ids, args.min)

    logger.info('')
    logger.info(f'Artists not followed with {args.min}+ liked songs: {len(results)}')
    logger.info('-' * 60)

    if not results:
        logger.info('No artists matched your criteria.')
    else:
        for i, artist in enumerate(results, 1):
            logger.info(f"{i:3}. {artist['name']} ({artist['liked_count']} liked songs)")

    logger.info('-' * 60)
    logger.info('Done')
    logger.info('=' * 60)
    return results


if __name__ == '__main__':
    main()
