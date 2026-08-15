import pytest
from unittest.mock import MagicMock, patch
from utils import unfollowed_liked_artists


def test_get_followed_artist_ids():
    mock_sp = MagicMock()
    mock_sp.current_user_followed_artists.return_value = {
        'artists': {
            'items': [{'id': 'a1', 'name': 'Artist 1'}],
            'next': 'url'
        }
    }
    mock_sp.next.return_value = {
        'artists': {
            'items': [{'id': 'a2', 'name': 'Artist 2'}],
            'next': None
        }
    }

    followed = unfollowed_liked_artists.get_followed_artist_ids(mock_sp)
    assert followed == {'a1', 'a2'}


def test_count_liked_songs_by_artist():
    mock_sp = MagicMock()
    mock_sp.current_user_saved_tracks.side_effect = [
        {
            'items': [
                {'track': {'id': 't1', 'artists': [{'id': 'a1', 'name': 'Artist 1'}]}},
                {'track': {'id': 't2', 'artists': [{'id': 'a1', 'name': 'Artist 1'}]}},
                {'track': {'id': 't3', 'artists': [{'id': 'a2', 'name': 'Artist 2'}]}},
                {'track': {'id': 't_empty', 'artists': []}},  # Missing artist list
                {'track': None},  # Missing track
            ],
            'next': 'url'
        },
        {
            'items': [
                {'track': {'id': 't4', 'artists': [{'id': 'a2', 'name': 'Artist 2'}]}},
                {'track': {'id': 't5', 'artists': [{'id': 'a3', 'name': 'Artist 3'}]}},
            ],
            'next': None
        }
    ]

    counts, names = unfollowed_liked_artists.count_liked_songs_by_artist(mock_sp)
    assert counts['a1'] == 2
    assert counts['a2'] == 2
    assert counts['a3'] == 1
    assert names['a1'] == 'Artist 1'
    assert names['a2'] == 'Artist 2'
    assert names['a3'] == 'Artist 3'

    # Test empty items break
    mock_sp.current_user_saved_tracks.side_effect = [{'items': []}]
    counts_empty, _ = unfollowed_liked_artists.count_liked_songs_by_artist(mock_sp)
    assert len(counts_empty) == 0


def test_find_unfollowed_liked_artists():
    counts = {'a1': 15, 'a2': 8, 'a3': 12, 'a4': 5}
    names = {'a1': 'Artist 1', 'a2': 'Artist 2', 'a3': 'Artist 3', 'a4': 'Artist 4'}
    followed_ids = {'a1'}

    results = unfollowed_liked_artists.find_unfollowed_liked_artists(counts, names, followed_ids, min_liked=10)
    assert len(results) == 1
    assert results[0]['id'] == 'a3'
    assert results[0]['name'] == 'Artist 3'
    assert results[0]['liked_count'] == 12

    results_5 = unfollowed_liked_artists.find_unfollowed_liked_artists(counts, names, followed_ids, min_liked=5)
    assert len(results_5) == 3
    assert [r['id'] for r in results_5] == ['a3', 'a2', 'a4']


def test_main():
    mock_sp = MagicMock()
    mock_logger = MagicMock()

    with patch('utils.unfollowed_liked_artists.get_followed_artist_ids', return_value={'a1'}), \
         patch('utils.unfollowed_liked_artists.count_liked_songs_by_artist', return_value=({'a2': 15}, {'a2': 'Artist 2'})):

        # Matches found
        res_matched = unfollowed_liked_artists.main(['--min', '10'], client=mock_sp, custom_logger=mock_logger)
        assert len(res_matched) == 1

        # No matches found
        res_unmatched = unfollowed_liked_artists.main(['--min', '20'], client=mock_sp, custom_logger=mock_logger)
        assert len(res_unmatched) == 0
