"""NZBGet status estimates use API-shaped group and status payloads."""

from unittest.mock import MagicMock

import pytest

from couchpotato.core.downloaders.nzbget import NZBGet


@pytest.mark.parametrize('active,paused,rate,expected', [
    (1, False, 1024 * 1024, '0:00:10'),
    (0, False, 1024 * 1024, -1),
    (1, True, 1024 * 1024, -1),
    (1, False, 0, -1),
])
def test_group_timeleft_uses_status_rate_and_group_remaining_mib(
    active, paused, rate, expected,
):
    downloader = NZBGet.__new__(NZBGet)
    downloader.getName = MagicMock(return_value='NZBGet')
    downloader.getRPC = MagicMock()
    rpc = downloader.getRPC.return_value
    rpc.writelog.return_value = True
    # These are the documented fields on the two separate NZBGet responses.
    # Deprecated Download2Paused and a per-group DownloadRate are absent.
    rpc.status.return_value = {'DownloadRate': rate, 'DownloadPaused': paused, 'PostPaused': False}
    rpc.listgroups.return_value = [{
        'NZBID': 17,
        'NZBFilename': 'Movie.nzb',
        'Parameters': [],
        'ActiveDownloads': active,
        'RemainingSizeMB': 10,
    }]
    rpc.postqueue.return_value = []
    rpc.history.return_value = []

    downloads = downloader.getAllDownloadStatus([17])

    assert len(downloads) == 1
    assert downloads[0]['id'] == 17
    assert downloads[0]['timeleft'] == expected
    assert downloads[0]['original_status'] == ('DOWNLOADING' if active else 'QUEUED')


@pytest.mark.parametrize('remaining_mib,rate_lo,rate_hi,expected', [
    (10, 1024 * 1024, 0, '0:00:10'),
    (4096, 0, 1, '0:00:01'),
])
def test_group_timeleft_accepts_split_rate_fields_without_legacy_rate(
    remaining_mib, rate_lo, rate_hi, expected,
):
    downloader = NZBGet.__new__(NZBGet)
    downloader.getName = MagicMock(return_value='NZBGet')
    downloader.getRPC = MagicMock()
    rpc = downloader.getRPC.return_value
    rpc.writelog.return_value = True
    rpc.status.return_value = {
        'DownloadRateLo': rate_lo,
        'DownloadRateHi': rate_hi,
        'DownloadPaused': False,
    }
    rpc.listgroups.return_value = [{
        'NZBID': 17,
        'NZBFilename': 'Movie.nzb',
        'Parameters': [],
        'ActiveDownloads': 1,
        'RemainingSizeMB': remaining_mib,
    }]
    rpc.postqueue.return_value = []
    rpc.history.return_value = []

    downloads = downloader.getAllDownloadStatus([17])

    assert len(downloads) == 1
    assert downloads[0]['timeleft'] == expected


@pytest.mark.parametrize('paused,expected', [(False, '0:00:00'), (True, -1)])
def test_postprocessing_queue_keeps_pause_mapping(paused, expected):
    downloader = NZBGet.__new__(NZBGet)
    downloader.getName = MagicMock(return_value='NZBGet')
    downloader.getRPC = MagicMock()
    rpc = downloader.getRPC.return_value
    rpc.writelog.return_value = True
    rpc.status.return_value = {'PostPaused': paused}
    rpc.listgroups.return_value = []
    rpc.postqueue.return_value = [{'NZBID': 19, 'NZBFilename': 'Post.nzb', 'Stage': 'UNPACKING'}]
    rpc.history.return_value = []

    downloads = downloader.getAllDownloadStatus([19])

    assert len(downloads) == 1
    assert downloads[0]['id'] == 19
    assert downloads[0]['name'] == 'Post.nzb'
    assert downloads[0]['original_status'] == 'UNPACKING'
    assert downloads[0]['timeleft'] == expected


@pytest.mark.parametrize('status,expected', [('SUCCESS/ALL', 'completed'), ('FAILURE/HEALTH', 'failed')])
def test_history_keeps_terminal_status_and_destination(status, expected):
    downloader = NZBGet.__new__(NZBGet)
    downloader.getName = MagicMock(return_value='NZBGet')
    downloader.getRPC = MagicMock()
    rpc = downloader.getRPC.return_value
    rpc.writelog.return_value = True
    rpc.status.return_value = {}
    rpc.listgroups.return_value = []
    rpc.postqueue.return_value = []
    rpc.history.return_value = [{
        'NZBID': 23,
        'NZBFilename': 'History.nzb',
        'Parameters': [],
        'Status': status,
        'ParStatus': 'SUCCESS',
        'ScriptStatus': 'SUCCESS',
        'Log': [],
        'DestDir': '/downloads/history',
    }]

    downloads = downloader.getAllDownloadStatus([23])

    assert len(downloads) == 1
    assert downloads[0]['id'] == 23
    assert downloads[0]['name'] == 'History.nzb'
    assert downloads[0]['status'] == expected
    assert downloads[0]['original_status'] == status
    assert downloads[0]['timeleft'] == '0:00:00'
    assert downloads[0]['folder'] == '/downloads/history'
