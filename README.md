# Kitap Takip

Python 3.11 ve Docker gerektirir.

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pytest
python application.py
```

Docker ile çalıştırma:

```powershell
docker compose up -d --build
```

Uygulama: http://localhost:6116
