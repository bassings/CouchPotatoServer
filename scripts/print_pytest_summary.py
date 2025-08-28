#!/usr/bin/env python3
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

def main():
    report = Path('pytest-report.xml')
    if not report.exists():
        print('pytest-report.xml not found')
        return 0
    try:
        tree = ET.parse(str(report))
        root = tree.getroot()
        ts = root.find('testsuite') or root
        tests = (ts.get('tests') or ts.attrib.get('tests') or '0')
        errors = (ts.get('errors') or ts.attrib.get('errors') or '0')
        failures = (ts.get('failures') or ts.attrib.get('failures') or '0')
        skipped = (ts.get('skipped') or ts.attrib.get('skipped') or '0')
        print(f'Total: tests={tests} failures={failures} errors={errors} skipped={skipped}')
        idx = 0
        for case in root.iter('testcase'):
            for tag in ('failure', 'error'):
                fe = case.find(tag)
                if fe is not None:
                    idx += 1
                    cls = case.get('classname', '')
                    name = case.get('name', '')
                    msg = fe.get('message', '')
                    text = (fe.text or '').strip()
                    print(f'[{idx}] {cls}::{name}\nMessage: {msg}\n{text[:2000]}\n')
        return 0
    except Exception as e:
        print('Could not parse pytest-report.xml:', e)
        return 0

if __name__ == '__main__':
    sys.exit(main())

