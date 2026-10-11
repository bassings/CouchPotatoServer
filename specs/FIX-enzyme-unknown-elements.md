# Unknown EBML element log noise

Issue: [#544](https://github.com/bassings/CouchPotatoServer/issues/544).

## Problem

The pinned Enzyme parser logs every unknown EBML element at ERROR even when
it skips the element and successfully returns video metadata. A production
scan emitted 61 such messages in about one second. The scanner currently
logs actual parser failures only at DEBUG.

## Acceptance criteria

1. A real MKV with an unknown EBML element still yields usable video metadata.
2. The exact Enzyme `Element with id 0x... is not in the specs` diagnostic is
   suppressed in production logging. Other Enzyme error messages are not.
3. A genuinely unreadable MKV produces an operator-visible warning without
   its private filesystem path. Ordinary MP4 files do not produce MKV parser
   warnings.
4. The tests use a synthetic MKV fixture and fail when the narrow filter or
   the real parse-failure warning is removed.
