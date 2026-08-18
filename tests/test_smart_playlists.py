import logging
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pylast
import pytest

import smart_playlists


@pytest.fixture(autouse=True)
def mock_sleep():
    with patch("time.sleep", return_value=None):
        yield


@pytest.fixture
def mock_spotify():
    with patch("smart_playlists.sp") as mock_sp:
        yield mock_sp


@pytest.fixture
def mock_lastfm():
    with patch("smart_playlists.network") as mock_network:
        yield mock_network


def test_print_and_log_handler(capsys):
    handler = smart_playlists.PrintAndLogHandler()
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)

    # Normal unicode message
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Normal message",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    captured = capsys.readouterr()
    assert "Normal message" in captured.out

    # Test UnicodeEncodeError fallback
    with patch.object(
        handler,
        "format",
        side_effect=[UnicodeEncodeError("ascii", "test", 0, 1, "ouch"), "Fallback"],
    ):
        handler.emit(record)
        captured = capsys.readouterr()
        assert "Fallback" in captured.out


def test_create_track_dict():
    track = {
        "uri": "spotify:track:123",
        "name": "Test Track (Remastered)",
        "artists": [{"name": "Test Artist"}],
    }
    # String date
    res_str = smart_playlists._create_track_dict(track, "2026-01-28T13:00:00Z")
    assert res_str is not None
    assert res_str["uri"] == "spotify:track:123"
    assert res_str["name"] == "Test Track (Remastered)"
    assert res_str["artist"] == "Test Artist"
    assert res_str["added_at"] == datetime(2026, 1, 28, 13, 0, 0)
    assert res_str["key"] == "test artist|||test track (remastered)"

    # Datetime date
    dt = datetime(2026, 1, 28, 13, 0, 0)
    res_dt = smart_playlists._create_track_dict(track, dt)
    assert res_dt is not None
    assert res_dt["added_at"] == dt

    # Missing artists fallback
    track_no_artist = {"uri": "spotify:track:456", "name": "Solo"}
    res_no_artist = smart_playlists._create_track_dict(track_no_artist)
    assert res_no_artist is not None
    assert res_no_artist["artist"] == "Unknown"

    # Missing name fallback
    track_no_name = {"uri": "spotify:track:789", "artists": [{"name": "Art"}]}
    res_no_name = smart_playlists._create_track_dict(track_no_name)
    assert res_no_name is not None
    assert res_no_name["name"] == "Unknown"

    # None, empty, or missing uri
    assert smart_playlists._create_track_dict(None) is None
    assert smart_playlists._create_track_dict({}) is None
    assert smart_playlists._create_track_dict({"name": "No URI"}) is None


def test_update_library_with_track_item():
    all_tracks: dict[str, Any] = {}
    # None or empty
    smart_playlists._update_library_with_track_item(all_tracks, None)
    smart_playlists._update_library_with_track_item(all_tracks, {"track": None})
    smart_playlists._update_library_with_track_item(all_tracks, {"track": {"name": "No URI"}})
    assert len(all_tracks) == 0

    item1 = {
        "track": {"uri": "uri1", "name": "Track 1", "artists": [{"name": "A"}]},
        "added_at": "2026-01-28T13:00:00Z",
    }
    smart_playlists._update_library_with_track_item(all_tracks, item1)
    assert "uri1" in all_tracks
    assert all_tracks["uri1"]["added_at"] == datetime(2026, 1, 28, 13, 0, 0)

    # Older date update
    item1_older = {
        "track": {"uri": "uri1", "name": "Track 1", "artists": [{"name": "A"}]},
        "added_at": "2026-01-01T10:00:00Z",
    }
    smart_playlists._update_library_with_track_item(all_tracks, item1_older)
    assert all_tracks["uri1"]["added_at"] == datetime(2026, 1, 1, 10, 0, 0)

    # Newer date ignored
    item1_newer = {
        "track": {"uri": "uri1", "name": "Track 1", "artists": [{"name": "A"}]},
        "added_at": "2026-02-01T10:00:00Z",
    }
    smart_playlists._update_library_with_track_item(all_tracks, item1_newer)
    assert all_tracks["uri1"]["added_at"] == datetime(2026, 1, 1, 10, 0, 0)

    # Update when existing date is None
    all_tracks["uri2"] = {
        "uri": "uri2",
        "name": "Track 2",
        "artist": "A",
        "added_at": None,
        "key": "a|||track 2",
    }
    item2 = {
        "track": {"uri": "uri2", "name": "Track 2", "artists": [{"name": "A"}]},
        "added_at": "2026-01-15T10:00:00Z",
    }
    smart_playlists._update_library_with_track_item(all_tracks, item2)
    assert all_tracks["uri2"]["added_at"] == datetime(2026, 1, 15, 10, 0, 0)


