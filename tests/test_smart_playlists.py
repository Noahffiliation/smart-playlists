import pytest
import pylast
import time
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import smart_playlists

@pytest.fixture(autouse=True)
def mock_sleep():
    with patch('time.sleep', return_value=None):
        yield

@pytest.fixture
def mock_spotify():
    with patch('smart_playlists.sp') as mock_sp:
        yield mock_sp

@pytest.fixture
def mock_lastfm():
    with patch('smart_playlists.network') as mock_network:
        yield mock_network

def test_format_elapsed_time():
    assert smart_playlists.format_elapsed_time(5) == "5s"
    assert smart_playlists.format_elapsed_time(65) == "1m 5s"
    assert smart_playlists.format_elapsed_time(3665) == "1h 1m 5s"

def test_create_track_dict():
    track = {
        'uri': 'spotify:track:123',
        'name': 'Test Track',
        'artists': [{'name': 'Test Artist'}]
    }
    added_at = '2026-01-28T13:00:00Z'
    result = smart_playlists._create_track_dict(track, added_at)
    assert result['uri'] == 'spotify:track:123'
    assert result['added_at'] == datetime(2026, 1, 28, 13, 0, 0)
    assert result['key'] == 'test artist|||test track'

    assert smart_playlists._create_track_dict(None) is None
    assert smart_playlists._create_track_dict({}) is None

def test_get_all_playlist_tracks(mock_spotify):
    mock_spotify.playlist_tracks.side_effect = [
        {'items': [{'track': {'uri': '1'}}], 'next': 'url'},
        {'items': [{'track': {'uri': '2'}}], 'next': None}
    ]
    tracks = smart_playlists.get_all_playlist_tracks('playlist_id')
    assert len(tracks) == 2
    assert tracks[0]['track']['uri'] == '1'
    assert tracks[1]['track']['uri'] == '2'

def test_get_liked_songs(mock_spotify):
    mock_spotify.current_user_saved_tracks.side_effect = [
        {'items': [{'track': {'uri': '1'}, 'added_at': '2026-01-28T13:00:00Z'}], 'next': None},
        {'items': [], 'next': None}
    ]
    tracks = smart_playlists.get_liked_songs()
    assert len(tracks) == 1
    assert tracks[0]['track']['uri'] == '1'

def test_get_lastfm_track_playcount(mock_lastfm):
    mock_track = MagicMock()
    mock_track.get_userplaycount.return_value = 10
    mock_lastfm.get_track.return_value = mock_track

    count = smart_playlists.get_lastfm_track_playcount('Artist', 'Track')
    assert count == 10

    mock_track.get_userplaycount.return_value = None
    assert smart_playlists.get_lastfm_track_playcount('Artist', 'Track') == 0

    mock_lastfm.get_track.side_effect = Exception("Error")
    assert smart_playlists.get_lastfm_track_playcount('Artist', 'Track') == 0



def test_add_liked_songs_to_library(mock_spotify):
    mock_spotify.current_user_saved_tracks.side_effect = [
        {'items': [{'track': {'uri': '1', 'name': 'N1', 'artists': [{'name': 'A1'}]}, 'added_at': '2026-01-28T13:00:00Z'}], 'next': None},
        {'items': [], 'next': None}
    ]
    all_tracks = {}
    smart_playlists._add_liked_songs_to_library(all_tracks)
    assert '1' in all_tracks
    assert all_tracks['1']['name'] == 'N1'

def test_update_recent_tracks_playlist(mock_spotify):
    with patch('smart_playlists.get_all_spotify_library_tracks') as mock_library, \
         patch('smart_playlists.create_or_update_playlist') as mock_create_update:

        now = datetime.now()
        mock_library.return_value = {
            't1': {'uri': 't1', 'added_at': now - timedelta(days=5)},
            't2': {'uri': 't2', 'added_at': now - timedelta(days=40)}, # Old
            't3': {'uri': 't3', 'added_at': now - timedelta(days=2)}
        }

        smart_playlists.update_recent_tracks_playlist(mock_library.return_value, 'Target')

        # Should only include t3 and t1, sorted t3 then t1
        mock_create_update.assert_called_with('Target', ['t3', 't1'])

def test_match_spotify_with_lastfm(mock_lastfm):
    spotify_tracks = {
        'uri1': {'name': 'Name1', 'artist': 'Artist1'},
        'uri2': {'name': 'Name2', 'artist': 'Artist2'}
    }

    with patch('smart_playlists.get_all_lastfm_playcounts') as mock_bulk:
        mock_bulk.return_value = {
            'artist1|||name1': 10,
            'artist2|||name2': 5
        }

        result = smart_playlists.match_spotify_with_lastfm(spotify_tracks)
        assert len(result) == 2
        assert result[0]['playcount'] == 10
        assert result[1]['playcount'] == 5

