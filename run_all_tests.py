#!/usr/bin/env python3
"""
Convenience runner to execute the full pytest suite locally or in containers.
"""
import os
import sys
import subprocess

def main() -> int:
    env = os.environ.copy()
    # Ensure vendored libs are importable like in runtime
    env['PYTHONPATH'] = f"{env.get('PYTHONPATH', '')}:{os.path.abspath('libs')}"
    cmd = [sys.executable, '-m', 'pytest', '-q']
    return subprocess.call(cmd, env=env)

if __name__ == '__main__':
    raise SystemExit(main())

