"""
Database — Работа с SQLite базой данных
Оптимизации:
 - Persistent connection (одно соединение на весь процесс)
 - WAL journal mode + PRAGMA cache_size для конкурентных запросов
 - SQL индексы на все часто запрашиваемые поля
 - Whitelist-валидация в update_member (защита от SQL-инъекции)
 - datetime.now(UTC) вместо устаревшего utcnow()
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

DB_PATH = "rosguard.db"

# Разрешённые поля для update_member (whitelist против SQL-инъекции)
_MEMBER_ALLOWED_FIELDS = frozenset({
    "game_name", "rank_id", "status", "notes",
    "reminder_sent", "position_prefix",
    "joined_academy", "joined_faction", "added_by",
    "dossier_thread_id", "dossier_message_id",
    "case_number", "static_id", "military_id",
})

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Singleton-like database wrapper с персистентным соединением."""

    def __init__(self):
        self.db_path = DB_PATH
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()  # защита от параллельных write-операций

    async def init(self):
        """Инициализация: открываем соединение, настраиваем PRAGMA, создаём таблицы."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row  # устанавливаем один раз

        # Performance PRAGMAs
        await self._conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA cache_size=10000;
            PRAGMA synchronous=NORMAL;
            PRAGMA temp_store=MEMORY;
            PRAGMA mmap_size=268435456;
        """)

        # Создание таблиц
        await self._conn.executescript("""
            -- Участники фракции
            CREATE TABLE IF NOT EXISTS members (
                discord_id    TEXT PRIMARY KEY,
                game_name     TEXT NOT NULL,
                rank_id       INTEGER DEFAULT 1,
                status        TEXT DEFAULT 'cadet',
                joined_academy DATETIME,
                joined_faction DATETIME,
                added_by      TEXT,
                notes         TEXT,
                reminder_sent INTEGER DEFAULT 0,
                position_prefix TEXT DEFAULT '',
                dossier_thread_id TEXT,
                dossier_message_id TEXT,
                case_number   INTEGER,
                static_id     TEXT,
                military_id   TEXT
            );

            -- Заявки на вступление
            CREATE TABLE IF NOT EXISTS applications (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id    TEXT NOT NULL,
                game_name     TEXT NOT NULL,
                age           TEXT,
                reason        TEXT,
                experience    TEXT,
                static_id     TEXT,
                military_id   TEXT,
                app_type      TEXT DEFAULT 'interview',
                status        TEXT DEFAULT 'pending',
                reviewed_by   TEXT,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                message_id    TEXT,
                channel_id    TEXT
            );

            -- Тесты
            CREATE TABLE IF NOT EXISTS tests (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                description   TEXT,
                created_by    TEXT,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                pass_score    INTEGER DEFAULT 70,
                is_active     INTEGER DEFAULT 1,
                required_all  INTEGER DEFAULT 0
            );

            -- Вопросы тестов
            CREATE TABLE IF NOT EXISTS test_questions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id       INTEGER NOT NULL,
                question      TEXT NOT NULL,
                option_a      TEXT NOT NULL,
                option_b      TEXT NOT NULL,
                option_c      TEXT NOT NULL,
                option_d      TEXT NOT NULL,
                correct       TEXT NOT NULL,
                FOREIGN KEY (test_id) REFERENCES tests(id)
            );

            -- Попытки прохождения тестов
            CREATE TABLE IF NOT EXISTS test_attempts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id     TEXT NOT NULL,
                test_id       INTEGER NOT NULL,
                attempt_num   INTEGER NOT NULL DEFAULT 1,
                score         INTEGER,
                passed        INTEGER DEFAULT 0,
                started_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at  DATETIME,
                answers       TEXT
            );

            -- Назначенные тесты курсантам
            CREATE TABLE IF NOT EXISTS cadet_tests (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id     TEXT NOT NULL,
                test_id       INTEGER NOT NULL,
                assigned_by   TEXT NOT NULL,
                assigned_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- Практические задания
            CREATE TABLE IF NOT EXISTS practical_tasks (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id     TEXT NOT NULL,
                title         TEXT NOT NULL,
                description   TEXT,
                assigned_by   TEXT NOT NULL,
                assigned_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed     INTEGER DEFAULT 0,
                completed_at  DATETIME
            );

            -- Премии
            CREATE TABLE IF NOT EXISTS bonuses (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id     TEXT NOT NULL,
                amount        INTEGER NOT NULL,
                reason        TEXT NOT NULL,
                issued_by     TEXT NOT NULL,
                issued_at     DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- Взыскания
            CREATE TABLE IF NOT EXISTS reprimands (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id     TEXT NOT NULL,
                type          TEXT NOT NULL,
                reason        TEXT NOT NULL,
                issued_by     TEXT NOT NULL,
                issued_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                active        INTEGER DEFAULT 1
            );

            -- Отчёты о работе
            CREATE TABLE IF NOT EXISTS work_reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id     TEXT NOT NULL,
                content       TEXT NOT NULL,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                reviewed_by   TEXT,
                status        TEXT DEFAULT 'pending'
            );

            -- История повышений
            CREATE TABLE IF NOT EXISTS promotions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id     TEXT NOT NULL,
                old_rank_id   INTEGER NOT NULL,
                new_rank_id   INTEGER NOT NULL,
                promoted_by   TEXT NOT NULL,
                promoted_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                reason        TEXT
            );

            -- Рапорты
            CREATE TABLE IF NOT EXISTS reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                author_id     TEXT NOT NULL,
                target_id     TEXT,
                type          TEXT NOT NULL,
                content       TEXT NOT NULL,
                status        TEXT DEFAULT 'pending',
                reviewed_by   TEXT,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                message_id    TEXT
            );

            -- Логи бота
            CREATE TABLE IF NOT EXISTS bot_logs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type    TEXT NOT NULL,
                actor_id      TEXT,
                target_id     TEXT,
                details       TEXT,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- Ходатайства о снятии взысканий (УСБ)
            CREATE TABLE IF NOT EXISTS appeals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id     TEXT NOT NULL,
                reprimand_url TEXT,
                article       TEXT,
                reason        TEXT,
                proof         TEXT,
                status        TEXT DEFAULT 'pending',
                reviewed_by   TEXT,
                review_comment TEXT,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                message_id    TEXT
            );

        """)
        await self._conn.commit()

        # Безопасные миграции колонок (выполняются до создания индексов)
        migrations = [
            ("members", "position_prefix", "TEXT DEFAULT ''"),
            ("members", "dossier_thread_id", "TEXT"),
            ("members", "dossier_message_id", "TEXT"),
            ("members", "case_number", "INTEGER"),
            ("members", "static_id", "TEXT"),
            ("members", "military_id", "TEXT"),
            ("applications", "static_id", "TEXT"),
            ("applications", "military_id", "TEXT"),
            ("applications", "app_type", "TEXT DEFAULT 'interview'"),
            ("applications", "experience", "TEXT"),
            ("applications", "channel_id", "TEXT"),
        ]
        for table, col, coltype in migrations:
            try:
                await self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
                await self._conn.commit()
            except Exception:
                pass  # Колонка уже существует

        # Индексы
        await self._conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_members_status
                ON members(status);
            CREATE INDEX IF NOT EXISTS idx_members_case_number
                ON members(case_number);
            CREATE INDEX IF NOT EXISTS idx_members_static_id
                ON members(static_id);
            CREATE INDEX IF NOT EXISTS idx_applications_discord_status
                ON applications(discord_id, status);
            CREATE INDEX IF NOT EXISTS idx_test_attempts_member_test
                ON test_attempts(member_id, test_id);
            CREATE INDEX IF NOT EXISTS idx_cadet_tests_member
                ON cadet_tests(member_id);
            CREATE INDEX IF NOT EXISTS idx_practical_tasks_member
                ON practical_tasks(member_id);
            CREATE INDEX IF NOT EXISTS idx_bonuses_member
                ON bonuses(member_id);
            CREATE INDEX IF NOT EXISTS idx_reprimands_member
                ON reprimands(member_id);
            CREATE INDEX IF NOT EXISTS idx_work_reports_member
                ON work_reports(member_id);
            CREATE INDEX IF NOT EXISTS idx_promotions_member
                ON promotions(member_id);
            CREATE INDEX IF NOT EXISTS idx_reports_target
                ON reports(target_id, status);
        """)
        await self._conn.commit()

        print("✅ База данных инициализирована!")

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ──────────────── MEMBERS ────────────────

    async def add_member(self, discord_id: str, game_name: str, added_by: str) -> None:
        now = _now()
        await self._conn.execute(
            """INSERT OR REPLACE INTO members
               (discord_id, game_name, rank_id, status, joined_academy, joined_faction, added_by)
               VALUES (?, ?, 1, 'cadet', ?, ?, ?)""",
            (discord_id, game_name, now, now, added_by),
        )
        await self._conn.commit()

    async def get_member(self, discord_id: str) -> Optional[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM members WHERE discord_id = ?", (discord_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_member_by_case_number(self, case_number: int) -> Optional[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM members WHERE case_number = ?", (case_number,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_member_by_static_id(self, static_id: str) -> Optional[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM members WHERE static_id = ? OR static_id LIKE ?",
            (static_id, f"%{static_id}%")
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_next_case_number(self) -> int:
        cur = await self._conn.execute(
            "SELECT COALESCE(MAX(case_number), 0) + 1 AS next_num FROM members"
        )
        row = await cur.fetchone()
        return int(row["next_num"]) if row and row["next_num"] else 1

    async def get_all_members(self, status: str = None) -> List[Dict]:
        if status:
            cur = await self._conn.execute(
                "SELECT * FROM members WHERE status = ? ORDER BY rank_id DESC", (status,)
            )
        else:
            cur = await self._conn.execute(
                "SELECT * FROM members WHERE status != 'fired' ORDER BY rank_id DESC"
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_cadets(self) -> List[Dict]:
        return await self.get_all_members("cadet")

    async def update_member(self, discord_id: str, **kwargs) -> None:
        if not kwargs:
            return
        # Whitelist-валидация имён полей (защита от SQL-инъекции)
        invalid = set(kwargs) - _MEMBER_ALLOWED_FIELDS
        if invalid:
            raise ValueError(f"update_member: недопустимые поля: {invalid}")
        fields = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [discord_id]
        async with self._lock:
            await self._conn.execute(
                f"UPDATE members SET {fields} WHERE discord_id = ?", values
            )
            await self._conn.commit()

    async def set_member_status(self, discord_id: str, status: str, rank_id: int = None) -> None:
        updates = {"status": status}
        if rank_id is not None:
            updates["rank_id"] = rank_id
        await self.update_member(discord_id, **updates)

    async def delete_member(self, discord_id: str) -> None:
        async with self._lock:
            await self._conn.execute(
                "DELETE FROM members WHERE discord_id = ?", (discord_id,)
            )
            await self._conn.commit()

    # ──────────────── APPLICATIONS ────────────────

    async def add_application(self, discord_id: str, game_name: str,
                               age: str, reason: str, experience: str = "",
                               extra: dict = None) -> int:
        extra = extra or {}
        static_id   = extra.get("static_id", "")
        military_id = extra.get("military_id", "")
        app_type    = extra.get("app_type", "interview")
        async with self._lock:
            cur = await self._conn.execute(
                """INSERT INTO applications
                   (discord_id, game_name, age, reason, experience, static_id, military_id, app_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (discord_id, game_name, age, reason, experience,
                 static_id, military_id, app_type),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_application(self, app_id: int) -> Optional[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_pending_application(self, discord_id: str) -> Optional[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM applications WHERE discord_id = ? AND status = 'pending'",
            (discord_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def update_application(self, app_id: int, status: str, reviewed_by: str,
                                  message_id: str = None) -> None:
        async with self._lock:
            await self._conn.execute(
                "UPDATE applications SET status=?, reviewed_by=?, message_id=? WHERE id=?",
                (status, reviewed_by, message_id, app_id),
            )
            await self._conn.commit()

    async def set_application_message(self, app_id: int, message_id: str, channel_id: str) -> None:
        async with self._lock:
            await self._conn.execute(
                "UPDATE applications SET message_id=?, channel_id=? WHERE id=?",
                (message_id, channel_id, app_id),
            )
            await self._conn.commit()

    # ──────────────── TESTS ────────────────

    async def create_test(self, name: str, description: str, created_by: str,
                           pass_score: int = 70, required_all: bool = False) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                """INSERT INTO tests (name, description, created_by, pass_score, required_all)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, description, created_by, pass_score, int(required_all)),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def add_question(self, test_id: int, question: str, option_a: str,
                            option_b: str, option_c: str, option_d: str, correct: str) -> None:
        async with self._lock:
            await self._conn.execute(
                """INSERT INTO test_questions
                   (test_id, question, option_a, option_b, option_c, option_d, correct)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (test_id, question, option_a, option_b, option_c, option_d, correct.lower()),
            )
            await self._conn.commit()

    async def get_test(self, test_id: int) -> Optional[Dict]:
        cur = await self._conn.execute("SELECT * FROM tests WHERE id = ?", (test_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_all_tests(self) -> List[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM tests WHERE is_active = 1 ORDER BY id"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_test_questions(self, test_id: int) -> List[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM test_questions WHERE test_id = ? ORDER BY id", (test_id,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_test_attempts(self, member_id: str, test_id: int) -> List[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM test_attempts WHERE member_id = ? AND test_id = ? ORDER BY attempt_num",
            (member_id, test_id),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count_test_attempts(self, member_id: str, test_id: int) -> int:
        cur = await self._conn.execute(
            "SELECT COUNT(*) FROM test_attempts WHERE member_id = ? AND test_id = ?",
            (member_id, test_id),
        )
        row = await cur.fetchone()
        return row[0] if row else 0

    async def has_passed_test(self, member_id: str, test_id: int) -> bool:
        cur = await self._conn.execute(
            "SELECT COUNT(*) FROM test_attempts WHERE member_id=? AND test_id=? AND passed=1",
            (member_id, test_id),
        )
        row = await cur.fetchone()
        return (row[0] or 0) > 0

    async def has_passed_tests_bulk(self, member_id: str, test_ids: List[int]) -> Dict[int, bool]:
        """Батч-проверка прохождения нескольких тестов — один запрос вместо N."""
        if not test_ids:
            return {}
        placeholders = ",".join("?" * len(test_ids))
        cur = await self._conn.execute(
            f"SELECT test_id FROM test_attempts WHERE member_id=? AND test_id IN ({placeholders}) AND passed=1",
            (member_id, *test_ids),
        )
        passed_ids = {row[0] for row in await cur.fetchall()}
        return {tid: tid in passed_ids for tid in test_ids}

    async def record_test_attempt(self, member_id: str, test_id: int, score: int,
                                   passed: bool, answers: list) -> None:
        # Считаем attempt_num и вставляем в одном соединении (без N+1)
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT COUNT(*) FROM test_attempts WHERE member_id=? AND test_id=?",
                (member_id, test_id),
            )
            row = await cur.fetchone()
            attempt_num = (row[0] if row else 0) + 1
            now = _now()
            await self._conn.execute(
                """INSERT INTO test_attempts
                   (member_id, test_id, attempt_num, score, passed, completed_at, answers)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (member_id, test_id, attempt_num, score, int(passed), now, json.dumps(answers)),
            )
            await self._conn.commit()

    async def assign_test_to_cadet(self, member_id: str, test_id: int, assigned_by: str) -> None:
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT id FROM cadet_tests WHERE member_id=? AND test_id=?",
                (member_id, test_id)
            )
            if await cur.fetchone():
                return
            await self._conn.execute(
                "INSERT INTO cadet_tests (member_id, test_id, assigned_by) VALUES (?, ?, ?)",
                (member_id, test_id, assigned_by),
            )
            await self._conn.commit()

    async def delete_test_attempts(self, member_id: str, test_id: int) -> None:
        """Сброс попыток — добавлен метод (ранее вызывался raw SQL в academy.py)."""
        async with self._lock:
            await self._conn.execute(
                "DELETE FROM test_attempts WHERE member_id=? AND test_id=?",
                (member_id, test_id),
            )
            await self._conn.commit()

    async def get_cadet_tests(self, member_id: str) -> List[Dict]:
        cur = await self._conn.execute(
            """SELECT ct.*, t.name, t.pass_score, t.description
               FROM cadet_tests ct
               JOIN tests t ON ct.test_id = t.id
               WHERE ct.member_id = ?""",
            (member_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ──────────────── PRACTICAL TASKS ────────────────

    async def add_practical_task(self, member_id: str, title: str, description: str,
                                  assigned_by: str) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                """INSERT INTO practical_tasks (member_id, title, description, assigned_by)
                   VALUES (?, ?, ?, ?)""",
                (member_id, title, description, assigned_by),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_practical_tasks(self, member_id: str) -> List[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM practical_tasks WHERE member_id = ? ORDER BY assigned_at",
            (member_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def complete_practical_task(self, task_id: int, confirmed_by: str) -> bool:
        now = _now()
        async with self._lock:
            cur = await self._conn.execute(
                "UPDATE practical_tasks SET completed=1, completed_at=?, confirmed_by=? WHERE id=?",
                (now, confirmed_by, task_id),
            )
            await self._conn.commit()
            return cur.rowcount > 0

    async def get_task(self, task_id: int) -> Optional[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM practical_tasks WHERE id=?", (task_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    # ──────────────── REPORTS ────────────────

    async def add_report(self, type_: str, author_id: str, target_id: str,
                          reason: str, new_rank_id: int = None) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                """INSERT INTO reports (type, author_id, target_id, reason, new_rank_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (type_, author_id, target_id, reason, new_rank_id),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_report(self, report_id: int) -> Optional[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM reports WHERE id=?", (report_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def update_report(self, report_id: int, status: str, reviewed_by: str,
                             message_id: str = None) -> None:
        now = _now()
        async with self._lock:
            await self._conn.execute(
                """UPDATE reports SET status=?, reviewed_by=?, reviewed_at=?, message_id=?
                   WHERE id=?""",
                (status, reviewed_by, now, message_id, report_id),
            )
            await self._conn.commit()

    async def set_report_message(self, report_id: int, message_id: str) -> None:
        async with self._lock:
            await self._conn.execute(
                "UPDATE reports SET message_id=? WHERE id=?", (message_id, report_id)
            )
            await self._conn.commit()

    # ──────────────── PROMOTIONS ────────────────

    async def add_promotion(self, member_id: str, from_rank: int, to_rank: int,
                             approved_by: str, report_id: int = None) -> None:
        async with self._lock:
            await self._conn.execute(
                """INSERT INTO promotions (member_id, from_rank, to_rank, approved_by, report_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (member_id, from_rank, to_rank, approved_by, report_id),
            )
            await self._conn.commit()

    async def get_member_promotions(self, member_id: str) -> List[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM promotions WHERE member_id=? ORDER BY date", (member_id,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ──────────────── BONUSES ────────────────

    async def add_bonus(self, member_id: str, reason: str, given_by: str) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                "INSERT INTO bonuses (member_id, reason, given_by) VALUES (?, ?, ?)",
                (member_id, reason, given_by),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_member_bonuses(self, member_id: str) -> List[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM bonuses WHERE member_id=? ORDER BY date DESC", (member_id,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ──────────────── WORK REPORTS ────────────────

    async def add_work_report(self, member_id: str, content: str) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                "INSERT INTO work_reports (member_id, content) VALUES (?, ?)",
                (member_id, content),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_work_reports(self, member_id: str, limit: int = 10) -> List[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM work_reports WHERE member_id=? ORDER BY created_at DESC LIMIT ?",
            (member_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count_work_reports(self, member_id: str) -> int:
        cur = await self._conn.execute(
            "SELECT COUNT(*) FROM work_reports WHERE member_id=?", (member_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else 0

    # ──────────────── REPRIMANDS ────────────────

    async def add_reprimand(self, member_id: str, reason: str, given_by: str,
                             type_: str = "warning") -> int:
        async with self._lock:
            cur = await self._conn.execute(
                "INSERT INTO reprimands (member_id, reason, given_by, type) VALUES (?, ?, ?, ?)",
                (member_id, reason, given_by, type_),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_member_reprimands(self, member_id: str) -> List[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM reprimands WHERE member_id=? ORDER BY date DESC", (member_id,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def remove_reprimand(self, reprimand_id: int) -> bool:
        async with self._lock:
            cur = await self._conn.execute(
                "DELETE FROM reprimands WHERE id=?", (reprimand_id,)
            )
            await self._conn.commit()
            return cur.rowcount > 0

    # ──────────────── STATS ────────────────

    async def get_stats(self) -> Dict[str, int]:
        """Все статистики одним запросом вместо 6 отдельных (оптимизация admin_stats)."""
        cur = await self._conn.execute("""
            SELECT
                SUM(CASE WHEN status='active' THEN 1 ELSE 0 END)     AS active,
                SUM(CASE WHEN status='cadet'  THEN 1 ELSE 0 END)     AS cadet,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END)     AS failed,
                SUM(CASE WHEN status='fired'  THEN 1 ELSE 0 END)     AS fired,
                COUNT(*)                                               AS total
            FROM members
        """)
        row = await cur.fetchone()
        return dict(row) if row else {}

    async def get_top_bonuses(self, limit: int = 10) -> List[Dict]:
        cur = await self._conn.execute(
            """SELECT m.discord_id, m.game_name, m.rank_id, COUNT(b.id) AS bonus_count
               FROM members m
               LEFT JOIN bonuses b ON m.discord_id = b.member_id
               WHERE m.status = 'active'
               GROUP BY m.discord_id
               ORDER BY bonus_count DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_top_reports(self, limit: int = 10) -> List[Dict]:
        cur = await self._conn.execute(
            """SELECT m.discord_id, m.game_name, m.rank_id, COUNT(wr.id) AS report_count
               FROM members m
               LEFT JOIN work_reports wr ON m.discord_id = wr.member_id
               WHERE m.status = 'active'
               GROUP BY m.discord_id
               ORDER BY report_count DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ──────────────── APPEALS (ХОДАТАЙСТВА) ────────────────

    async def add_appeal(self, member_id: str, reprimand_url: str, article: str,
                         reason: str, proof: str) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                """INSERT INTO appeals (member_id, reprimand_url, article, reason, proof)
                   VALUES (?, ?, ?, ?, ?)""",
                (member_id, reprimand_url, article, reason, proof),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def get_appeal(self, appeal_id: int) -> Optional[Dict]:
        cur = await self._conn.execute(
            "SELECT * FROM appeals WHERE id=?", (appeal_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def update_appeal(self, appeal_id: int, status: str, reviewed_by: str,
                            review_comment: Optional[str] = None):
        async with self._lock:
            await self._conn.execute(
                "UPDATE appeals SET status=?, reviewed_by=?, review_comment=? WHERE id=?",
                (status, reviewed_by, review_comment, appeal_id),
            )
            await self._conn.commit()

    async def set_appeal_message(self, appeal_id: int, message_id: str):
        async with self._lock:
            await self._conn.execute(
                "UPDATE appeals SET message_id=? WHERE id=?",
                (message_id, appeal_id),
            )
            await self._conn.commit()

    async def remove_latest_reprimand(self, member_id: str) -> bool:
        """Удаляет последнее активное взыскание сотрудника"""
        async with self._lock:
            cur = await self._conn.execute(
                """DELETE FROM reprimands WHERE id = (
                    SELECT id FROM reprimands WHERE member_id=? ORDER BY id DESC LIMIT 1
                )""",
                (member_id,),
            )
            await self._conn.commit()
            return cur.rowcount > 0
