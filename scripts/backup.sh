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
RETAIN=""

die() { printf 'backup.sh: %s\n' "$1" >&2; exit 1; }
info() { printf 'backup.sh: %s\n' "$1"; }
warn() { printf 'backup.sh: WARNING: %s\n' "$1" >&2; }

usage() {
  sed -n '3,29p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --retain)
      [ $# -ge 2 ] || die "--retain needs a value"
      RETAIN="$2"
      shift 2
      ;;
    --retain=*)
      RETAIN="${1#*=}"
      shift
      ;;
    -h|--help) usage ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

if [ -n "$RETAIN" ]; then
  case "$RETAIN" in
    ''|*[!0-9]*) die "--retain must be a positive integer, got '$RETAIN'" ;;
  esac
  # Guard against `--retain 0` being read as "keep nothing", which would delete
  # the snapshot this run just took.
  [ "$RETAIN" -ge 1 ] || die "--retain must be >= 1, got '$RETAIN' (refusing to delete every snapshot)"
fi

DB_SRC="$CP_DATA_DIR/database_v2/couchpotato.db"
SETTINGS_SRC="$CP_DATA_DIR/config.ini"

[ -f "$DB_SRC" ] || die "database not found: $DB_SRC (is CP_DATA_DIR correct?)"

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/$STAMP"

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
elif warn "sqlite3 unavailable or failed — falling back to the Python sqlite3 backup API" \
     && backup_with_python; then
  info "database snapshot written with Python sqlite3.backup()"
else
  # Don't leave a half-written snapshot that looks like a good backup.
  rm -rf "$DEST"
  die "could not back up $DB_SRC — neither sqlite3 nor Python was usable. NO BACKUP WAS TAKEN."
fi

# ── Settings ────────────────────────────────────────────────────────────────
# Missing settings is odd but must not cost you the database snapshot.
if [ -f "$SETTINGS_SRC" ]; then
  cp "$SETTINGS_SRC" "$DEST/config.ini"
else
  warn "config.ini not found at $SETTINGS_SRC — snapshot contains the database only"
fi

info "snapshot complete: $DEST"

# ── Retention ───────────────────────────────────────────────────────────────
# Only ever deletes directories directly under BACKUP_DIR whose names are
# exactly our own YYYYMMDD-HHMMSS stamp. Unrelated files and directories
# (and anything outside BACKUP_DIR, e.g. config.bak/) are never candidates.
prune_snapshots() {
  local keep="$1"
  local snaps=()
  local entry base

  for entry in "$BACKUP_DIR"/*; do
    [ -d "$entry" ] || continue
    base="$(basename "$entry")"
    if [[ "$base" =~ ^[0-9]{8}-[0-9]{6}$ ]]; then
      snaps+=("$entry")
    fi
  done

  local total=${#snaps[@]}
  [ "$total" -gt "$keep" ] || return 0

  # Names sort chronologically, so the oldest are first.
  local sorted
  sorted="$(printf '%s\n' "${snaps[@]}" | sort)"

  local remove=$((total - keep))
  local victim
  printf '%s\n' "$sorted" | head -n "$remove" | while IFS= read -r victim; do
    [ -n "$victim" ] || continue
    rm -rf "$victim"
    info "pruned old snapshot: $(basename "$victim")"
  done
}

if [ -n "$RETAIN" ]; then
  prune_snapshots "$RETAIN"
fi
