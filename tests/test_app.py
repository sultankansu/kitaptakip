from html import unescape
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


def test_all_books_view_shows_covers_from_every_shelf(client):
    conn = db.get_db()
    conn.executemany(
        "INSERT INTO books (title, page_count, status, cover) VALUES (?, 100, ?, ?)",
        [
            ("Okunacak kitap", "want", "/static/want-cover.jpg"),
            ("Okunan kitap", "reading", "/static/reading-cover.jpg"),
            ("Okunan tamamlandı", "finished", "/static/finished-cover.jpg"),
        ],
    )
    conn.commit()
    conn.close()

    response = client.get("/?tab=all")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    for title, cover in [
        ("Okunacak kitap", "want-cover.jpg"),
        ("Okunan kitap", "reading-cover.jpg"),
        ("Okunan tamamlandı", "finished-cover.jpg"),
    ]:
        assert title in page
        assert cover in page
    assert "Tüm kitaplar" in page


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


def test_book_summary_can_be_added_and_rendered(client):
    conn = db.get_db()
    cursor = conn.execute(
        "INSERT INTO books (title, page_count, status) VALUES ('Özet testi', 120, 'reading')"
    )
    book_id = cursor.lastrowid
    conn.commit()
    conn.close()

    summary = "Bir yolculuk sırasında kahraman kendini ve çevresini yeniden keşfeder."
    response = client.post(
        f"/book/{book_id}/summary",
        data={"summary": summary, "tab": "reading"},
    )
    assert response.status_code == 302
    conn = db.get_db()
    saved = conn.execute(
        "SELECT summary FROM books WHERE id = ?", (book_id,)
    ).fetchone()["summary"]
    conn.close()
    assert saved == summary

    response = client.get("/?tab=reading")
    assert summary in response.get_data(as_text=True)


def test_book_summary_rejects_more_than_4000_characters(client):
    conn = db.get_db()
    cursor = conn.execute(
        "INSERT INTO books (title, page_count, status) VALUES ('Uzun özet testi', 120, 'reading')"
    )
    book_id = cursor.lastrowid
    conn.commit()
    conn.close()

    response = client.post(
        f"/book/{book_id}/summary",
        data={"summary": "x" * 4001, "tab": "reading"},
    )
    assert response.status_code == 302
    conn = db.get_db()
    saved = conn.execute(
        "SELECT summary FROM books WHERE id = ?", (book_id,)
    ).fetchone()["summary"]
    conn.close()
    assert saved == ""


def test_turkish_characters_round_trip_through_book_fields(client):
    fields = {
        "title": "İstanbul'da Şölen",
        "author": "Işıl Özçelik",
        "publisher": "Çağdaş Yayınları",
        "page_count": "321",
        "isbn": "TR-İ-Ş-Ğ",
        "publication_year": "2024",
        "summary": "Üç öğrenci, İstanbul'da özgürlük ve düşlerini arıyor.",
        "category": "Roman",
        "status": "want",
    }
    response = client.post("/add", data=fields)
    assert response.status_code == 302

    conn = db.get_db()
    book = conn.execute(
        "SELECT title, author, publisher, isbn, summary, category FROM books"
    ).fetchone()
    conn.close()
    assert tuple(book) == (
        fields["title"],
        fields["author"],
        fields["publisher"],
        fields["isbn"],
        fields["summary"],
        fields["category"],
    )

    response = client.get("/?tab=want")
    assert response.mimetype == "text/html"
    assert response.mimetype_params["charset"] == "utf-8"
    page = unescape(response.get_data(as_text=True))
    assert fields["title"] in page
    assert fields["author"] in page
    assert fields["summary"] in page
    assert 'accept-charset="UTF-8"' in page


def test_duplicate_book_check_handles_turkish_case(client):
    client.post(
        "/add",
        data={
            "title": "IŞIK",
            "author": "Yazar",
            "page_count": "100",
            "status": "want",
            "isbn": "123",
        },
    )
    response = client.post(
        "/add",
        data={
            "title": "ışık",
            "author": "Yazar",
            "page_count": "100",
            "status": "want",
            "isbn": "123",
        },
    )
    assert response.status_code == 302
    conn = db.get_db()
    assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
    conn.close()


def test_turkish_characters_round_trip_in_review_note(client):
    conn = db.get_db()
    cursor = conn.execute(
        "INSERT INTO books (title, page_count, status) VALUES ('Not kitabı', 180, 'finished')"
    )
    book_id = cursor.lastrowid
    conn.commit()
    conn.close()

    note = "Öykü çok etkileyici; özellikle Çağrı'nın seçimi düşündürücü."
    response = client.post(
        f"/book/{book_id}/review",
        data={"rating": "5", "note": note},
    )
    assert response.status_code == 302
    conn = db.get_db()
    saved = conn.execute(
        "SELECT note FROM books WHERE id = ?", (book_id,)
    ).fetchone()["note"]
    conn.close()
    assert saved == note

    page = unescape(client.get("/?tab=finished").get_data(as_text=True))
    assert note in page
