"""Database fixture loading and management helpers."""
import json
import os


def load_fixture_data(fixtures_dir, filename='sample_data.json'):
    """Load fixture data from JSON file."""
    path = os.path.join(fixtures_dir, filename)
    with open(path, 'r') as f:
        return json.load(f)


def get_media_by_status(data, status):
    """Filter media records by status."""
    return [m for m in data.get('media', []) if m.get('status') == status]


def get_media_by_imdb(data, imdb_id):
    """Find a media record by IMDB identifier."""
    for m in data.get('media', []):
        if m.get('identifiers', {}).get('imdb') == imdb_id:
            return m
    return None


def get_releases_for_quality(data, quality):
    """Filter releases by quality."""
    return [r for r in data.get('release', []) if r.get('quality') == quality]


def count_records_by_type(data):
    """Count records grouped by _t type across all collections."""
    counts = {}
    for key, records in data.items():
        if key == '_meta':
            continue
        if isinstance(records, list):
            counts[key] = len(records)
    return counts
