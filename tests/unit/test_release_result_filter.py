"""Candidate selection and dispatch contract for release.tryDownloadResult."""

from unittest.mock import patch

from couchpotato.core.plugins.release.main import Release


def candidate(name, **changes):
    result = {'name': name, 'status': 'available', 'score': 10,
              'size': 51, 'seeders': 1, 'age': 3}
    result.update(changes)
    return result


def run(results, quality, outcomes=None):
    attempted = []

    def download(event, **kwargs):
        assert event == 'release.download'
        attempted.append(kwargs['data'])
        return (outcomes or {}).get(kwargs['data']['name'], 'try_next')

    with patch('couchpotato.core.plugins.release.main.Env.setting', return_value=1), \
            patch('couchpotato.core.plugins.release.main.fireEvent', side_effect=download):
        result = object.__new__(Release).tryDownloadResult(
            results, {'_id': 'movie-1'}, quality,
        )
    return result, attempted


def test_filters_rejected_candidates_and_preserves_accepted_identity():
    accepted = candidate('accepted')
    final = candidate('final')
    results = [
        candidate('ignored', status='ignored'),
        candidate('failed', status='failed'),
        candidate('low-score', score=9),
        candidate('small', size=50),
        candidate('unseeded', seeders=0),
        accepted,
        final,
    ]

    result, attempted = run(
        results, {'minimum_score': 10, 'index': 0},
        {'accepted': 'try_next', 'final': True},
    )

    assert result is True
    assert attempted == [accepted, final]
    assert attempted[0] is accepted
    assert attempted[1] is final
    assert accepted['wait_for'] is False
    assert final['wait_for'] is False
    assert all('wait_for' not in item for item in results[:5])


def test_waits_when_every_eligible_candidate_is_too_new():
    young = candidate('young', age=2)
    eligible = candidate('eligible', age=4)

    result, attempted = run(
        [candidate('ignored', status='ignored'), young, eligible],
        {'minimum_score': 10, 'index': 1, 'wait_for': 5},
    )

    assert result is True
    assert attempted == []
    assert young['wait_for'] is True
    assert eligible['wait_for'] is True


def test_one_old_candidate_releases_all_eligible_candidates_from_wait():
    young = candidate('young', age=2)
    old = candidate('old', age=6)

    result, attempted = run(
        [young, old], {'minimum_score': 10, 'index': 1, 'wait_for': 5},
    )

    assert result is False
    assert attempted == [young, old]
    assert young['wait_for'] is True
    assert old['wait_for'] is False


def test_no_eligible_candidates_returns_false_without_dispatch():
    result, attempted = run(
        [candidate('small', size=50)],
        {'minimum_score': 10, 'index': 0},
    )

    assert result is False
    assert attempted == []