def test_get_all_playlist_tracks(mock_spotify):
    mock_spotify.playlist_tracks.side_effect = [
        {"items": [{"track": {"uri": "1"}}], "next": "url"},
        {"items": [{"track": {"uri": "2"}}, None, {"track": None}], "next": None},
    ]
    tracks = smart_playlists.get_all_playlist_tracks("playlist_id")
    assert len(tracks) == 2
    assert tracks[0]["track"]["uri"] == "1"
    assert tracks[1]["track"]["uri"] == "2"

    # Exception branch
    mock_spotify.playlist_tracks.side_effect = Exception("API error")
    err_tracks = smart_playlists.get_all_playlist_tracks("err_id")
    assert err_tracks == []


def test_get_liked_songs(mock_spotify):
    # Test with 500 items to trigger progress logging
    items_500 = [
        {"track": {"uri": f"u_{i}"}, "added_at": "2026-01-28T13:00:00Z"} for i in range(500)
    ]
    mock_spotify.current_user_saved_tracks.side_effect = [{"items": items_500}, {"items": []}]
    tracks = smart_playlists.get_liked_songs()
    assert len(tracks) == 500


def test_add_liked_songs_to_library(mock_spotify):
    mock_spotify.current_user_saved_tracks.side_effect = [
        {
            "items": [
                {
                    "track": {"uri": "1", "name": "N1", "artists": [{"name": "A1"}]},
                    "added_at": "2026-01-28T13:00:00Z",
                }
            ],
            "next": None,
        },
        {"items": [], "next": None},
    ]
    all_tracks: dict[str, Any] = {}
    smart_playlists._add_liked_songs_to_library(all_tracks)
    assert "1" in all_tracks
    assert all_tracks["1"]["name"] == "N1"


def test_add_playlist_tracks_to_library(mock_spotify):
    mock_spotify.playlist.side_effect = [{"name": "P1"}, Exception("Failed to fetch playlist")]
    with patch("smart_playlists.get_all_playlist_tracks") as mock_get:
        mock_get.return_value = [{"track": {"uri": "t1", "name": "N", "artists": [{"name": "A"}]}}]
        all_tracks: dict[str, Any] = {}
        # Normal
        smart_playlists._add_playlist_tracks_to_library(all_tracks, ["id1"])
        assert "t1" in all_tracks
        # Exception branch
        smart_playlists._add_playlist_tracks_to_library(all_tracks, ["id2"])


def test_get_all_spotify_library_tracks(mock_spotify):
    mock_spotify.auth_manager.get_access_token.side_effect = [
        "token",
        Exception("Auth token error"),
        "token",
    ]

    with (
        patch("smart_playlists._add_liked_songs_to_library") as mock_liked,
        patch("smart_playlists._add_playlist_tracks_to_library") as mock_playlist,
    ):
        # Normal
        result = smart_playlists.get_all_spotify_library_tracks(["ids"])
        assert result == {}
        mock_liked.assert_called_once()
        mock_playlist.assert_called_once()

        # Exception during auth pre-refresh
        smart_playlists.get_all_spotify_library_tracks(["ids"])

        # Exception inside future
        mock_playlist.side_effect = Exception("Worker thread failure")
        smart_playlists.get_all_spotify_library_tracks(["ids"])


def test_update_recent_tracks_playlist(mock_spotify):
    with patch("smart_playlists.create_or_update_playlist") as mock_create_update:
        now = datetime.now()
        library = {
            "t1": {"uri": "t1", "added_at": now - timedelta(days=5)},
            "t2": {"uri": "t2", "added_at": now - timedelta(days=40)},
            "t3": {"uri": "t3", "added_at": now - timedelta(days=2)},
            "t4": {"uri": "t4", "added_at": None},
        }

        smart_playlists.update_recent_tracks_playlist(library, "Target")
        mock_create_update.assert_called_with("Target", ["t3", "t1"])


def test_get_lastfm_track_playcount(mock_lastfm):
    mock_track = MagicMock()
    mock_track.get_userplaycount.return_value = 10
    mock_lastfm.get_track.return_value = mock_track

    count = smart_playlists.get_lastfm_track_playcount("Artist", "Track")
    assert count == 10

    mock_track.get_userplaycount.return_value = None
    assert smart_playlists.get_lastfm_track_playcount("Artist", "Track") == 0

    mock_lastfm.get_track.side_effect = Exception("Error")
    assert smart_playlists.get_lastfm_track_playcount("Artist", "Track") == 0


def test_get_all_lastfm_playcounts(mock_lastfm):
    mock_user = MagicMock()
    mock_lastfm.get_user.return_value = mock_user

    # Generate 500 tracks to trigger progress logging
    tracks_500 = []
    for i in range(500):
        t = MagicMock()
        t.item.artist.name = f"Artist{i}"
        t.item.title = f"Track{i}"
        t.weight = "10"
        tracks_500.append(t)

    mock_user.get_top_tracks.return_value = tracks_500

    result = smart_playlists.get_all_lastfm_playcounts()
    assert len(result) == 500

    # Rate limit exception status 29
    rate_limit_error = pylast.WSError("network", "29", "rate limit")
    mock_user.get_top_tracks.side_effect = rate_limit_error
    assert smart_playlists.get_all_lastfm_playcounts() == {}

    # Other WSError
    other_ws_error = pylast.WSError("network", "50", "other error")
    mock_user.get_top_tracks.side_effect = other_ws_error
    assert smart_playlists.get_all_lastfm_playcounts() == {}

    # Generic Exception
    mock_user.get_top_tracks.side_effect = Exception("Generic error")
    assert smart_playlists.get_all_lastfm_playcounts() == {}


