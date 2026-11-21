"""SEC-005: the characters a Jackett address may not contain are one exact set.

``_UNSAFE_ADDRESS`` was rewritten so its ranges no longer overlap (python:S5869).
This pins the set it matches, code point by code point, against the pattern as it
was written before, so the rewrite cannot have widened or narrowed what is refused.
"""
import re
import sys

from couchpotato.core.media._base.providers.torrent.torrentpotato import _UNSAFE_ADDRESS

# The pattern before the rewrite, written out as the reference. Python's `\s` on
# text is the Unicode whitespace set, which overlaps the control range.
REFERENCE = re.compile(r'[\s\x00-\x1f\x7f\\?#]')


def _matched(pattern):
    return {code for code in range(sys.maxunicode + 1)
            if not 0xD800 <= code <= 0xDFFF and pattern.match(chr(code))}


def test_refuses_exactly_the_characters_the_original_pattern_refused():
    assert _matched(_UNSAFE_ADDRESS) == _matched(REFERENCE)


def test_the_reference_is_not_empty_and_reaches_beyond_ascii():
    refused = _matched(REFERENCE)
    assert {0x00, 0x20, 0x7F, 0x5C, 0x3F, 0x23} <= refused
    assert {0x85, 0xA0, 0x2028, 0x3000} <= refused
