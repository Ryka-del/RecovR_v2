# =============================================================================
# backup_recovery.py -- automatic SQLite backup + startup integrity recovery
# =============================================================================
"""
Scope and honest limitations (read this before relying on it):

- Backups live in a `backups/` folder next to recovr.db, on the SAME SD card
  as the live database. This protects against database-level corruption
  (a bad write, an interrupted transaction, a damaged file) but does NOT
  protect against the SD card itself failing physically -- that requires an
  external/offsite copy, which is out of scope here (no new storage
  requirement was authorized for this change).
- The recovery point is "the last successful periodic backup" for
  completed/historical records (therapists, patients, calibrations, and any
  session that had already been saved), and separately "the last periodic
  checkpoint update" for a session that was actively being played when
  power was lost (see database.py's session_checkpoints table / this
  module's relationship to recover_interrupted_checkpoints()). Any gameplay
  progress between the last checkpoint update and the actual power loss is
  genuinely unrecoverable -- this is disclosed, not silently glossed over.
- This is NOT full game-state resume. An interrupted session is recorded as
  a historical record (status="interrupted") with whatever score/duration
  the last checkpoint captured; it does not let the patient resume mid-game.

Three independent pieces, each usable on its own:
  * create_backup()      -- atomic, verified, periodic full-DB backup.
  * check_and_recover_startup() -- run ONCE at app startup, before any
    process opens the live database for real use.
  * BackupScheduler       -- a daemon thread that calls create_backup() on
    an interval, owned by exactly one process (the therapist process -- see
    recovr/launch_production.py) so two processes never race on the same
    backup file.
"""

import glob
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime

from database import DB_PATH

BACKUP_DIR = os.path.join(os.path.dirname(DB_PATH), "backups")
BACKUP_RETENTION = 10          # keep the 10 most recent valid backups
BACKUP_INTERVAL_SEC = 30 * 60  # 30 minutes -- bounds the SD-card write rate
                                # while keeping the worst-case recovery
                                # point (for already-completed records) to
                                # "at most the last 30 minutes"
_BACKUP_PREFIX = "recovr_backup_"
_BACKUP_SUFFIX = ".db"

_log = logging.getLogger("recovr.backup")
if not _log.handlers:
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        _handler = logging.FileHandler(
            os.path.join(BACKUP_DIR, "backup_log.txt"), encoding="utf-8")
        _handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"))
        _log.addHandler(_handler)
        _log.setLevel(logging.INFO)
    except Exception:
        # Logging must never be why a backup/recovery attempt crashes.
        _log.addHandler(logging.NullHandler())


def _verify_integrity(path):
    """True only if PRAGMA integrity_check reports exactly 'ok'. Opens its
    own short-lived read-only-in-spirit connection (closed before
    returning) so this never holds a lock on the file it's checking."""
    try:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(row) and row[0] == "ok"
        finally:
            conn.close()
    except Exception:
        return False


def _backup_path(ts):
    return os.path.join(BACKUP_DIR, f"{_BACKUP_PREFIX}{ts}{_BACKUP_SUFFIX}")


def list_backups():
    """Existing backups, newest first."""
    paths = glob.glob(os.path.join(BACKUP_DIR, f"{_BACKUP_PREFIX}*{_BACKUP_SUFFIX}"))
    return sorted(paths, reverse=True)


def prune_old_backups(retention=None):
    """Deletes backups beyond the retention count, oldest first. Only ever
    removes backups older than the kept set -- never touches the most
    recent ones, and never runs as part of a FAILED create_backup() (see
    create_backup's docstring), so a bad attempt can't cost an existing
    good backup."""
    if retention is None:
        retention = BACKUP_RETENTION   # read live, not a def-time default
    backups = list_backups()
    for path in backups[retention:]:
        try:
            os.remove(path)
            _log.info("Pruned old backup: %s", os.path.basename(path))
        except Exception as e:
            _log.warning("Failed to prune old backup %s: %s", path, e)


