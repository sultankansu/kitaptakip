import os
import re
from urllib.parse import urljoin

import requests
import truststore
from bs4 import BeautifulSoup

truststore.inject_into_ssl()

SEARCH_URL = "https://www.kitapyurdu.com/index.php"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def search_books(query):
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        response = session.get(
            SEARCH_URL,
            params={"route": "product/search", "filter_name": query},
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException:
        return {"error": "unavailable", "results": []}

    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.select(".ky-product")
    results = []
    for card in cards:
        title_link = card.select_one("a.ky-product-title")
        author = card.select_one(".ky-product-author a")
        publisher = card.select_one(".ky-product-publisher a")
        cover_link = card.select_one("a.ky-product-cover img")
        if not title_link:
            continue
        href = urljoin(response.url, title_link.get("href", ""))
        cover = cover_link.get("data-src") or cover_link.get("src") if cover_link else None
        if cover:
            cover = urljoin(response.url, cover)
        results.append(
            {
                "title": title_link.get_text(" ", strip=True),
                "author": author.get_text(" ", strip=True) if author else "",
                "publisher": publisher.get_text(" ", strip=True) if publisher else "",
                "cover": cover,
                "url": href,
                "details": get_book_details(href),
            }
        )
    return {"error": None, "results": results}


def get_book_details(url):
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        response = session.get(url, timeout=5)
        response.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    details = {"page_count": None, "isbn": None, "publication_year": None}
    for item in soup.select(".ky-pd-attributes__item"):
        text = item.get_text(" ", strip=True)
        match = re.search(r"(\d+)", text)
        if "Sayfa Sayısı" in text and match:
            details["page_count"] = int(match.group(1))
        elif "ISBN" in text:
            isbn = re.search(r"[0-9Xx\-]+", text)
            if isbn:
                details["isbn"] = isbn.group(0)
        elif "Yayın" in text and match:
            year = int(match.group(1))
            if 1000 <= year <= 2100:
                details["publication_year"] = year
    return details


def download_cover(url, destination_dir="static/kapaklar"):
    if not url:
        return None
    os.makedirs(destination_dir, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_-]", "_", url.rsplit("/", 1)[-1].split("?")[0])
    if not name:
        name = "kitap.jpg"
    if not os.path.splitext(name)[1]:
        name += ".jpg"
    path = os.path.join(destination_dir, name)
    try:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=5
        )
        response.raise_for_status()
        with open(path, "wb") as cover_file:
            cover_file.write(response.content)
        return "/static/kapaklar/" + name
    except requests.RequestException:
        return None
