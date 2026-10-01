"""Network-free regression tests for complete image delivery."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from engine.publish import telegram_publisher as tg
from engine.publish import x_publisher as xp


def slides(tmp_path: Path, count: int = 8) -> list[Path]:
    paths = [tmp_path / f'S{i}.png' for i in range(count)]
    for path in paths:
        Image.new('RGB', (12, 12), 'white').save(path)
    return paths


def script() -> dict:
    return {'caption_x_final': xp.DISCLAIMER_REQUIRED}


@pytest.mark.parametrize('publisher', ['x', 'tg'])
@pytest.mark.parametrize('defect', ['missing', 'corrupt'])
def test_preflight_checks_all_images_before_any_network(tmp_path, monkeypatch, publisher, defect):
    paths = slides(tmp_path)
    if defect == 'missing':
        paths[-1].unlink()
    else:
        paths[-1].write_bytes(b'not an image')
    network = MagicMock()
    if publisher == 'x':
        monkeypatch.setattr(xp, '_make_clients', network)
        def invoke():
            return xp.publish_episode_x(script(), paths, dry_run=False)
    else:
        monkeypatch.setattr(tg.requests, 'post', network)
        def invoke():
            return tg.publish_episode_telegram({}, paths, ['channel'], dry_run=False)
    with pytest.raises((ValueError, OSError)):
        invoke()
    network.assert_not_called()


@pytest.mark.parametrize('media_id', [None, '', 0])
def test_x_missing_upload_id_never_creates_tweet(tmp_path, monkeypatch, media_id):
    api, client = MagicMock(), MagicMock()
    api.media_upload.return_value = SimpleNamespace(media_id=media_id)
    monkeypatch.setattr(xp, '_make_clients', lambda: (api, client))
    with pytest.raises(ValueError):
        xp.publish_episode_x(script(), slides(tmp_path), dry_run=False)
    client.create_tweet.assert_not_called()


def test_x_upload_count_mismatch_never_creates_tweet(tmp_path, monkeypatch):
    api, client = MagicMock(), MagicMock()
    monkeypatch.setattr(xp, '_make_clients', lambda: (api, client))
    monkeypatch.setattr(xp, '_upload_media', lambda *args: [])
    with pytest.raises(ValueError, match='incomplete'):
        xp.publish_episode_x(script(), slides(tmp_path), dry_run=False)
    client.create_tweet.assert_not_called()


def test_x_missing_tweet_id_stops_remaining_parts(tmp_path, monkeypatch):
    api, client = MagicMock(), MagicMock()
    api.media_upload.return_value = SimpleNamespace(media_id=123)
    client.create_tweet.return_value = SimpleNamespace(data={'id': None})
    monkeypatch.setattr(xp, '_make_clients', lambda: (api, client))
    with pytest.raises(ValueError, match='reconciliation'):
        xp.publish_episode_x(script(), slides(tmp_path), dry_run=False)
    assert client.create_tweet.call_count == 1


def album(count):
    return {'ok': True, 'result': [{'message_id': i + 1} for i in range(count)]}


@pytest.mark.parametrize('bad_response', [None, {'ok': False}, {'ok': True, 'result': []},
    {'ok': True, 'result': [{'message_id': None}] * 10},
    {'ok': True, 'result': [{'message_id': True}] * 10}])
def test_telegram_first_batch_failure_stops_later_batch(tmp_path, monkeypatch, bad_response):
    send = MagicMock(side_effect=[bad_response, album(10)])
    monkeypatch.setattr(tg, '_get_bot_token', lambda: 'fake')
    monkeypatch.setattr(tg, '_send_media_group', send)
    result = tg.publish_episode_telegram({}, slides(tmp_path, 20), ['channel'], dry_run=False)
    assert result == {'channel': False}
    assert send.call_count == 1


def test_telegram_all_batches_success(tmp_path, monkeypatch):
    send = MagicMock(side_effect=[album(10), album(2)])
    monkeypatch.setattr(tg, '_get_bot_token', lambda: 'fake')
    monkeypatch.setattr(tg, '_send_media_group', send)
    monkeypatch.setattr(tg.time, 'sleep', lambda _: None)
    assert tg.publish_episode_telegram({}, slides(tmp_path, 12), ['channel'], dry_run=False) == {'channel': True}
    assert send.call_count == 2


def test_telegram_http200_invalid_album_is_failure(tmp_path, monkeypatch):
    post = MagicMock()
    post.return_value.json.return_value = {'ok': True, 'result': [{'message_id': 1}]}
    monkeypatch.setattr(tg.requests, 'post', post)
    assert tg._send_media_group('fake', 'channel', slides(tmp_path, 2), '') is None
    for file in post.call_args.kwargs['files'].values():
        assert file.closed


def test_telegram_later_batch_failure_keeps_channel_failed(tmp_path, monkeypatch):
    send = MagicMock(side_effect=[album(10), None, album(2)])
    monkeypatch.setattr(tg, '_get_bot_token', lambda: 'fake')
    monkeypatch.setattr(tg, '_send_media_group', send)
    monkeypatch.setattr(tg.time, 'sleep', lambda _: None)
    assert tg.publish_episode_telegram({}, slides(tmp_path, 22), ['channel'], dry_run=False) == {'channel': False}
    assert send.call_count == 2


def test_telegram_duplicate_message_ids_are_not_complete():
    assert not tg._valid_album_response({'ok': True, 'result': [{'message_id': 1}] * 2}, 2)


def test_x_complete_delivery_retains_four_part_thread(tmp_path, monkeypatch):
    api, client = MagicMock(), MagicMock()
    api.media_upload.side_effect = [SimpleNamespace(media_id=i) for i in range(1, 9)]
    client.create_tweet.side_effect = [SimpleNamespace(data={'id': str(i)}) for i in range(1, 5)]
    monkeypatch.setattr(xp, '_make_clients', lambda: (api, client))
    monkeypatch.setattr(xp.time, 'sleep', lambda _: None)
    assert xp.publish_episode_x(script(), slides(tmp_path), dry_run=False) == ['1', '2', '3', '4']
    assert api.media_upload.call_count == 8
    assert [len(call.kwargs['media_ids']) for call in client.create_tweet.call_args_list] == [1, 3, 3, 1]
    assert client.create_tweet.call_args_list[-1].kwargs['in_reply_to_tweet_id'] == '3'
