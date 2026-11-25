import os
import unicodedata
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import db
from scraper import download_cover, get_book_details, search_books


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "kitaptakip-gelistirme")
app.config["SESSION_COOKIE_HTTPONLY"] = True

db.init_db()

DEFAULT_COVER = "/static/default-cover.svg"
CATEGORIES = (
    "Genel",
    "Roman",
    "Bilim Kurgu",
    "Polisiye",
    "Tarih",
    "Felsefe",
    "Biyografi",
    "Kişisel Gelişim",
    "Diğer",
)


def turkish_casefold(value):
    normalized = unicodedata.normalize("NFC", value)
    return normalized.translate(str.maketrans({"I": "ı", "İ": "i"})).casefold()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def page_count_for(book_id):
    conn = db.get_db()
    row = conn.execute(
        "SELECT page_count FROM books WHERE id = ?", (book_id,)
    ).fetchone()
    conn.close()
    return row["page_count"] if row else None


def latest_pages(book_id):
    conn = db.get_db()
    row = conn.execute(
        "SELECT pages_read FROM reading_logs WHERE book_id = ? "
        "ORDER BY logged_at DESC, id DESC LIMIT 1",
        (book_id,),
    ).fetchone()
    conn.close()
    return row["pages_read"] if row else 0


def estimate_finish_days(book_id):
    conn = db.get_db()
    book = conn.execute("SELECT page_count FROM books WHERE id = ?", (book_id,)).fetchone()
    rows = conn.execute(
        "SELECT pages_read, logged_at FROM reading_logs "
        "WHERE book_id = ? ORDER BY logged_at DESC, id DESC LIMIT 7",
        (book_id,),
    ).fetchall()
    conn.close()
    if not book or not book["page_count"] or not rows:
        return None
    remaining = book["page_count"] - rows[0]["pages_read"]
    if remaining <= 0:
        return 0
    pages = [row["pages_read"] - 0 for row in rows]
    if len(pages) < 2:
        return None
    increments = [a - b for a, b in zip(pages, pages[1:])]
    increments = [value for value in increments if value > 0]
    if not increments:
        return None
    daily = sum(increments) / len(increments)
    return max(1, int((remaining + daily - 1) // daily)) if daily else None


def calculate_reading_streak():
    conn = db.get_db()
    rows = conn.execute(
        "SELECT DISTINCT substr(logged_at, 1, 10) AS day "
        "FROM reading_logs ORDER BY day DESC"
    ).fetchall()
    conn.close()
    if not rows:
        return 0
    days = {row["day"] for row in rows}
    today = datetime.now().date()
    streak = 0
    while today.strftime("%Y-%m-%d") in days:
        streak += 1
        today = today.fromordinal(today.toordinal() - 1)
    return streak


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == "test" and request.form.get("password") == "123":
            session["logged_in"] = True
            return redirect(url_for("library"))
        flash("Kullanıcı adı veya şifre hatalı.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def library():
    tab = request.args.get("tab", "reading")
    if tab not in ("all", "want", "reading", "finished"):
        tab = "reading"
    selected_category = request.args.get("category", "")
    if selected_category not in CATEGORIES:
        selected_category = ""
    conn = db.get_db()
    query = "SELECT * FROM books"
    conditions = []
    params = []
    if tab != "all":
        conditions.append("status = ?")
        params.append(tab)
    if selected_category:
        conditions.append("category = ?")
        params.append(selected_category)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    books = conn.execute(query + " ORDER BY created_at DESC", params).fetchall()
    progress = {}
    estimates = {}
    reading_logs = {}
    for book in books:
        latest = latest_pages(book["id"])
        progress[book["id"]] = (
            round(latest / book["page_count"] * 100)
            if book["page_count"] else 0
        )
        estimates[book["id"]] = estimate_finish_days(book["id"])
        reading_logs[book["id"]] = conn.execute(
            "SELECT id, pages_read, logged_at FROM reading_logs "
            "WHERE book_id = ? ORDER BY logged_at DESC, id DESC",
            (book["id"],),
        ).fetchall()
    conn.close()
    return render_template(
        "library.html",
        books=books,
        tab=tab,
        progress=progress,
        estimates=estimates,
        reading_logs=reading_logs,
        categories=CATEGORIES,
        selected_category=selected_category,
        default_cover=DEFAULT_COVER,
    )


@app.route("/search")
@login_required
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return render_template(
            "search.html",
            query="",
            results=[],
            error=None,
            categories=CATEGORIES,
            default_cover=DEFAULT_COVER,
        )
    result = search_books(query)
    if result["error"]:
        flash("Şu an kitap aranamıyor, elle ekleyebilirsin.", "warning")
    elif not result["results"]:
        flash("Kitap bulunamadı, elle ekleyebilirsin.", "warning")
    return render_template(
        "search.html",
        query=query,
        results=result["results"],
        error=result["error"],
        categories=CATEGORIES,
        default_cover=DEFAULT_COVER,
    )


@app.route("/add", methods=["POST"])
@login_required
def add_book():
    url = request.form.get("url", "").strip()
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    publisher = request.form.get("publisher", "").strip()
    isbn = request.form.get("isbn", "").strip()
    category = request.form.get("category", "Genel")
    if category not in CATEGORIES:
        category = "Genel"
    status = request.form.get("status", "want")
    if status not in ("want", "reading", "finished"):
        status = "want"
    try:
        page_count = int(request.form.get("page_count") or 0)
    except ValueError:
        page_count = 0
    try:
        publication_year = int(request.form.get("publication_year") or 0) or None
    except ValueError:
        publication_year = None
    if not title:
        flash("Kitap adı zorunludur.", "danger")
        return redirect(url_for("search"))
    if page_count <= 0:
        flash("Sayfa sayısı sıfırdan büyük olmalıdır.", "danger")
        return redirect(url_for("search"))
    summary = request.form.get("summary", "").strip()
    if len(summary) > 4000:
        flash("Kitap özeti 4000 karakterden uzun olamaz.", "danger")
        return redirect(url_for("search"))

    conn = db.get_db()
    existing = next(
        (
            book
            for book in conn.execute("SELECT id, title, isbn FROM books").fetchall()
            if turkish_casefold(book["title"]) == turkish_casefold(title)
            and (book["isbn"] or "") == isbn
        ),
        None,
    )
    if existing:
        conn.close()
        flash("Bu kitap zaten ekli.", "warning")
        return redirect(url_for("library"))

    cover = request.form.get("cover", "").strip()
    local_cover = download_cover(cover) if cover else None
    conn.execute(
        "INSERT INTO books "
        "(title, author, publisher, cover, url, page_count, isbn, publication_year, status, category, summary, finished_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            title,
            author,
            publisher,
            local_cover or DEFAULT_COVER,
            url,
            page_count,
            isbn or None,
            publication_year,
            status,
            category,
            summary,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "finished" else None,
        ),
    )
    conn.commit()
    conn.close()
    flash("Kitap eklendi.", "success")
    return redirect(url_for("library", tab=status))


@app.route("/book/<int:book_id>/summary", methods=["POST"])
@login_required
def update_summary(book_id):
    summary = request.form.get("summary", "").strip()
    if len(summary) > 4000:
        flash("Kitap özeti 4000 karakterden uzun olamaz.", "danger")
        return redirect(url_for("library"))
    tab = request.form.get("tab", "reading")
    if tab not in ("all", "want", "reading", "finished"):
        tab = "reading"
    selected_category = request.form.get("category_filter", "")
    if selected_category not in CATEGORIES:
        selected_category = ""
    conn = db.get_db()
    result = conn.execute(
        "UPDATE books SET summary = ? WHERE id = ?", (summary, book_id)
    )
    conn.commit()
    conn.close()
    if result.rowcount:
        flash("Kitap özeti kaydedildi.", "success")
    else:
        flash("Kitap bulunamadı.", "warning")
    return redirect(
        url_for("library", tab=tab, category=selected_category or None)
    )


@app.route("/book/<int:book_id>/category", methods=["POST"])
@login_required
def change_category(book_id):
    category = request.form.get("category", "")
    if category not in CATEGORIES:
        flash("Geçersiz kategori.", "danger")
        return redirect(url_for("library"))
    conn = db.get_db()
    conn.execute(
        "UPDATE books SET category = ? WHERE id = ?", (category, book_id)
    )
    conn.commit()
    conn.close()
    tab = request.form.get("tab", "reading")
    if tab not in ("all", "want", "reading", "finished"):
        tab = "reading"
    selected_category = request.form.get("category_filter", "")
    if selected_category not in CATEGORIES:
        selected_category = ""
    return redirect(
        url_for("library", tab=tab, category=selected_category or None)
    )


@app.route("/book/<int:book_id>/delete", methods=["POST"])
@login_required
def delete_book(book_id):
    tab = request.form.get("tab", "reading")
    if tab not in ("all", "want", "reading", "finished"):
        tab = "reading"
    selected_category = request.form.get("category_filter", "")
    if selected_category not in CATEGORIES:
        selected_category = ""

    conn = db.get_db()
    conn.execute("DELETE FROM reading_logs WHERE book_id = ?", (book_id,))
    result = conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()
    if result.rowcount:
        flash("Kitap ve okuma kayıtları silindi.", "success")
    else:
        flash("Kitap bulunamadı.", "warning")
    return redirect(
        url_for("library", tab=tab, category=selected_category or None)
    )


@app.route("/book/<int:book_id>/status", methods=["POST"])
@login_required
def change_status(book_id):
    status = request.form.get("status")
    if status not in ("want", "reading", "finished"):
        flash("Geçersiz raf.", "danger")
        return redirect(url_for("library"))
    conn = db.get_db()
    if status == "finished":
        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE books SET status = ?, finished_at = ? WHERE id = ?",
            (status, finished_at, book_id),
        )
    else:
        conn.execute(
            "UPDATE books SET status = ?, finished_at = NULL WHERE id = ?",
            (status, book_id),
        )
    conn.commit()
    conn.close()
    return_tab = request.form.get("return_tab", "")
    if return_tab not in ("all", "want", "reading", "finished"):
        return_tab = status
    return redirect(url_for("library", tab=return_tab))


@app.route("/book/<int:book_id>/progress", methods=["POST"])
@login_required
def add_progress(book_id):
    try:
        pages = int(request.form.get("pages_read", ""))
    except (TypeError, ValueError):
        flash("Geçerli bir sayfa değeri gir.", "danger")
        return redirect(url_for("library", tab="reading"))
    conn = db.get_db()
    book = conn.execute(
        "SELECT page_count FROM books WHERE id = ?", (book_id,)
    ).fetchone()
    previous = conn.execute(
        "SELECT pages_read FROM reading_logs WHERE book_id = ? "
        "ORDER BY logged_at DESC, id DESC LIMIT 1",
        (book_id,),
    ).fetchone()
    previous_pages = previous["pages_read"] if previous else 0
    if not book or pages < previous_pages or pages > book["page_count"] or pages < 0:
        conn.close()
        flash("Sayfa değeri önceki kayıttan küçük veya toplam sayfadan büyük olamaz.", "danger")
        return redirect(url_for("library", tab="reading"))
    conn.execute(
        "INSERT INTO reading_logs (book_id, pages_read) VALUES (?, ?)",
        (book_id, pages),
    )
    if pages == book["page_count"]:
        conn.execute(
            "UPDATE books SET status = 'finished', finished_at = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), book_id),
        )
    conn.commit()
    conn.close()
    return redirect(url_for("library", tab="reading"))


@app.route("/book/<int:book_id>/log/<int:log_id>/delete", methods=["POST"])
@login_required
def delete_log(book_id, log_id):
    conn = db.get_db()
    conn.execute(
        "DELETE FROM reading_logs WHERE id = ? AND book_id = ?", (log_id, book_id)
    )
    latest = conn.execute(
        "SELECT pages_read FROM reading_logs WHERE book_id = ? "
        "ORDER BY logged_at DESC, id DESC LIMIT 1",
        (book_id,),
    ).fetchone()
    if latest:
        conn.execute(
            "UPDATE books SET status = 'reading', finished_at = NULL WHERE id = ?",
            (book_id,),
        )
    else:
        conn.execute(
            "UPDATE books SET status = 'reading', finished_at = NULL WHERE id = ?",
            (book_id,),
        )
    conn.commit()
    conn.close()
    return redirect(url_for("library", tab="reading"))


@app.route("/book/<int:book_id>/review", methods=["POST"])
@login_required
def review_book(book_id):
    try:
        rating = int(request.form.get("rating") or 0)
    except ValueError:
        rating = 0
    if rating < 1 or rating > 5:
        rating = None
    note = request.form.get("note", "").strip()
    conn = db.get_db()
    conn.execute(
        "UPDATE books SET rating = ?, note = ? WHERE id = ?", (rating, note, book_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("library", tab="finished"))


@app.route("/stats")
@login_required
def stats():
    year = datetime.now().year
    conn = db.get_db()
    goal_row = conn.execute("SELECT yearly_goal FROM settings WHERE id = 1").fetchone()
    goal = goal_row["yearly_goal"] if goal_row else 24
    completed = conn.execute(
        "SELECT COUNT(*) AS count FROM books "
        "WHERE status = 'finished' AND substr(finished_at, 1, 4) = ?",
        (str(year),),
    ).fetchone()["count"]
    monthly = conn.execute(
        "SELECT substr(logged_at, 1, 7) AS month, "
        "MAX(pages_read) AS pages FROM reading_logs "
        "WHERE substr(logged_at, 1, 4) = ? "
        "GROUP BY substr(logged_at, 1, 7) ORDER BY month",
        (str(year),),
    ).fetchall()
    conn.close()
    difference = completed - goal
    if difference >= 0:
        status_text = f"Hedefini {difference} kitap geçtin"
    else:
        status_text = f"Hedefin {abs(difference)} kitap gerisindesin"
    return render_template(
        "stats.html",
        goal=goal,
        completed=completed,
        status_text=status_text,
        monthly=monthly,
        streak=calculate_reading_streak(),
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    conn = db.get_db()
    if request.method == "POST":
        try:
            goal = int(request.form.get("yearly_goal", "24"))
        except ValueError:
            goal = 24
        if goal < 1:
            goal = 24
        conn.execute(
            "UPDATE settings SET yearly_goal = ? WHERE id = 1", (goal,)
        )
        conn.commit()
        flash("Ayarlar kaydedildi.", "success")
    row = conn.execute("SELECT yearly_goal FROM settings WHERE id = 1").fetchone()
    conn.close()
    return render_template("settings.html", goal=row["yearly_goal"])


@app.context_processor
def inject_defaults():
    return {"default_cover": DEFAULT_COVER}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010, debug=True)
