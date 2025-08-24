# Patch: wersja bez ML

Ten pakiet nadpisuje `app/main.py` tak, by projekt nie miał żadnych zależności od modułów ML/heurystyki.

## Co zrobić
1. Rozpakuj archiwum do katalogu projektu i **nadpisz** plik `app/main.py`.
2. Usuń z projektu katalogi `ml/` oraz `models/` (jeśli istnieją).
3. (Opcjonalnie) zaktualizuj `requirements.txt` do wersji z tego patcha — jest bez LightGBM/sklearn/joblib.
4. Uruchom aplikację:
   ```powershell
   .\.venv\Scripts\activate
   python -m uvicorn app.main:app --reload
   ```

**Uwaga:** widok TOP5 pokazuje po prostu pierwsze 5 wyników po filtrach (brak ML i brak heurystyki).