def test_get_all_lastfm_playcounts(mock_lastfm):
    mock_user = MagicMock()
    mock_lastfm.get_user.return_value = mock_user

    # Mock tracks
    track1 = MagicMock()
    track1.item.artist.name = "Artist1"
    track1.item.title = "Track1"
    track1.weight = "10"

    track2 = MagicMock()
    track2.item.artist.name = "Artist2"
    track2.item.title = "Track2"
    track2.weight = "5"

    # get_top_tracks returns an iterable list in our mock
    mock_user.get_top_tracks.return_value = [track1, track2]

    with patch('smart_playlists.LASTFM_USERNAME', 'test_user'):
        result = smart_playlists.get_all_lastfm_playcounts()

    assert len(result) == 2
    assert result['artist1|||track1'] == 10
    assert result['artist2|||track2'] == 5

def test_retry_on_rate_limit():
    mock_func = MagicMock()
    # Create a mock WSError
    rate_limit_error = pylast.WSError("network", "29", "rate limit")
    mock_func.side_effect = [rate_limit_error, "success"]

    @smart_playlists.retry_on_rate_limit(max_retries=2, initial_delay=0.1)
    def test_func():
        return mock_func()

    with patch('smart_playlists.time.sleep'):
        result = test_func()

    assert result == "success"
    assert mock_func.call_count == 2

def test_retry_on_rate_limit_failure():
    mock_func = MagicMock()
    rate_limit_error = pylast.WSError("network", "29", "rate limit")
    mock_func.side_effect = rate_limit_error

    @smart_playlists.retry_on_rate_limit(max_retries=1, initial_delay=0.1)
    def test_func():
        return mock_func()

    with patch('smart_playlists.time.sleep'):
        with pytest.raises(pylast.WSError) as excinfo:
            test_func()
        assert str(excinfo.value.status) == "29"

    assert mock_func.call_count == 2 # Initial + 1 retry

def test_get_all_lastfm_playcounts_rate_limit(mock_lastfm):
    mock_user = MagicMock()
    mock_lastfm.get_user.return_value = mock_user

    # Force a rate limit error
    rate_limit_error = pylast.WSError("network", "29", "rate limit")
    mock_user.get_top_tracks.side_effect = rate_limit_error

    with patch('smart_playlists.LASTFM_USERNAME', 'test_user'), \
         patch('smart_playlists.time.sleep'):
        result = smart_playlists.get_all_lastfm_playcounts()

    assert result == {}
    assert mock_user.get_top_tracks.call_count == 1

def test_create_or_update_playlist_exists(mock_spotify):
    mock_spotify.current_user_playlists.return_value = {'items': [{'name': 'P1', 'id': 'p1'}]}
    smart_playlists.create_or_update_playlist('P1', ['t1'])
    mock_spotify.playlist_replace_items.assert_called_with('p1', [])
    mock_spotify.playlist_add_items.assert_called_with('p1', ['t1'])

def test_create_or_update_playlist_new(mock_spotify):
    mock_spotify.current_user_playlists.return_value = {'items': []}
    mock_spotify.current_user.return_value = {'id': 'user_id'}
    mock_spotify.user_playlist_create.return_value = {'id': 'p1'}
    smart_playlists.create_or_update_playlist('P1', ['t1'])
    mock_spotify.user_playlist_create.assert_called_with('user_id', 'P1', public=True)
    mock_spotify.playlist_add_items.assert_called_with('p1', ['t1'])

def test_update_playcount_playlists(mock_spotify):
    with patch('smart_playlists.get_all_spotify_library_tracks') as mock_library, \
         patch('smart_playlists.match_spotify_with_lastfm') as mock_match, \
         patch('smart_playlists.create_or_update_playlist') as mock_create_update:

        mock_library.return_value = {}
        mock_match.return_value = [
            {'uri': 't1', 'artist': 'A', 'name': 'N', 'playcount': 100},
            {'uri': 't2', 'artist': 'A2', 'name': 'N2', 'playcount': 10}
        ]

        smart_playlists.update_playcount_playlists(mock_library.return_value, 'Top', 'Bottom')
        assert mock_create_update.call_count == 2



def test_get_all_spotify_library_tracks(mock_spotify):
    with patch('smart_playlists._add_liked_songs_to_library') as mock_liked, \
         patch('smart_playlists._add_playlist_tracks_to_library') as mock_playlist:

        result = smart_playlists.get_all_spotify_library_tracks(['ids'])
        assert result == {}
        mock_liked.assert_called_once()
        mock_playlist.assert_called_once()

def test_add_playlist_tracks_to_library(mock_spotify):
    mock_spotify.playlist.return_value = {'name': 'P1'}
    with patch('smart_playlists.get_all_playlist_tracks') as mock_get:
        mock_get.return_value = [{'track': {'uri': 't1', 'name': 'N', 'artists': [{'name': 'A'}]}}]
        all_tracks = {}
        smart_playlists._add_playlist_tracks_to_library(all_tracks, ['id'])
        assert 't1' in all_tracks
