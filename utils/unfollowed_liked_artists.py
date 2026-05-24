import argparse
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from collections import defaultdict
from datetime import datetime
from os import getenv, makedirs
from os.path import join
from dotenv import load_dotenv
import logging

load_dotenv()

CLIENT_ID = getenv('CLIENT_ID')
CLIENT_SECRET = getenv('CLIENT_SECRET')
REDIRECT_URI = getenv('REDIRECT_URI')
MIN_LIKED_SONGS = int(getenv('MIN_LIKED_SONGS', '10'))


def setup_logging():
    logs_dir = join('logs')
    makedirs(logs_dir, exist_ok=True)
    log_file = join(logs_dir, f'unfollowed_liked_artists_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(__name__)


def get_spotify_client():
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope='user-follow-read user-library-read',
    ))


def get_followed_artist_ids(sp):
    followed = set()
    results = sp.current_user_followed_artists(limit=50)

    for artist in results['artists']['items']:
        followed.add(artist['id'])

    while results['artists']['next']:
        results = sp.next(results['artists'])
        for artist in results['artists']['items']:
            followed.add(artist['id'])

    return followed


def count_liked_songs_by_artist(sp):
    """Count liked songs per primary artist from the user's liked songs."""
    counts = defaultdict(int)
    names = {}
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

        if not results['next']:
            break
        offset += limit

    return counts, names


def find_unfollowed_liked_artists(counts, names, followed_ids, min_liked):
    candidates = []
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


def main():
    parser = argparse.ArgumentParser(
        description='List artists you do not follow but have many liked songs.'
    )
    parser.add_argument(
        '--min',
        type=int,
        default=MIN_LIKED_SONGS,
        help=f'Minimum liked songs per artist (default: {MIN_LIKED_SONGS})',
    )
    args = parser.parse_args()

    logger = setup_logging()
    logger.info('=' * 60)
    logger.info('Unfollowed artists with many liked songs')
    logger.info('=' * 60)

    sp = get_spotify_client()

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


if __name__ == '__main__':
    main()
