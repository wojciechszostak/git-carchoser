# Car Chooser – lokalna aplikacja FastAPI
pytho
## Uruchomienie
1. Stwórz środowisko i zainstaluj zależności:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Umieść `cleaned_aukcje.csv` w `data/`.
3. Start serwera:
   ```bash
   uvicorn app.main:app --reload
   ```
4. Wejdź na `http://127.0.0.1:8000`.
