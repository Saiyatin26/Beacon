"""Phase 17 — User and Project Membership Repository.

Manages persistent storage and querying of users, credentials, and tenant/project
memberships in SQLite with thread-safety and memory fallback for isolated testing.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Optional

from .models import ProjectMembership, User, UserRole
from .security import hash_password

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "beacon.sqlite3"


class AuthRepository:
    """Manages persistent storage of users, credentials, and project memberships."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DB_PATH
        # In-memory storage for test isolation and fallback
        self._memory_users: dict[str, User] = {}  # user_id -> User
        self._memory_usernames: dict[str, str] = {}  # username.lower() -> user_id
        self._memory_memberships: dict[str, list[ProjectMembership]] = {}  # user_id -> list
        self._init_db()
        self._seed_default_users()

    def _init_db(self):
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        full_name TEXT NOT NULL,
                        email TEXT NOT NULL,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        is_system_admin INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS project_memberships (
                        user_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, project_id)
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memberships_proj ON project_memberships(project_id)")
                conn.commit()
        except Exception as exc:
            logger.warning(f"Could not initialize SQLite auth tables: {exc}")

    def _seed_default_users(self):
        """Seeds initial development and test users if database is empty."""
        try:
            if self.get_user_by_username("admin"):
                return

            # 1. System Admin
            admin_user = self.create_user(
                user_id="USR-ADMIN-001",
                username="admin",
                password="BeaconAdmin2026!",
                full_name="System Administrator",
                email="admin@beacon.local",
                is_system_admin=True,
            )

            # 2. Certifier (Alice)
            alice = self.create_user(
                user_id="USR-ALICE-002",
                username="alice_certifier",
                password="AliceCert2026!",
                full_name="Alice (Certifier)",
                email="alice@retail.corp",
            )
            self.assign_user_to_project(alice.user_id, "proj_retail_pilot", UserRole.CERTIFIER)
            self.assign_user_to_project(alice.user_id, "benchmark_retail_discount_pricing", UserRole.CERTIFIER)
            self.assign_user_to_project(alice.user_id, "loan_demo", UserRole.CERTIFIER)
            self.assign_user_to_project(alice.user_id, "regression_proj_g", UserRole.CERTIFIER)

            # 3. Viewer (Bob)
            bob = self.create_user(
                user_id="USR-BOB-003",
                username="bob_viewer",
                password="BobView2026!",
                full_name="Bob (Viewer)",
                email="bob@retail.corp",
            )
            self.assign_user_to_project(bob.user_id, "proj_retail_pilot", UserRole.VIEWER)
            self.assign_user_to_project(bob.user_id, "benchmark_retail_discount_pricing", UserRole.VIEWER)

            # 4. Auditor (Carol)
            carol = self.create_user(
                user_id="USR-CAROL-004",
                username="carol_auditor",
                password="CarolAudit2026!",
                full_name="Carol (Compliance Auditor)",
                email="carol@audit.org",
            )
            self.assign_user_to_project(carol.user_id, "proj_retail_pilot", UserRole.AUDITOR)
            self.assign_user_to_project(carol.user_id, "benchmark_retail_discount_pricing", UserRole.AUDITOR)

            # 5. Project Admin (Dave)
            dave = self.create_user(
                user_id="USR-DAVE-005",
                username="dave_admin",
                password="DaveAdmin2026!",
                full_name="Dave (Project Admin)",
                email="dave@retail.corp",
            )
            self.assign_user_to_project(dave.user_id, "proj_retail_pilot", UserRole.PROJECT_ADMIN)

            # 6. External Tenant User (for multi-tenant isolation testing)
            ext = self.create_user(
                user_id="USR-EXT-006",
                username="external_user",
                password="External2026!",
                full_name="External Tenant User",
                email="external@othercorp.com",
            )
            self.assign_user_to_project(ext.user_id, "proj_other_finance", UserRole.CERTIFIER)

        except Exception as exc:
            logger.warning(f"Could not seed default auth users: {exc}")

    def create_user(
        self,
        username: str,
        password: str,
        user_id: Optional[str] = None,
        full_name: str = "",
        email: str = "",
        is_system_admin: bool = False,
        is_active: bool = True,
    ) -> User:
        """Creates a new user with a salted PBKDF2 hashed password."""
        norm_username = username.strip().lower()
        uid = user_id or f"USR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{norm_username}"
        pwd_hash = hash_password(password)

        user = User(
            user_id=uid,
            username=norm_username,
            password_hash=pwd_hash,
            full_name=full_name,
            email=email,
            is_active=is_active,
            is_system_admin=is_system_admin,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # Store in memory
        self._memory_users[uid] = user
        self._memory_usernames[norm_username] = uid

        # Store in SQLite
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO users (
                        user_id, username, password_hash, full_name, email, is_active, is_system_admin, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.user_id,
                        user.username,
                        user.password_hash,
                        user.full_name,
                        user.email,
                        1 if user.is_active else 0,
                        1 if user.is_system_admin else 0,
                        user.created_at,
                    ),
                )
                conn.commit()
        except Exception as exc:
            logger.debug(f"SQLite user write note: {exc}")

        return user

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Retrieves user by unique user_id."""
        if user_id in self._memory_users:
            return self._memory_users[user_id]

        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT user_id, username, password_hash, full_name, email, is_active, is_system_admin, created_at
                    FROM users WHERE user_id = ?
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()
                if row:
                    user = User(
                        user_id=row[0],
                        username=row[1],
                        password_hash=row[2],
                        full_name=row[3],
                        email=row[4],
                        is_active=bool(row[5]),
                        is_system_admin=bool(row[6]),
                        created_at=row[7],
                    )
                    self._memory_users[user.user_id] = user
                    self._memory_usernames[user.username] = user.user_id
                    return user
        except Exception as exc:
            logger.debug(f"SQLite get_user_by_id note: {exc}")

        return None

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Retrieves user by username (case-insensitive)."""
        norm = username.strip().lower()
        if norm in self._memory_usernames:
            uid = self._memory_usernames[norm]
            return self.get_user_by_id(uid)

        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT user_id, username, password_hash, full_name, email, is_active, is_system_admin, created_at
                    FROM users WHERE username = ?
                    """,
                    (norm,),
                )
                row = cursor.fetchone()
                if row:
                    user = User(
                        user_id=row[0],
                        username=row[1],
                        password_hash=row[2],
                        full_name=row[3],
                        email=row[4],
                        is_active=bool(row[5]),
                        is_system_admin=bool(row[6]),
                        created_at=row[7],
                    )
                    self._memory_users[user.user_id] = user
                    self._memory_usernames[user.username] = user.user_id
                    return user
        except Exception as exc:
            logger.debug(f"SQLite get_user_by_username note: {exc}")

        return None

    def assign_user_to_project(self, user_id: str, project_id: str, role: UserRole) -> ProjectMembership:
        """Assigns or updates a user's role within a project tenant."""
        membership = ProjectMembership(
            user_id=user_id,
            project_id=project_id,
            role=role,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # Update in-memory list
        m_list = self._memory_memberships.setdefault(user_id, [])
        # Replace existing project membership if present
        self._memory_memberships[user_id] = [m for m in m_list if m.project_id != project_id] + [membership]

        # Update SQLite
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO project_memberships (user_id, project_id, role, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, project_id, role.value if hasattr(role, "value") else str(role), membership.created_at),
                )
                conn.commit()
        except Exception as exc:
            logger.debug(f"SQLite membership write note: {exc}")

        return membership

    def get_user_memberships(self, user_id: str) -> list[ProjectMembership]:
        """Retrieves all project memberships for a given user."""
        if user_id in self._memory_memberships:
            return list(self._memory_memberships[user_id])

        memberships: list[ProjectMembership] = []
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT user_id, project_id, role, created_at FROM project_memberships WHERE user_id = ?",
                    (user_id,),
                )
                for row in cursor.fetchall():
                    memberships.append(
                        ProjectMembership(
                            user_id=row[0],
                            project_id=row[1],
                            role=UserRole(row[2]),
                            created_at=row[3],
                        )
                    )
            self._memory_memberships[user_id] = memberships
        except Exception as exc:
            logger.debug(f"SQLite get_user_memberships note: {exc}")

        return memberships

    def remove_user_from_project(self, user_id: str, project_id: str) -> bool:
        """Removes a user's membership from a project."""
        if user_id in self._memory_memberships:
            self._memory_memberships[user_id] = [
                m for m in self._memory_memberships[user_id] if m.project_id != project_id
            ]

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "DELETE FROM project_memberships WHERE user_id = ? AND project_id = ?",
                    (user_id, project_id),
                )
                conn.commit()
                return True
        except Exception as exc:
            logger.debug(f"SQLite remove membership note: {exc}")
            return False

    def list_users(self) -> list[User]:
        """Lists all registered users."""
        users_map = dict(self._memory_users)
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT user_id, username, password_hash, full_name, email, is_active, is_system_admin, created_at
                    FROM users
                    """
                )
                for row in cursor.fetchall():
                    uid = row[0]
                    if uid not in users_map:
                        users_map[uid] = User(
                            user_id=row[0],
                            username=row[1],
                            password_hash=row[2],
                            full_name=row[3],
                            email=row[4],
                            is_active=bool(row[5]),
                            is_system_admin=bool(row[6]),
                            created_at=row[7],
                        )
        except Exception:
            pass
        return sorted(list(users_map.values()), key=lambda u: u.username)

    def clear(self):
        """Clears memory state and re-seeds default users (used for test isolation)."""
        self._memory_users.clear()
        self._memory_usernames.clear()
        self._memory_memberships.clear()
        self._seed_default_users()


# Default singleton instance
auth_repository = AuthRepository()
