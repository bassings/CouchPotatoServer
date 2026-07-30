#!/usr/bin/env bash
#
# backup.sh — snapshot the CouchPotato SQLite database + settings.
#
# Run this BEFORE every prod promotion, and nightly from cron. A promotion is
# only reversible if the database was captured first: `:latest` has already
# moved by deploy time, so "re-pull the old image" does not recover data.
# Full procedure: docs/development-process.md → "Deploying to prod".
#
# The DB is copied with sqlite3's `.backup` (or Python's sqlite3 backup API when
# the CLI is missing/broken) — both are safe against a live database. A plain
# `cp` of an in-use SQLite file can capture a torn page, which looks like a
# successful backup and only fails when you try to restore it.
#
# Usage:
#   ./scripts/backup.sh                 # snapshot, keep everything
#   ./scripts/backup.sh --retain 14     # snapshot, then keep the 14 newest
#
# Env:
#   CP_DATA_DIR   CouchPotato data dir (holds config.ini + database_v2/)
#                 default: /var/lib/plexmediaserver/CouchPotato/config/data
#   BACKUP_DIR    where snapshots are written
#                 default: /var/lib/plexmediaserver/CouchPotato/backups
#
# Writes <BACKUP_DIR>/<YYYYMMDD-HHMMSS>/{couchpotato.db,config.ini}.
#
# NOTE: `config.bak/` in the prod directory must NEVER be deleted. This script
# only ever prunes its own timestamped output directories, never anything else
# in BACKUP_DIR and nothing at all outside it — see the regex in prune_snapshots.

set -euo pipefail

CP_DATA_DIR="${CP_DATA_DIR:-/var/lib/plexmediaserver/CouchPotato/config/data}"
BACKUP_DIR="${BACKUP_DIR:-/var/lib/plexmediaserver/CouchPotato/backups}"
# Strip a trailing slash immediately. `dirname` normalises it away, so a
# `BACKUP_DIR=/path/backups/` compared against `$(dirname "$victim")` never
# matched and retention was silently disabled: exit 0, no warning, disk grows
# forever. Normalise once here rather than at each use.
BACKUP_DIR="${BACKUP_DIR%/}"
RETAIN=""

# The `|| :` on each of these is load-bearing, not defensive noise. Under
# `set -e` a logging call is a statement like any other, so if the write fails
# (stderr closed, full log partition) the script dies at the log line — turning a
# perfectly recoverable backup into "NO BACKUP WAS TAKEN". Logging must never be
# able to fail the run.
die() { printf 'backup.sh: %s\n' "$1" >&2 || :; exit 1; }
info() { printf 'backup.sh: %s\n' "$1" || :; }
warn() { printf 'backup.sh: WARNING: %s\n' "$1" >&2 || :; }

usage() {
  # Printed literally rather than sed'd out of the header: a hardcoded line
  # range (`sed -n '3,29p'`) silently desyncs the moment the comment block above
  # changes length, and nothing detects it.
  cat <<'USAGE'
backup.sh — snapshot the CouchPotato SQLite database + settings.

Run before every prod promotion, and nightly from cron. Uses sqlite3 `.backup`
(or Python's sqlite3 backup API) so the copy is safe against a live database.

Usage:
  ./scripts/backup.sh                 snapshot, keep everything
  ./scripts/backup.sh --retain 14     snapshot, then keep the 14 newest
  ./scripts/backup.sh --retain=14     same, = form
  ./scripts/backup.sh --help          this message

Env:
  CP_DATA_DIR   data dir holding config.ini + database_v2/
                default: /var/lib/plexmediaserver/CouchPotato/config/data
  BACKUP_DIR    where snapshots are written
                default: /var/lib/plexmediaserver/CouchPotato/backups

Writes <BACKUP_DIR>/<YYYYMMDD-HHMMSS>/{couchpotato.db,config.ini}.
Full procedure: docs/development-process.md -> "Deploying to prod".
USAGE
  exit 0
}

RETAIN_GIVEN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --retain)
      [ $# -ge 2 ] || die "--retain needs a value"
      RETAIN="$2"
      RETAIN_GIVEN=1
      shift 2
      ;;
    --retain=*)
      RETAIN="${1#*=}"
      RETAIN_GIVEN=1
      shift
      ;;
    -h|--help) usage ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

