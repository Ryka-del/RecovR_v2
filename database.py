# =============================================================================
# database.py  —  SQLite Database Handler
# =============================================================================

import sqlite3
import os
import hashlib
import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recovr.db")

MAX_PIN_ATTEMPTS = 5
LOCK_DURATION_HOURS = 1


class Database:

    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        # Therapists — uses 'clinic' column internally (legacy name kept for DB compat)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS therapists (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name   TEXT    NOT NULL,
                username    TEXT    NOT NULL UNIQUE,
                pin_hash    TEXT    NOT NULL,
                role        TEXT    NOT NULL,
                clinic      TEXT    NOT NULL,
                icon_index  INTEGER NOT NULL DEFAULT 1,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # PIN attempt tracking & account locks
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS account_locks (
                therapist_id  INTEGER PRIMARY KEY,
                attempts      INTEGER NOT NULL DEFAULT 0,
                locked_until  DATETIME,
                FOREIGN KEY (therapist_id) REFERENCES therapists(id) ON DELETE CASCADE
            )
        """)

        # Patients
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id_str  TEXT    NOT NULL UNIQUE,
                full_name       TEXT    NOT NULL,
                age             INTEGER,
                sex             TEXT,
                dominant_hand   TEXT,
                affected_hand   TEXT,
                stroke_type     TEXT,
                date_of_stroke  TEXT,
                months_stroke   INTEGER,
                severity        TEXT,
                notes_stiffness TEXT,
                notes_pain      TEXT,
                notes_therapist TEXT,
                therapist_id    INTEGER,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (therapist_id) REFERENCES therapists(id)
            )
        """)

        # Patient sharing — tracks which therapists a patient has been shared with
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS patient_shares (
                patient_id   INTEGER NOT NULL,
                therapist_id INTEGER NOT NULL,
                shared_by    INTEGER NOT NULL,
                shared_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (patient_id, therapist_id),
                FOREIGN KEY (patient_id)   REFERENCES patients(id)   ON DELETE CASCADE,
                FOREIGN KEY (therapist_id) REFERENCES therapists(id) ON DELETE CASCADE,
                FOREIGN KEY (shared_by)    REFERENCES therapists(id) ON DELETE CASCADE
            )
        """)

        # Calibration records
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS calibrations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id      INTEGER,
                therapist_id    INTEGER,
                game_type       TEXT,
                sensor          TEXT,
                sensitivity     TEXT,
                average         REAL,
                threshold       REAL,
                threshold_pct   INTEGER,
                speed           TEXT,
                duration        TEXT,
                difficulty      TEXT,
                preset          TEXT,
                calibrated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_id)   REFERENCES patients(id),
                FOREIGN KEY (therapist_id) REFERENCES therapists(id)
            )
        """)

        # Session records
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id   INTEGER,
                therapist_id INTEGER,
                game         TEXT    NOT NULL,
                score        INTEGER NOT NULL DEFAULT 0,
                duration_sec INTEGER NOT NULL DEFAULT 0,
                difficulty   TEXT,
                played_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_id)   REFERENCES patients(id),
                FOREIGN KEY (therapist_id) REFERENCES therapists(id)
            )
        """)

        # Add game_name column if it doesn't exist yet (migration for existing DBs)
        try:
            self.conn.execute(
                "ALTER TABLE calibrations ADD COLUMN game_name TEXT DEFAULT ''")
            self.conn.commit()
        except Exception:
            pass

        self.conn.commit()

    # ── CALIBRATION RECORDS ───────────────────────────────────────────

    def save_calibration(self, patient_id, therapist_id, result, game_name=""):
        p = result.get("params", {})
        self.conn.execute("""
            INSERT INTO calibrations
              (patient_id, therapist_id, game_type, game_name, sensor, sensitivity,
               average, threshold, threshold_pct, speed, duration, difficulty, preset)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            patient_id, therapist_id,
            result.get("game_type",   ""),
            game_name,
            result.get("sensor",      ""),
            result.get("sensitivity", ""),
            result.get("average",     0.0),
            result.get("threshold",   0.0),
            p.get("threshold_pct", 0),
            p.get("speed",         ""),
            p.get("duration",      ""),
            p.get("difficulty",    ""),
            result.get("preset",      ""),
        ))
        self.conn.commit()

    def get_calibrations(self, therapist_id, patient_id=None):
        if patient_id is not None:
            # Show ALL calibrations for this patient regardless of which therapist did them
            cur = self.conn.execute("""
                SELECT c.*, p.full_name AS patient_name, t.full_name AS therapist_name
                FROM calibrations c
                LEFT JOIN patients   p ON c.patient_id   = p.id
                LEFT JOIN therapists t ON c.therapist_id = t.id
                WHERE c.patient_id = ?
                ORDER BY c.calibrated_at DESC
            """, (patient_id,))
        else:
            # Show calibrations for all patients accessible to this therapist
            cur = self.conn.execute("""
                SELECT c.*, p.full_name AS patient_name, t.full_name AS therapist_name
                FROM calibrations c
                LEFT JOIN patients   p ON c.patient_id   = p.id
                LEFT JOIN therapists t ON c.therapist_id = t.id
                WHERE c.patient_id IN (
                    SELECT id FROM patients WHERE therapist_id = ?
                    UNION
                    SELECT patient_id FROM patient_shares WHERE therapist_id = ?
                )
                ORDER BY c.calibrated_at DESC
            """, (therapist_id, therapist_id))
        return [dict(r) for r in cur.fetchall()]

    # ── SESSION RECORDS ───────────────────────────────────────────────

    def save_session(self, patient_id, therapist_id, game, score, duration_sec, difficulty):
        self.conn.execute("""
            INSERT INTO sessions (patient_id, therapist_id, game, score, duration_sec, difficulty)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (patient_id, therapist_id, game, score, duration_sec, difficulty))
        self.conn.commit()

    def get_sessions(self, therapist_id, patient_id=None):
        if patient_id is not None:
            # Return ALL sessions for this patient regardless of which therapist ran them
            cur = self.conn.execute("""
                SELECT s.id, s.played_at, s.game, s.score, s.duration_sec, s.difficulty,
                       p.full_name AS patient_name, t.full_name AS therapist_name
                FROM sessions s
                LEFT JOIN patients   p ON s.patient_id   = p.id
                LEFT JOIN therapists t ON s.therapist_id = t.id
                WHERE s.patient_id = ?
                ORDER BY s.played_at DESC
            """, (int(patient_id),))
        else:
            cur = self.conn.execute("""
                SELECT s.id, s.played_at, s.game, s.score, s.duration_sec, s.difficulty,
                       p.full_name AS patient_name, t.full_name AS therapist_name
                FROM sessions s
                LEFT JOIN patients   p ON s.patient_id   = p.id
                LEFT JOIN therapists t ON s.therapist_id = t.id
                WHERE s.therapist_id = ?
                ORDER BY s.played_at DESC
            """, (int(therapist_id),))
        return [dict(r) for r in cur.fetchall()]

    # ── THERAPIST CREATE ──────────────────────────────────────────────

    def create_therapist(self, full_name, username, pin, role, workplace, icon_index):
        """Returns True on success, False if username already taken."""
        try:
            self.conn.execute("""
                INSERT INTO therapists (full_name, username, pin_hash, role, clinic, icon_index)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (full_name, username, self._hash(pin), role, workplace, icon_index))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    # ── THERAPIST READ ────────────────────────────────────────────────

    def _row_to_therapist(self, row):
        """Converts a DB row to a dict, exposing 'clinic' also as 'workplace'."""
        d = dict(row)
        d["workplace"] = d.get("clinic", "")   # alias so UI code can use either key
        return d

    def get_all_therapists(self):
        c = self.conn.execute(
            "SELECT id, full_name, username, role, clinic, icon_index "
            "FROM therapists ORDER BY created_at ASC"
        )
        return [self._row_to_therapist(r) for r in c.fetchall()]

    def get_therapist_by_username(self, username):
        c = self.conn.execute(
            "SELECT id, full_name, username, role, clinic, icon_index "
            "FROM therapists WHERE username=?", (username,)
        )
        r = c.fetchone()
        return self._row_to_therapist(r) if r else None

    def search_therapists_by_prefix(self, prefix: str, exclude_id: int):
        """Return up to 5 therapists whose username starts with prefix, excluding self."""
        c = self.conn.execute(
            "SELECT id, full_name, username, role, clinic, icon_index "
            "FROM therapists WHERE username LIKE ? AND id != ? "
            "ORDER BY username ASC LIMIT 5",
            (prefix + "%", exclude_id)
        )
        return [self._row_to_therapist(r) for r in c.fetchall()]

    def get_therapist_by_id(self, tid):
        c = self.conn.execute(
            "SELECT id, full_name, username, role, clinic, icon_index "
            "FROM therapists WHERE id=?", (tid,)
        )
        r = c.fetchone()
        return self._row_to_therapist(r) if r else None

    # ── PIN VERIFICATION WITH LOCKOUT ────────────────────────────────

    def get_lock_info(self, therapist_id):
        """Returns (attempts, locked_until_datetime_or_None)."""
        c = self.conn.execute(
            "SELECT attempts, locked_until FROM account_locks WHERE therapist_id=?",
            (therapist_id,)
        )
        r = c.fetchone()
        if not r:
            return 0, None
        locked_until = None
        if r["locked_until"]:
            try:
                locked_until = datetime.datetime.fromisoformat(r["locked_until"])
            except Exception:
                locked_until = None
        return r["attempts"], locked_until

    def is_locked(self, therapist_id):
        """Returns (is_locked: bool, unlock_time: datetime or None)."""
        _, locked_until = self.get_lock_info(therapist_id)
        if locked_until is None:
            return False, None
        now = datetime.datetime.now()
        if now >= locked_until:
            # Lock expired — clear it
            self._clear_lock(therapist_id)
            return False, None
        return True, locked_until

    def _ensure_lock_row(self, therapist_id):
        self.conn.execute(
            "INSERT OR IGNORE INTO account_locks (therapist_id, attempts) VALUES (?, 0)",
            (therapist_id,)
        )
        self.conn.commit()

    def _clear_lock(self, therapist_id):
        self.conn.execute(
            "DELETE FROM account_locks WHERE therapist_id=?", (therapist_id,)
        )
        self.conn.commit()

    def record_failed_attempt(self, therapist_id):
        """
        Increments failed attempt counter.
        If MAX_PIN_ATTEMPTS reached, sets locked_until.
        Returns (new_attempt_count, locked_until_or_None).
        """
        self._ensure_lock_row(therapist_id)
        self.conn.execute(
            "UPDATE account_locks SET attempts = attempts + 1 WHERE therapist_id=?",
            (therapist_id,)
        )
        self.conn.commit()
        attempts, _ = self.get_lock_info(therapist_id)
        if attempts >= MAX_PIN_ATTEMPTS:
            unlock_time = datetime.datetime.now() + datetime.timedelta(hours=LOCK_DURATION_HOURS)
            self.conn.execute(
                "UPDATE account_locks SET locked_until=? WHERE therapist_id=?",
                (unlock_time.isoformat(), therapist_id)
            )
            self.conn.commit()
            return attempts, unlock_time
        return attempts, None

    def record_successful_login(self, therapist_id):
        """Clears all failed attempts on successful login."""
        self._clear_lock(therapist_id)

    def verify_pin(self, username, pin):
        """
        Verifies PIN only (no lockout logic here — call is_locked first).
        Returns True if correct, False otherwise.
        """
        c = self.conn.execute(
            "SELECT pin_hash FROM therapists WHERE username=?", (username,)
        )
        r = c.fetchone()
        return bool(r and r["pin_hash"] == self._hash(pin))

    def username_exists(self, username):
        c = self.conn.execute("SELECT 1 FROM therapists WHERE username=?", (username,))
        return c.fetchone() is not None

    # ── THERAPIST UPDATE ──────────────────────────────────────────────

    def update_therapist(self, tid, full_name, username, role, workplace, icon_index, new_pin=None):
        """Returns True on success, False if new username conflicts."""
        try:
            if new_pin:
                self.conn.execute("""
                    UPDATE therapists
                    SET full_name=?, username=?, role=?, clinic=?, icon_index=?, pin_hash=?
                    WHERE id=?
                """, (full_name, username, role, workplace, icon_index, self._hash(new_pin), tid))
            else:
                self.conn.execute("""
                    UPDATE therapists
                    SET full_name=?, username=?, role=?, clinic=?, icon_index=?
                    WHERE id=?
                """, (full_name, username, role, workplace, icon_index, tid))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    # ── THERAPIST DELETE ──────────────────────────────────────────────

    def delete_therapist(self, tid):
        self.conn.execute("DELETE FROM therapists WHERE id=?", (tid,))
        self.conn.commit()

    # ── PATIENT CRUD ──────────────────────────────────────────────────

    def get_all_patients(self, therapist_id=None):
        """
        If therapist_id is given, returns only:
          - patients owned by that therapist, AND
          - patients explicitly shared with that therapist.
        Otherwise returns every patient (admin use).
        """
        if therapist_id:
            c = self.conn.execute("""
                SELECT DISTINCT p.* FROM patients p
                LEFT JOIN patient_shares ps ON ps.patient_id = p.id
                WHERE p.therapist_id = ?
                   OR ps.therapist_id = ?
                ORDER BY p.created_at ASC
            """, (therapist_id, therapist_id))
        else:
            c = self.conn.execute("SELECT * FROM patients ORDER BY created_at ASC")
        return [dict(r) for r in c.fetchall()]

    def create_patient(self, data: dict, therapist_id: int):
        """
        data keys: full_name, age, sex, dominant_hand, affected_hand,
                   stroke_type, date_of_stroke, months_stroke, severity,
                   notes_stiffness, notes_pain, notes_therapist
        Returns the auto-generated patient_id_str (e.g. RCVR-0001).
        """
        # Auto-generate sequential patient ID
        c = self.conn.execute("SELECT COUNT(*) as cnt FROM patients")
        n = c.fetchone()["cnt"] + 1
        pid_str = f"RCVR-{n:04d}"
        try:
            self.conn.execute("""
                INSERT INTO patients
                  (patient_id_str, full_name, age, sex, dominant_hand, affected_hand,
                   stroke_type, date_of_stroke, months_stroke, severity,
                   notes_stiffness, notes_pain, notes_therapist, therapist_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                pid_str,
                data.get("full_name", ""),
                int(data.get("age", 0)) if str(data.get("age", "")).isdigit() else None,
                data.get("sex", ""),
                data.get("dominant_hand", ""),
                data.get("affected_hand", ""),
                data.get("stroke_type", ""),
                data.get("date_of_stroke", ""),
                int(data.get("months_stroke", 0)) if str(data.get("months_stroke", "")).isdigit() else None,
                data.get("severity", ""),
                data.get("notes_stiffness", ""),
                data.get("notes_pain", ""),
                data.get("notes_therapist", ""),
                therapist_id,
            ))
            self.conn.commit()
            return pid_str
        except sqlite3.IntegrityError:
            return None

    # ── PATIENT SHARING ───────────────────────────────────────────────

    def share_patient(self, patient_id: int, target_therapist_id: int, shared_by: int):
        """
        Grants target_therapist_id access to patient_id.
        Returns True on success, False if already shared or error.
        """
        try:
            self.conn.execute("""
                INSERT OR IGNORE INTO patient_shares (patient_id, therapist_id, shared_by)
                VALUES (?, ?, ?)
            """, (patient_id, target_therapist_id, shared_by))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def unshare_patient(self, patient_id: int, target_therapist_id: int):
        """Revokes a previously shared therapist's access to a patient."""
        self.conn.execute("""
            DELETE FROM patient_shares
            WHERE patient_id = ? AND therapist_id = ?
        """, (patient_id, target_therapist_id))
        self.conn.commit()

    def get_patient_owner(self, patient_id: int):
        """Returns the therapist_id of the patient's original registering therapist."""
        c = self.conn.execute(
            "SELECT therapist_id FROM patients WHERE id = ?", (patient_id,)
        )
        r = c.fetchone()
        return r["therapist_id"] if r else None

    def get_shared_therapists(self, patient_id: int):
        """
        Returns a list of therapist dicts that this patient has been shared with
        (excludes the original owner).
        """
        c = self.conn.execute("""
            SELECT t.id, t.full_name, t.username, t.role, t.clinic, t.icon_index
            FROM patient_shares ps
            JOIN therapists t ON t.id = ps.therapist_id
            WHERE ps.patient_id = ?
            ORDER BY ps.shared_at ASC
        """, (patient_id,))
        return [self._row_to_therapist(r) for r in c.fetchall()]

    def is_patient_shared_with(self, patient_id: int, therapist_id: int) -> bool:
        """Returns True if the patient has been shared with therapist_id."""
        c = self.conn.execute("""
            SELECT 1 FROM patient_shares
            WHERE patient_id = ? AND therapist_id = ?
        """, (patient_id, therapist_id))
        return c.fetchone() is not None

    def update_patient(self, patient_id: int, data: dict):
        """Update an existing patient's fields by internal row id."""
        self.conn.execute("""
            UPDATE patients SET
              full_name=?, age=?, sex=?, dominant_hand=?, affected_hand=?,
              stroke_type=?, date_of_stroke=?, months_stroke=?, severity=?,
              notes_stiffness=?, notes_pain=?, notes_therapist=?
            WHERE id=?
        """, (
            data.get("full_name", ""),
            int(data.get("age", 0)) if str(data.get("age", "")).isdigit() else None,
            data.get("sex", ""),
            data.get("dominant_hand", ""),
            data.get("affected_hand", ""),
            data.get("stroke_type", ""),
            data.get("date_of_stroke", ""),
            int(data.get("months_stroke", 0)) if str(data.get("months_stroke", "")).isdigit() else None,
            data.get("severity", ""),
            data.get("notes_stiffness", ""),
            data.get("notes_pain", ""),
            data.get("notes_therapist", ""),
            patient_id,
        ))
        self.conn.commit()

    def delete_patient(self, patient_id: int):
        """Permanently remove a patient and all their share records."""
        self.conn.execute("DELETE FROM patient_shares WHERE patient_id=?", (patient_id,))
        self.conn.execute("DELETE FROM patients WHERE id=?", (patient_id,))
        self.conn.commit()

    # ── UTIL ──────────────────────────────────────────────────────────

    def _hash(self, pin):
        return hashlib.sha256(pin.encode()).hexdigest()

    def close(self):
        self.conn.close()