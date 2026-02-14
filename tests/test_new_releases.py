import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import new_releases

@pytest.fixture(autouse=True)
def mock_sleep():
    with patch('time.sleep', return_value=None):
        yield

@pytest.fixture
def mock_sp():
    return MagicMock()

@pytest.fixture
def mock_logger():
    return MagicMock()

def test_get_followed_artists(mock_sp, mock_logger):
    mock_sp.current_user_followed_artists.return_value = {
        'artists': {
            'items': [{'name': 'Artist 1'}],
            'next': 'url'
        }
    }
    mock_sp.next.return_value = {
        'artists': {
            'items': [{'name': 'Artist 2'}],
            'next': None
        }
    }

    artists = new_releases.get_followed_artists(mock_sp, mock_logger)
    assert len(artists) == 2
    assert artists[0]['name'] == 'Artist 1'
    assert artists[1]['name'] == 'Artist 2'

def test_get_artist_new_releases(mock_sp):
    mock_sp.artist_albums.return_value = {
        'items': [
            {'name': 'New Album', 'release_date': '2026-01-27', 'id': 'a1'},
            {'name': 'Old Album', 'release_date': '2025-01-01', 'id': 'a2'}
        ]
    }
    since_date = datetime(2026, 1, 20)

    releases = new_releases.get_artist_new_releases(mock_sp, 'artist_id', since_date)
    assert len(releases) == 1
    assert releases[0]['name'] == 'New Album'

def test_get_artist_new_releases_date_formats(mock_sp):
    mock_sp.artist_albums.return_value = {
        'items': [
            {'name': 'Year Only', 'release_date': '2026', 'id': 'a1'},
            {'name': 'Year-Month', 'release_date': '2026-01', 'id': 'a2'}
        ]
    }
    since_date = datetime(2026, 1, 1)
    releases = new_releases.get_artist_new_releases(mock_sp, 'artist_id', since_date)
    assert len(releases) == 2

def test_get_saved_tracks(mock_sp, mock_logger):
    mock_sp.current_user_saved_tracks.return_value = {
        'items': [{'track': {'id': 't1'}}],
        'next': None
    }
    track_ids = new_releases.get_saved_tracks(mock_sp, mock_logger)
    assert 't1' in track_ids
    assert len(track_ids) == 1

def test_create_or_get_playlist_exists(mock_sp, mock_logger):
    mock_sp.current_user.return_value = {'id': 'user_id'}
    mock_sp.current_user_playlists.return_value = {
        'items': [{'name': 'The News', 'id': 'playlist_id'}]
    }

    pid = new_releases.create_or_get_playlist(mock_sp, 'The News', mock_logger)
    assert pid == 'playlist_id'
    mock_sp.user_playlist_create.assert_not_called()

def test_create_or_get_playlist_new(mock_sp, mock_logger):
    mock_sp.current_user.return_value = {'id': 'user_id'}
    mock_sp.current_user_playlists.return_value = {'items': []}
    mock_sp.user_playlist_create.return_value = {'id': 'new_id'}

    pid = new_releases.create_or_get_playlist(mock_sp, 'The News', mock_logger)
    assert pid == 'new_id'
    mock_sp.user_playlist_create.assert_called_with(
        'user_id', 'The News', public=False, description='New releases from artists I follow'
    )

def test_get_playlist_tracks(mock_sp, mock_logger):
    mock_sp.playlist_tracks.return_value = {
        'items': [{'track': {'id': 't1'}}, {'track': {'id': 't2'}}],
        'next': None
    }
    track_ids = new_releases.get_playlist_tracks(mock_sp, 'pid', mock_logger)
    assert 't1' in track_ids
    assert 't2' in track_ids
    assert len(track_ids) == 2

def test_get_playlist_tracks_empty(mock_sp, mock_logger):
    mock_sp.playlist_tracks.side_effect = Exception("API Error")
    track_ids = new_releases.get_playlist_tracks(mock_sp, 'pid', mock_logger)
    assert len(track_ids) == 0

def test_get_all_library_tracks(mock_sp, mock_logger):
    with patch('new_releases.get_saved_tracks') as mock_saved, \
         patch('new_releases.get_playlist_tracks') as mock_playlist:
        mock_saved.return_value = {'t1'}
        mock_playlist.return_value = {'t2'}

        all_tracks = new_releases.get_all_library_tracks(mock_sp, 'p1,p2', mock_logger)
        assert all_tracks == {'t1', 't2'}
        assert mock_playlist.call_count == 2

def test_get_album_tracks(mock_sp):
    mock_sp.album_tracks.return_value = {
        'items': [{'id': 't1'}, {'id': 't2'}],
        'next': None
    }
    track_ids = new_releases.get_album_tracks(mock_sp, 'aid')
    assert track_ids == ['t1', 't2']

def test_main(mock_sp, mock_logger):
    with patch('new_releases.setup_logging', return_value=mock_logger), \
         patch('new_releases.get_spotify_client', return_value=mock_sp), \
         patch('new_releases.get_followed_artists', return_value=[{'name': 'A', 'id': 'aid'}]), \
         patch('new_releases.get_all_library_tracks', return_value=set()), \
         patch('new_releases.create_or_get_playlist', return_value='pid'), \
         patch('new_releases.get_playlist_tracks', return_value=set()), \
         patch('new_releases.get_artist_new_releases', return_value=[{'id': 'alb_id', 'name': 'Alb', 'release_date': '2026-01-28'}]), \
         patch('new_releases.get_album_tracks', return_value=['t1']):

        new_releases.main()
        mock_sp.playlist_add_items.assert_called()

def test_main_excludes_target_playlist_tracks(mock_sp, mock_logger):
    """Verify that tracks already in the target playlist are not added again"""
    with patch('new_releases.setup_logging', return_value=mock_logger), \
         patch('new_releases.get_spotify_client', return_value=mock_sp), \
         patch('new_releases.get_followed_artists', return_value=[{'name': 'A', 'id': 'aid'}]), \
         patch('new_releases.get_all_library_tracks', return_value=set()), \
         patch('new_releases.create_or_get_playlist', return_value='pid'), \
         patch('new_releases.get_playlist_tracks', return_value={'t1'}), \
         patch('new_releases.get_artist_new_releases', return_value=[{'id': 'alb_id', 'name': 'Alb', 'release_date': '2026-01-28'}]), \
         patch('new_releases.get_album_tracks', return_value=['t1', 't2']):

        new_releases.main()

        # Should only add t2, since t1 is in target playlist
        mock_sp.playlist_add_items.assert_called_once()
        args, _ = mock_sp.playlist_add_items.call_args
        assert args[1] == ['t2']
