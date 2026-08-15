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
            {'name': 'Old Album', 'release_date': '2025-01-01', 'id': 'a2'},
            {'name': 'Duplicate', 'release_date': '2026-01-27', 'id': 'a1'},
            {'name': 'Invalid Date', 'release_date': 'invalid', 'id': 'a3'},
            {'name': 'No ID', 'release_date': '2026-01-27', 'id': ''}
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


def test_parse_release_date():
    assert new_releases.parse_release_date('2026') == datetime(2026, 1, 1)
    assert new_releases.parse_release_date('2026-05') == datetime(2026, 5, 1)
    assert new_releases.parse_release_date('2026-05-15') == datetime(2026, 5, 15)
    assert new_releases.parse_release_date('') is None
    assert new_releases.parse_release_date(None) is None
    assert new_releases.parse_release_date('invalid-date') is None


def test_get_artist_new_releases_pagination(mock_sp):
    mock_sp.artist_albums.return_value = {
        'items': [{'name': 'Page 1 Album', 'release_date': '2026-01-27', 'id': 'a1'}],
        'next': 'url_to_page_2'
    }
    mock_sp.next.return_value = {
        'items': [{'name': 'Page 2 Single', 'release_date': '2026-01-25', 'id': 'a2'}],
        'next': None
    }
    since_date = datetime(2026, 1, 20)

    releases = new_releases.get_artist_new_releases(mock_sp, 'artist_id', since_date)
    assert len(releases) == 2
    assert releases[0]['name'] == 'Page 1 Album'
    assert releases[1]['name'] == 'Page 2 Single'


def test_get_saved_tracks(mock_sp, mock_logger):
    mock_sp.current_user_saved_tracks.return_value = {
        'items': [{'track': {'id': 't1'}}, {'track': None}],
        'next': 'url'
    }
    mock_sp.next.return_value = {
        'items': [{'track': {'id': 't2'}}],
        'next': None
    }
    track_ids = new_releases.get_saved_tracks(mock_sp, mock_logger)
    assert track_ids == {'t1', 't2'}


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
        'items': [{'track': {'id': 't1'}}, {'track': None}],
        'next': 'url'
    }
    mock_sp.next.return_value = {
        'items': [{'track': {'id': 't2'}}],
        'next': None
    }
    track_ids = new_releases.get_playlist_tracks(mock_sp, 'pid', mock_logger)
    assert track_ids == {'t1', 't2'}


def test_get_playlist_tracks_empty(mock_sp, mock_logger):
    mock_sp.playlist_tracks.side_effect = Exception("API Error")
    track_ids = new_releases.get_playlist_tracks(mock_sp, 'pid', mock_logger)
    assert len(track_ids) == 0


def test_get_all_library_tracks(mock_sp, mock_logger):
    with patch('new_releases.get_saved_tracks') as mock_saved, \
         patch('new_releases.get_playlist_tracks') as mock_playlist:
        mock_saved.return_value = {'t1'}
        mock_playlist.return_value = {'t2'}

        # With source playlist IDs
        all_tracks = new_releases.get_all_library_tracks(mock_sp, 'p1,p2', mock_logger)
        assert all_tracks == {'t1', 't2'}
        assert mock_playlist.call_count == 2

        # Without source playlist IDs
        all_tracks_empty = new_releases.get_all_library_tracks(mock_sp, '', mock_logger)
        assert all_tracks_empty == {'t1'}


def test_get_album_tracks(mock_sp):
    mock_sp.album_tracks.return_value = {
        'items': [{'id': 't1'}],
        'next': 'url'
    }
    mock_sp.next.return_value = {
        'items': [{'id': 't2'}],
        'next': None
    }
    track_ids = new_releases.get_album_tracks(mock_sp, 'aid')
    assert track_ids == ['t1', 't2']


def test_main_with_new_tracks(mock_sp, mock_logger):
    with patch('new_releases.get_followed_artists', return_value=[{'name': 'A1', 'id': 'aid1'}, {'name': 'A2', 'id': 'aid2'}]), \
         patch('new_releases.get_all_library_tracks', return_value=set()), \
         patch('new_releases.create_or_get_playlist', return_value='pid'), \
         patch('new_releases.get_playlist_tracks', return_value=set()), \
         patch('new_releases.get_artist_new_releases', side_effect=[
             [{'id': 'alb1', 'name': 'Album 1', 'release_date': '2026-01-28'}],
             [{'id': 'alb1', 'name': 'Album 1', 'release_date': '2026-01-28'}] # Duplicate album skipped
         ]), \
         patch('new_releases.get_album_tracks', return_value=['t1']):

        new_releases.main(
            sp_client=mock_sp,
            custom_logger=mock_logger,
            source_playlist_ids='p1',
            lookback_days_override=3
        )
        mock_sp.playlist_add_items.assert_called_once_with('pid', ['t1'])


def test_main_no_new_tracks(mock_sp, mock_logger):
    with patch('new_releases.get_followed_artists', return_value=[{'name': 'A', 'id': 'aid'}]), \
         patch('new_releases.get_all_library_tracks', return_value={'t1'}), \
         patch('new_releases.create_or_get_playlist', return_value='pid'), \
         patch('new_releases.get_playlist_tracks', return_value={'t1'}), \
         patch('new_releases.get_artist_new_releases', return_value=[{'id': 'alb_id', 'name': 'Alb', 'release_date': '2026-01-28'}]), \
         patch('new_releases.get_album_tracks', return_value=['t1']):

        new_releases.main(sp_client=mock_sp, custom_logger=mock_logger)
        mock_sp.playlist_add_items.assert_not_called()


def test_main_exception(mock_sp, mock_logger):
    with patch('new_releases.get_followed_artists', side_effect=RuntimeError("Fatal error")):
        with pytest.raises(RuntimeError):
            new_releases.main(sp_client=mock_sp, custom_logger=mock_logger)
