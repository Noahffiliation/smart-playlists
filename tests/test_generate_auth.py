import pytest
from unittest.mock import MagicMock, patch
from utils.generate_auth import generate_master_cache


def test_generate_master_cache():
    mock_sp = MagicMock()
    mock_sp.current_user.return_value = {'id': 'user_123'}

    user = generate_master_cache(client=mock_sp)
    assert user['id'] == 'user_123'
    mock_sp.current_user.assert_called_once()
