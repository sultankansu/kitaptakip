import os
import sqlite3


DB_PATH = os.environ.get("KITAPTAKIP_DB", os.path.join("data", "kitap.db"))


def get_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            yearly_goal INTEGER NOT NULL DEFAULT 24
        );
        INSERT OR IGNORE INTO settings (id, yearly_goal) VALUES (1, 24);

        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT,
            publisher TEXT,
            cover TEXT,
            url TEXT,
            page_count INTEGER,
            isbn TEXT,
            publication_year INTEGER,
            status TEXT NOT NULL CHECK (status IN ('want', 'reading', 'finished')),
            category TEXT NOT NULL DEFAULT 'Genel',
            rating INTEGER CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5)),
            note TEXT,
            finished_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reading_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            pages_read INTEGER NOT NULL,
            logged_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
        );
        """
    )
    book_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(books)").fetchall()
    }
    if "category" not in book_columns:
        conn.execute(
            "ALTER TABLE books ADD COLUMN category TEXT NOT NULL DEFAULT 'Genel'"
        )
    conn.commit()
    conn.close()
