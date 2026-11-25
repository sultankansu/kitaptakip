import os
import tempfile

import pytest

import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    db.DB_PATH = str(tmp_path / "kitap.db")
    db.init_db()
    import application

    application.app.config.update(TESTING=True)
    with application.app.test_client() as test_client:
        test_client.post(
            "/login", data={"username": "test", "password": "123"}
        )
        yield test_client


def test_login_required(client):
    import application

    response = application.app.test_client().get("/")
    assert response.status_code == 302


def test_page_progress_rule(client):
    conn = db.get_db()
    conn.execute(
        "INSERT INTO books (title, page_count, status) VALUES ('Suç ve Ceza', 500, 'reading')"
    )
    conn.commit()
    book_id = conn.execute("SELECT id FROM books").fetchone()["id"]
    conn.close()

    response = client.post(
        f"/book/{book_id}/progress", data={"pages_read": "501"}
    )
    assert response.status_code == 302
    conn = db.get_db()
    assert conn.execute(
        "SELECT COUNT(*) AS count FROM reading_logs"
    ).fetchone()["count"] == 0
    conn.close()


def test_finish_estimate(client):
    conn = db.get_db()
    conn.execute(
        "INSERT INTO books (title, page_count, status) VALUES ('Test', 100, 'reading')"
    )
    book_id = conn.execute("SELECT id FROM books").fetchone()["id"]
    conn.execute(
        "INSERT INTO reading_logs (book_id, pages_read) VALUES (?, 20)",
        (book_id,),
    )
    conn.execute(
        "INSERT INTO reading_logs (book_id, pages_read) VALUES (?, 30)",
        (book_id,),
    )
    conn.execute(
        "INSERT INTO reading_logs (book_id, pages_read) VALUES (?, 50)",
        (book_id,),
    )
    conn.commit()
    conn.close()

    import application

    assert application.estimate_finish_days(book_id) == 4


def test_yearly_goal_setting(client):
    response = client.post("/settings", data={"yearly_goal": "30"})
    assert response.status_code == 200
    conn = db.get_db()
    goal = conn.execute(
        "SELECT yearly_goal FROM settings WHERE id = 1"
    ).fetchone()["yearly_goal"]
    conn.close()
    assert goal == 30


def test_book_categories_can_be_assigned_and_filtered(client):
    response = client.post(
        "/add",
        data={
            "title": "Kategori testi",
            "page_count": "250",
            "status": "want",
            "category": "Roman",
        },
    )
    assert response.status_code == 302
    conn = db.get_db()
    book = conn.execute(
        "SELECT id, category FROM books WHERE title = 'Kategori testi'"
    ).fetchone()
    assert book["category"] == "Roman"
    conn.close()

    response = client.get("/?tab=want&category=Roman")
    assert response.status_code == 200
    assert "Kategori testi" in response.get_data(as_text=True)
    assert "Tüm kategoriler" in response.get_data(as_text=True)

    response = client.post(
        f"/book/{book['id']}/category",
        data={"category": "Polisiye", "tab": "want", "category_filter": "Roman"},
    )
    assert response.status_code == 302
    conn = db.get_db()
    category = conn.execute(
        "SELECT category FROM books WHERE id = ?", (book["id"],)
    ).fetchone()["category"]
    conn.close()
    assert category == "Polisiye"
    assert "category=Roman" in response.location


def test_delete_book_removes_book_and_reading_logs(client):
    conn = db.get_db()
    cursor = conn.execute(
        "INSERT INTO books (title, page_count, status) VALUES ('Silinecek kitap', 200, 'reading')"
    )
    book_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO reading_logs (book_id, pages_read) VALUES (?, 30)",
        (book_id,),
    )
    conn.commit()
    conn.close()

    response = client.post(
        f"/book/{book_id}/delete",
        data={"tab": "reading", "category_filter": "Roman"},
    )
    assert response.status_code == 302
    assert "category=Roman" in response.location
    conn = db.get_db()
    assert conn.execute(
        "SELECT COUNT(*) FROM books WHERE id = ?", (book_id,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM reading_logs WHERE book_id = ?", (book_id,)
    ).fetchone()[0] == 0
    conn.close()
