from scraper import search_books


def test_search_parses_turkish_characters_from_utf8_bytes(monkeypatch):
    class Response:
        url = "https://www.kitapyurdu.com/search"
        content = (
            '<div class="ky-product">'
            '<a class="ky-product-title" href="/kitap/1">İstanbul\'da Şölen</a>'
            '<span class="ky-product-author"><a>Çağrı Işık</a></span>'
            '<span class="ky-product-publisher"><a>Özgür Yayınları</a></span>'
            "</div>"
        ).encode("utf-8")

        def raise_for_status(self):
            pass

    class Session:
        def __init__(self):
            self.headers = {}

        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("scraper.requests.Session", Session)
    monkeypatch.setattr("scraper.get_book_details", lambda url: None)

    result = search_books("İstanbul")
    assert result["error"] is None
    assert result["results"][0]["title"] == "İstanbul'da Şölen"
    assert result["results"][0]["author"] == "Çağrı Işık"
    assert result["results"][0]["publisher"] == "Özgür Yayınları"
