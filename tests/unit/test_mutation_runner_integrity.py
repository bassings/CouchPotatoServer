"""Exercise the configured JS runner against an actual, known broken mutant."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_configured_js_runner_rejects_a_real_arithmetic_mutation(tmp_path):
    # Reuse the installed toolchain and the actual runner/coverage configuration.
    # Only fixture sources, report format and concurrency differ from a full run.
    (tmp_path / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
    (tmp_path / 'package.json').write_text((ROOT / 'package.json').read_text())
    (tmp_path / 'vitest.config.mts').write_text('''
import { defineConfig } from 'vitest/config';
export default defineConfig({ test: { environment: 'node', include: ['tests/unit/ui/*.spec.ts'] } });
''')
    source = tmp_path / 'couchpotato/static/scripts/ui/canary.js'
    source.parent.mkdir(parents=True)
    source.write_text('export function increment(value) { return value + 1; }\n')
    test = tmp_path / 'tests/unit/ui/canary.spec.ts'
    test.parent.mkdir(parents=True)
    test.write_text('''
import { describe, it, expect } from 'vitest';
import { increment } from '../../../couchpotato/static/scripts/ui/canary.js';
describe('increment contract', () => {
  it('adds one', () => { expect(increment(2)).toBe(3); });
});
''')
    config = json.loads((ROOT / 'stryker.conf.json').read_text())
    config.update(reporters=['json'], concurrency=1, cleanTempDir='always')
    (tmp_path / 'stryker.conf.json').write_text(json.dumps(config))
    # Do not let an outer mutation run leak its active ID into this clean probe.
    env = {key: value for key, value in os.environ.items()
           if key != '__STRYKER_ACTIVE_MUTANT__'}
    result = subprocess.run([str(ROOT / 'node_modules/.bin/stryker'), 'run'],
                            cwd=tmp_path, env=env, text=True, capture_output=True, timeout=50)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/mutation/mutation.json').read_text())
    mutants = report['files']['couchpotato/static/scripts/ui/canary.js']['mutants']
    arithmetic = [mutant for mutant in mutants if mutant['mutatorName'] == 'ArithmeticOperator']
    assert len(arithmetic) == 1, mutants
    assert arithmetic[0]['status'] == 'Killed', arithmetic[0]
