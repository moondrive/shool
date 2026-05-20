"""
Модуль работы с базой данных (SQLite).
Хранит архив отложенных постов по каждому администратору.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "posts.db"

# ─── Инициализация ────────────────────────────────────────────────────────────

def init_db() -> None:
    """Создаёт таблицы при первом запуске. Безопасно вызывать повторно."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS archived_posts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id    INTEGER NOT NULL,
                post_text   TEXT    NOT NULL,
                topic       TEXT    NOT NULL DEFAULT '',
                created_at  TEXT    NOT NULL
                            DEFAULT (strftime('%d.%m %H:%M', 'now', 'localtime'))
            )
        """)
        conn.commit()


# ─── Запись ───────────────────────────────────────────────────────────────────

def archive_post(admin_id: int, post_text: str, topic: str = "") -> int:
    """
    Сохраняет пост в архив.

    Returns:
        id новой записи.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO archived_posts (admin_id, post_text, topic) VALUES (?, ?, ?)",
            (admin_id, post_text, topic),
        )
        conn.commit()
        return cur.lastrowid


# ─── Чтение ───────────────────────────────────────────────────────────────────

def count_archived(admin_id: int) -> int:
    """Возвращает количество постов в архиве пользователя."""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM archived_posts WHERE admin_id = ?",
            (admin_id,),
        ).fetchone()[0]


def get_archived_posts(admin_id: int, limit: int = 5, offset: int = 0) -> list:
    """
    Возвращает посты из архива (от новых к старым).

    Args:
        admin_id: Telegram ID администратора.
        limit:    Сколько записей вернуть.
        offset:   Смещение (для пагинации).

    Returns:
        Список словарей: {id, post_text, topic, created_at}.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, post_text, topic, created_at
               FROM   archived_posts
               WHERE  admin_id = ?
               ORDER  BY id DESC
               LIMIT  ? OFFSET ?""",
            (admin_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def get_post_by_id(post_id: int, admin_id: int) -> dict | None:
    """
    Получает один пост по его id (с проверкой владельца).

    Returns:
        Словарь с данными поста или None, если не найден / чужой.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM archived_posts WHERE id = ? AND admin_id = ?",
            (post_id, admin_id),
        ).fetchone()
        return dict(row) if row else None


# ─── Удаление ─────────────────────────────────────────────────────────────────

def delete_post(post_id: int, admin_id: int) -> bool:
    """
    Удаляет пост из архива.

    Returns:
        True если пост был найден и удалён, False иначе.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "DELETE FROM archived_posts WHERE id = ? AND admin_id = ?",
            (post_id, admin_id),
        )
        conn.commit()
        return cur.rowcount > 0