def create_backup(source_conn=None):
    """Creates one verified, atomic backup of the live database.

    Atomicity: the Online Backup API writes to a TEMP file first; the temp
    file is only promoted to its final name via os.replace() (atomic on
    both POSIX and Windows for a same-directory rename) AFTER its own
    integrity_check passes. If anything goes wrong at any point -- a crash
    mid-copy, a bad verify -- the temp file is removed and every
    PREVIOUSLY-existing valid backup is left completely untouched, so a
    failed attempt can never leave the backup set in a worse state than
    before it ran.

    `source_conn` lets the caller reuse its own already-open connection
    (the therapist process's long-lived one) instead of opening a second
    connection to the same live file. If omitted, a short-lived connection
    to DB_PATH is opened and closed here.

    Returns the final backup path on success, or None on failure (never
    raises -- a failed backup must not crash the caller's own work).
    """
    if not os.path.exists(DB_PATH):
        _log.warning("create_backup: no database at %s yet -- skipping", DB_PATH)
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_path = os.path.join(BACKUP_DIR, f".tmp_{ts}{_BACKUP_SUFFIX}")
    final_path = _backup_path(ts)

    owns_conn = source_conn is None
    conn = source_conn or sqlite3.connect(DB_PATH)
    dest_conn = None
    try:
        dest_conn = sqlite3.connect(tmp_path)
        conn.backup(dest_conn)   # SQLite Online Backup API -- safe to run
                                  # concurrently with normal reads/writes on
                                  # `conn`, regardless of journal mode.
        dest_conn.close()
        dest_conn = None

        if not _verify_integrity(tmp_path):
            _log.error("create_backup: verification failed for %s -- discarding", tmp_path)
            os.remove(tmp_path)
            return None

        os.replace(tmp_path, final_path)
        _log.info("Backup created: %s", os.path.basename(final_path))
        prune_old_backups()
        return final_path
    except Exception as e:
        _log.error("create_backup failed: %s", e)
        try:
            if dest_conn is not None:
                dest_conn.close()
        except Exception:
            pass
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return None
    finally:
        if owns_conn:
            conn.close()


def restore_backup(backup_path, dest_path=DB_PATH):
    """Verifies `backup_path` before touching anything, then promotes it
    to `dest_path`. The CURRENT file at dest_path (if any) is renamed aside
    (never deleted) so a corrupted database stays available for
    inspection instead of silently disappearing."""
    if not _verify_integrity(backup_path):
        _log.error("restore_backup: %s itself failed integrity_check -- refusing", backup_path)
        return False
    if os.path.exists(dest_path):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        quarantine = f"{dest_path}.corrupt_{ts}"
        try:
            os.replace(dest_path, quarantine)
            _log.info("Quarantined existing database to %s", quarantine)
        except Exception as e:
            _log.error("restore_backup: could not quarantine existing file: %s", e)
            return False
    shutil.copy2(backup_path, dest_path)
    _log.info("Restored database from %s", os.path.basename(backup_path))
    return True


def check_and_recover_startup():
    """Run ONCE per application launch, before any process opens DB_PATH
    for real use (see recovr/launch_production.py). Returns one of:
      "fresh"            -- no database file exists yet (first run)
      "ok"                -- the existing database passed integrity_check
      "recovered"         -- it failed, and a valid backup was restored
      "corrupt_no_backup" -- it failed and no valid backup exists; the
                             corrupt file is left in place (never deleted)
                             so the caller can decide how to proceed rather
                             than this module silently guessing
    """
    if not os.path.exists(DB_PATH):
        _log.info("check_and_recover_startup: no existing database -- fresh install")
        return "fresh"

    if _verify_integrity(DB_PATH):
        _log.info("check_and_recover_startup: database OK")
        return "ok"

    _log.error("check_and_recover_startup: %s FAILED integrity_check", DB_PATH)
    for candidate in list_backups():
        if _verify_integrity(candidate):
            if restore_backup(candidate, DB_PATH):
                _log.info("check_and_recover_startup: recovered using %s",
                           os.path.basename(candidate))
                return "recovered"
        else:
            _log.warning("check_and_recover_startup: backup %s is also corrupt -- skipping",
                          os.path.basename(candidate))

    _log.critical("check_and_recover_startup: no usable backup found -- "
                   "database left as-is at %s for manual inspection", DB_PATH)
    return "corrupt_no_backup"


class BackupScheduler:
    """Owned by exactly ONE process (the therapist process). Runs
    create_backup() on a plain timer from its own daemon thread so the
    60fps render loop never blocks on it. Deliberately always opens its
    OWN short-lived connection to DB_PATH from within that same thread
    (never reuses a connection handed in from another thread) -- sqlite3
    connections are not safe to share across threads by default, so this
    sidesteps that entirely rather than relying on the caller to get it
    right. Not started by more than one process at a time: two independent
    periodic backup timers racing on the same backups/ directory would be
    redundant at best, so launch_production.py's single supervisor process
    is deliberately NOT where this runs -- see its own comment."""

    def __init__(self, interval_sec=BACKUP_INTERVAL_SEC):
        import threading
        self._interval = interval_sec
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        # First backup shortly after startup (not instantly -- let the app
        # finish settling), then on a fixed interval until stopped.
        if self._stop.wait(timeout=60):
            return
        while not self._stop.is_set():
            try:
                create_backup()   # opens its own connection -- see docstring
            except Exception as e:
                _log.error("BackupScheduler: create_backup raised: %s", e)
            if self._stop.wait(timeout=self._interval):
                return