# Validate on "was the flag given", not on "is the value non-empty": keying off
# emptiness meant `--retain ''` skipped validation entirely and silently disabled
# retention, which looks identical to not passing the flag at all.
if [ "$RETAIN_GIVEN" -eq 1 ]; then
  case "$RETAIN" in
    ''|*[!0-9]*) die "--retain must be a positive integer, got '$RETAIN'" ;;
  esac
  # Length-check before the arithmetic comparison: `[ 99999999999999999999999
  # -ge 1 ]` leaks a raw "bash: [: integer expression expected" first.
  [ "${#RETAIN}" -le 9 ] || die "--retain is implausibly large: '$RETAIN'"
  # Guard against `--retain 0` being read as "keep nothing", which would delete
  # the snapshot this run just took.
  [ "$RETAIN" -ge 1 ] || die "--retain must be >= 1, got '$RETAIN' (refusing to delete every snapshot)"
fi

DB_SRC="$CP_DATA_DIR/database_v2/couchpotato.db"

# config.ini location differs between layouts, so look in both rather than
# quietly snapshotting the database alone:
#   * DATA_DIR/config.ini      — what `couchpotato/runner.py:48` defaults to
#   * DATA_DIR/../config.ini   — what the Docker image uses, where
#                                `--config_file=/config/config.ini` sits one
#                                level above `--data_dir=/data`
# Picking the wrong one is invisible: the script warns and exits 0, so a nightly
# cron reports success forever while never capturing settings.
SETTINGS_SRC=""
for candidate in "$CP_DATA_DIR/config.ini" "$CP_DATA_DIR/../config.ini"; do
  if [ -f "$candidate" ]; then
    SETTINGS_SRC="$candidate"
    break
  fi
done

[ -f "$DB_SRC" ] || die "database not found: $DB_SRC (is CP_DATA_DIR correct?)"

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/$STAMP"

# Two runs inside the same second would share $DEST, and the cleanup on failure
# (`rm -rf "$DEST"`) would then destroy the FIRST run's perfectly good snapshot.
# Suffix on collision so a snapshot is never clobbered by a later one.
if [ -e "$DEST" ]; then
  suffix=2
  while [ -e "${DEST}-${suffix}" ]; do
    suffix=$((suffix + 1))
  done
  warn "$DEST already exists — writing ${DEST}-${suffix} instead so the existing snapshot is not touched"
  DEST="${DEST}-${suffix}"
fi

# ── Database ────────────────────────────────────────────────────────────────
# Try the sqlite3 CLI, then Python. Never fall through to `cp`.
backup_with_sqlite3() {
  command -v sqlite3 >/dev/null 2>&1 || return 1
  sqlite3 "$DB_SRC" ".backup '$DEST/couchpotato.db'" 2>/dev/null
}

backup_with_python() {
  local py=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then py="$candidate"; break; fi
  done
  [ -n "$py" ] || return 1

  # Clear anything sqlite3 left behind. A broken-but-present sqlite3 can write a
  # torn header before failing, and sqlite3.connect() on that raises
  # "file is not a database" — defeating the fallback in exactly the
  # "present but broken" case it exists for.
  rm -f "$DEST/couchpotato.db"

  "$py" - "$DB_SRC" "$DEST/couchpotato.db" <<'PY'
import sqlite3
import sys

src, dst = sys.argv[1], sys.argv[2]
source = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
try:
    target = sqlite3.connect(dst)
    try:
        with target:
            source.backup(target)
    finally:
        target.close()
finally:
    source.close()
PY
}

mkdir -p "$DEST"

if backup_with_sqlite3; then
  info "database snapshot written with sqlite3 .backup"
else
  # `warn` must NOT be part of the fallback condition. As `elif warn ... &&
  # backup_with_python`, a failed stderr write (closed fd, full log partition)
  # made `warn` return non-zero, short-circuited the `&&`, and reported
  # "NO BACKUP WAS TAKEN" on a host where the Python fallback worked perfectly.
  warn "sqlite3 unavailable or failed — falling back to the Python sqlite3 backup API"
  if backup_with_python; then
    info "database snapshot written with Python sqlite3.backup()"
  else
    # Don't leave a half-written snapshot that looks like a good backup.
    rm -rf "$DEST"
    die "could not back up $DB_SRC — neither sqlite3 nor Python was usable. NO BACKUP WAS TAKEN."
  fi
