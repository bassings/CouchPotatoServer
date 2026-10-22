"""Keep patched libc packages in both build and shipped image stages."""

import re
import shlex
from pathlib import Path

import pytest


@pytest.mark.parametrize('stage', ['builder', 'runtime'])
@pytest.mark.parametrize('package', ['musl', 'musl-utils'])
def test_each_stage_requires_patched_musl(stage, package):
    dockerfile = (Path(__file__).resolve().parents[2] / 'Dockerfile').read_text()
    # Parse executable RUN instructions, excluding comments and other stages.
    stages = re.split(r'^FROM\s+[^\n]+\n', dockerfile, flags=re.MULTILINE)[1:]
    assert len(stages) == 2
    instructions = stages[0 if stage == 'builder' else 1].replace('\\\n', ' ')
    packages = []
    for command in re.findall(r'^RUN\s+([^\n]+)', instructions, flags=re.MULTILINE):
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|')
        lexer.whitespace_split = True
        tokens = []
        for token in lexer:
            if token in {';', '&&', '||', '&', '|'}:
                break
            tokens.append(token)
        if tokens[:2] == ['apk', 'add']:
            packages.extend(tokens[2:])

    assert f'{package}>=1.2.6-r3' in packages, (
        f'{stage} must install {package}>=1.2.6-r3 to fix CVE-2026-107891'
    )