def test_match_spotify_with_lastfm(mock_lastfm):
    # Test with > 100 tracks to trigger progress logging and missing tracks
    spotify_tracks = {f"uri_{i}": {"name": f"Name{i}", "artist": f"Artist{i}"} for i in range(105)}

    with patch("smart_playlists.get_all_lastfm_playcounts") as mock_bulk:
        # Only uri_0 is matched
        mock_bulk.return_value = {"artist0|||name0": 10}

        result = smart_playlists.match_spotify_with_lastfm(spotify_tracks)
        assert len(result) == 105
        assert result[0]["playcount"] == 10
        assert result[1]["playcount"] == 0


def test_retry_on_rate_limit():
    mock_func = MagicMock()
    rate_limit_error = pylast.WSError("network", "29", "rate limit")
    mock_func.side_effect = [rate_limit_error, "success"]

    @smart_playlists.retry_on_rate_limit(max_retries=2, initial_delay=0.1)
    def test_func():
        return mock_func()

    result = test_func()
    assert result == "success"
    assert mock_func.call_count == 2

    # Rate limit exceeded max retries
    mock_func.side_effect = rate_limit_error
    with pytest.raises(pylast.WSError):
        test_func()

    # Other WSError
    other_ws_error = pylast.WSError("network", "50", "server error")
    mock_func.side_effect = other_ws_error
    with pytest.raises(pylast.WSError):
        test_func()

    # Generic exception
    mock_func.side_effect = ValueError("Invalid value")
    with pytest.raises(ValueError):
        test_func()

    # Negative max_retries returning None
    wrapped_negative = smart_playlists.retry_on_rate_limit(max_retries=-1)(lambda: None)
    assert wrapped_negative() is None


def test_create_or_update_playlist(mock_spotify):
    # Existing playlist with tracks (multiple batches)
    mock_spotify.current_user_playlists.return_value = {"items": [{"name": "P1", "id": "p1"}]}
    tracks_150 = [f"t{i}" for i in range(150)]
    smart_playlists.create_or_update_playlist("P1", tracks_150)
    mock_spotify.playlist_replace_items.assert_called_with("p1", [])
    assert mock_spotify.playlist_add_items.call_count == 2
    mock_spotify.playlist_add_items.assert_any_call("p1", tracks_150[:100])
    mock_spotify.playlist_add_items.assert_any_call("p1", tracks_150[100:])

    # New playlist with empty track_uris
    mock_spotify.current_user_playlists.return_value = {"items": []}
    mock_spotify.current_user.return_value = {"id": "user_id"}
    mock_spotify.user_playlist_create.return_value = {"id": "p2"}
    smart_playlists.create_or_update_playlist("P2", [])
    mock_spotify.user_playlist_create.assert_called_with("user_id", "P2", public=True)


def test_update_playcount_playlists(mock_spotify):
    # Generate 30 tracks to test >= 25 limit and group sorting
    tracks = [
        {"uri": f"t_{i}", "artist": f"A_{i}", "name": f"N_{i}", "playcount": (i % 5) + 1}
        for i in range(30)
    ]

    with (
        patch("smart_playlists.match_spotify_with_lastfm", return_value=tracks),
        patch("smart_playlists.create_or_update_playlist") as mock_create_update,
    ):
        smart_playlists.update_playcount_playlists({}, "Top", "Bottom")
        assert mock_create_update.call_count == 2


def test_format_elapsed_time():
    assert smart_playlists.format_elapsed_time(3665) == "1h 1m 5s"
    assert smart_playlists.format_elapsed_time(125) == "2m 5s"
    assert smart_playlists.format_elapsed_time(42) == "42s"


def test_main():
    with (
        patch("smart_playlists.get_all_spotify_library_tracks", return_value={}) as mock_lib,
        patch("smart_playlists.update_recent_tracks_playlist") as mock_recent,
        patch("smart_playlists.update_playcount_playlists") as mock_playcount,
        patch.dict(
            "os.environ",
            {
                "SOURCE_PLAYLIST_IDS": "p1,p2",
                "TARGET_PLAYLIST_NAME": "Recent",
                "TOP_25_PLAYLIST_NAME": "Top 25",
                "BOTTOM_25_PLAYLIST_NAME": "Bottom 25",
            },
        ),
    ):
        smart_playlists.main()
        mock_lib.assert_called_once_with(["p1", "p2"])
        mock_recent.assert_called_once_with({}, "Recent")
        mock_playcount.assert_called_once_with({}, "Top 25", "Bottom 25")