fi

# ── Settings ────────────────────────────────────────────────────────────────
# Missing settings is odd but must not cost you the database snapshot.
if [ -n "$SETTINGS_SRC" ] && [ -f "$SETTINGS_SRC" ]; then
  cp "$SETTINGS_SRC" "$DEST/config.ini"
  info "settings snapshot written from $SETTINGS_SRC"
else
  warn "config.ini not found (looked in $CP_DATA_DIR and $CP_DATA_DIR/..) — snapshot contains the database only"
fi

info "snapshot complete: $DEST"

# ── Retention ───────────────────────────────────────────────────────────────
# Only ever deletes directories directly under BACKUP_DIR whose names are
# exactly our own YYYYMMDD-HHMMSS stamp. Unrelated files and directories
# (and anything outside BACKUP_DIR, e.g. config.bak/) are never candidates.
#
# Implementation note — this deliberately does NOT pipe paths into
# `head | while read`. Two real defects came from that:
#   1. `read` splits on newlines, so a newline anywhere in BACKUP_DIR truncated
#      each path and `rm -rf` was handed a DIFFERENT, unrelated directory
#      outside BACKUP_DIR (reproduced), while pruning nothing.
#   2. `set -o pipefail` + `head` closing the pipe early made the whole script
#      exit 141 (SIGPIPE) on a *successful* backup once the snapshot list
#      exceeded the pipe buffer (~1050 snapshots at the default path length), so
#      cron reported failure for a good backup.
# The array is already correct; sort and slice it in-process instead.
prune_snapshots() {
  local keep="$1"
  local snaps=()
  local entry base

  for entry in "$BACKUP_DIR"/*; do
    [ -d "$entry" ] || continue
    base="${entry##*/}"
    # The optional `-N` matches the same-second collision suffix written below.
    # Without it, a `<stamp>-2` directory was neither counted nor prunable, so two
    # runs in one second left a snapshot that retention could never reclaim — two
    # behaviours added in the same change, mutually inconsistent.
    if [[ "$base" =~ ^[0-9]{8}-[0-9]{6}(-[0-9]+)?$ ]]; then
      snaps+=("$entry")
    fi
  done

  local total=${#snaps[@]}
  [ "$total" -gt "$keep" ] || return 0

  # Sort by the stamp (the basename), not the full path. In practice bash's glob
  # already returns `"$BACKUP_DIR"/*` in sorted order and every entry shares the
  # same prefix, so this is belt-and-braces rather than load-bearing; it exists so
  # the ordering does not depend on glob behaviour. Bash 3.2: no mapfile.
  local sorted=()
  local i j tmp
  sorted=("${snaps[@]}")
  for ((i = 1; i < total; i++)); do
    tmp="${sorted[i]}"
    j=$((i - 1))
    while [ "$j" -ge 0 ] && [ "${sorted[j]##*/}" \> "${tmp##*/}" ]; do
      sorted[$((j + 1))]="${sorted[j]}"
      j=$((j - 1))
    done
    sorted[$((j + 1))]="$tmp"
  done

  local remove=$((total - keep))
  local victim
  for ((i = 0; i < remove; i++)); do
    victim="${sorted[i]}"
    # Belt and braces before an rm -rf: must be a directory, must live directly
    # under BACKUP_DIR, and must still match our own stamp pattern.
    [ -n "$victim" ] && [ -d "$victim" ] || continue
    # These two re-checks are unreachable by construction — the collection loop
    # above already guarantees both — and are kept only as defence-in-depth
    # against a future refactor of that loop. Being unreachable, they are not
    # unit-testable; do not read their presence as "tested".
    [ "${victim%/*}" = "$BACKUP_DIR" ] || continue
    [[ "${victim##*/}" =~ ^[0-9]{8}-[0-9]{6}(-[0-9]+)?$ ]] || continue
    rm -rf "$victim"
    info "pruned old snapshot: ${victim##*/}"
  done
}

if [ -n "$RETAIN" ]; then
  prune_snapshots "$RETAIN"
fi
