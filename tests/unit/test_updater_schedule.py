"""Guard the shared updater scheduler job identifier."""

from types import SimpleNamespace

from couchpotato.core._base.updater import main as updater_module


def test_updater_replaces_the_same_scheduled_job(monkeypatch):
    assert updater_module.UPDATE_CHECK_JOB == 'updater.check'
    job = 'sentinel.update-check'
    monkeypatch.setattr(updater_module, 'UPDATE_CHECK_JOB', job)
    calls = []
    monkeypatch.setattr(updater_module, 'fireEvent', lambda *args, **kwargs: calls.append((args, kwargs)))
    update_calls = []
    updater = SimpleNamespace(
        isEnabled=lambda: True,
        conf=lambda key, default=None: 12,
        autoUpdate=lambda: update_calls.append(True),
    )

    updater_module.Updater.setCrons(updater)

    assert calls[0] == (('schedule.remove', job), {'single': True})
    assert calls[1] == (('schedule.interval', job, updater.autoUpdate), {'hours': 12})
    assert update_calls == [True]
