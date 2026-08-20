#!/usr/bin/env bash
#
# backup.sh — snapshot the CouchPotato SQLite database + settings.
#
# Run this before a promotion that could touch the database: a schema change or
# migration, or any release carrying changes to the persistence layer
# (`couchpotato/core/db/`) or to a write path that runs unattended, such as the
# library scanner or the renamer. It is NOT run nightly and NOT run before every
# deploy: a docs-only or packaging-only promotion cannot damage data, and a
# backup ritual applied to every release is one people stop taking seriously.
#
# "UI-only" is NOT on that safe list, and saying so was a defect in the first
# draft of this policy. This project's UI calls destructive APIs directly:
# `couchpotato/ui/templates/partials/movie_detail.html` fires `media.delete`,
# and both `wizard.html` and the settings partial fire `settings.save`. A UI
# change that sends the wrong id or the wrong value destroys library records or
# corrupts configuration just as thoroughly as a migration would. Classify a UI
# change by whether it can reach a write API, not by the fact that it is UI.
#
# The reason the trigger is "could touch the database" rather than "changes the
# schema" is that this project has already lost data the other way. The
# `_query_index` defects fixed in 2026-02 corrupted records during an ordinary
# library scan, with no migration and no schema change involved. Ask what the
# release can WRITE, not what it declares.
#
# Be honest about what that example does NOT establish, because it cuts both
# ways. That corruption happened during NORMAL RUNNING, not during a promotion,
# so a promotion-gated snapshot would not have caught it either: a scan that
# corrupts data three days after a deploy falls between backups under this
# policy, where a nightly would have caught it. That residual risk is accepted
# deliberately, on the owner's decision, and it is the thread to pull if this
# policy ever needs revisiting. It is written down rather than left implicit so
# the next reader inherits the decision and not just the rule.
#
# When it does apply, it is not optional: a promotion is only reversible if the
# database was captured first, because `:latest` has already moved by deploy
# time, so "re-pull the old image" does not recover data.
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
# RUN THIS ON THE HOST, NOT INSIDE THE CONTAINER. `COPY . ${APP_DIR}` ships this
# file into the image, but the runtime image is Alpine with NEITHER bash NOR
# sqlite3 (verified), so `docker exec couchpotato scripts/backup.sh` fails with
# "not found" — which is a bad thing to discover mid-incident. Use the host copy:
#   ssh <host> && cd /var/lib/plexmediaserver/CouchPotato && ./scripts/backup.sh
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

Run before a promotion that could touch the database: a schema change or
migration, anything under couchpotato/core/db/, an unattended write path such as
the scanner or renamer, or a UI change that can reach a destructive API (the UI
calls media.delete and settings.save directly). NOT nightly, NOT before every
deploy. Uses sqlite3 `.backup` (or Python's sqlite3 backup API) so the copy is
safe against a live database.

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
# Picking the wrong one is invisible: the script warns and exits 0, so every run
# reports success while never capturing settings. That is why the documented
# verification checks config.ini is PRESENT in the snapshot, not just that the
# database opens.
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
  # Zero-padded so the suffix sorts chronologically: with a bare `-N`, `-10`
  # sorts before `-2` and the freshest snapshot can look like the oldest, which
  # would let `--retain 1` delete the backup this run just took.
  suffix=2
  candidate="$(printf '%s-%02d' "$DEST" "$suffix")"
  while [ -e "$candidate" ]; do
    suffix=$((suffix + 1))
    candidate="$(printf '%s-%02d' "$DEST" "$suffix")"
  done
  warn "$DEST already exists — writing $candidate instead so the existing snapshot is not touched"
  DEST="$candidate"
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
# RESIDUAL LIMITATION (narrowed, not gone). The `-NN` collision suffix is
# zero-padded so same-second snapshots sort chronologically. A BACKUP_DIR that
# still holds an UNPADDED `-N` directory from an older version of this script can
# still mis-sort: with `<stamp>` and a legacy `<stamp>-2` present, `--retain 1`
# keeps `-2` and prunes the fresh `<stamp>-02` (reproduced). Unreachable under
# the documented usage — `--retain N` on a pre-promotion run
# would need 15+ snapshots inside a single second. If you ever hit it, delete or
# rename the legacy unpadded directories once and it cannot recur.
#
# Implementation note — this deliberately does NOT pipe paths into
# `head | while read`. Two real defects came from that:
#   1. `read` splits on newlines, so a newline anywhere in BACKUP_DIR truncated
#      each path and `rm -rf` was handed a DIFFERENT, unrelated directory
#      outside BACKUP_DIR (reproduced), while pruning nothing.
#   2. `set -o pipefail` + `head` closing the pipe early made the whole script
#      exit 141 (SIGPIPE) on a *successful* backup once the snapshot list
#      exceeded the pipe buffer (~1050 snapshots at the default path length), so
#      the run reported failure for a good backup.
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
