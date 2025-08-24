from pathlib import Path
import pandas as pd
from sqlmodel import SQLModel, Session, create_engine
from .models import CarListing
from sqlalchemy import text

DB_URL = "sqlite:///./carlistings.db"
engine = create_engine(DB_URL, echo=False)

DATA_CSV = Path(__file__).resolve().parents[1] / "data" / "cleaned_aukcje.csv"

def init_db():
    SQLModel.metadata.create_all(engine)

def _to_number(series):
    # usuń wszystko poza znakami cyfr, minusem, kropką i przecinkiem, potem zamień , na .
    s = series.astype(str).str.replace(r"[^0-9\-,\.]", "", regex=True).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")

def seed_from_csv(limit: int | None = None):
    if not DATA_CSV.exists():
        raise FileNotFoundError(f"Nie znaleziono pliku: {DATA_CSV}")

    print(f"[seed] Wczytuję CSV: {DATA_CSV}")
    df = pd.read_csv(DATA_CSV)

    rename_map = {
        "Title": "title",
        "Link": "link",
        "Price": "price",
        "Mileage": "mileage",
        "Mileage[KM]": "mileage_km",
        "Year": "year",
        "power[HP]": "power_hp",
        "capacity[cm3]": "capacity_cm3",
        "Fuel Type": "fuel_type",
        "Gearbox": "gearbox",
        "City": "city",
        "Voivodeship": "voivodeship",
        "other_info": "other_info",
    }
    df = df.rename(columns=rename_map)

    # Konwersje liczbowe (bezpieczne)
    if "price" in df: df["price"] = _to_number(df["price"])
    if "mileage" in df: df["mileage"] = _to_number(df["mileage"])
    if "mileage_km" in df: df["mileage_km"] = _to_number(df["mileage_km"])
    if "power_hp" in df: df["power_hp"] = _to_number(df["power_hp"])
    if "capacity_cm3" in df: df["capacity_cm3"] = _to_number(df["capacity_cm3"])
    if "year" in df: df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

    if limit:
        df = df.head(limit)

    rows = df.to_dict(orient="records")

    with Session(engine) as session:
        session.exec(text("DELETE FROM carlisting"))
        session.commit()

        added = 0
        for r in rows:
            session.add(CarListing(**r))
            added += 1
            if added % 10000 == 0:
                session.commit()
                print(f"[seed] Zaimportowano: {added}")

        session.commit()
        print(f"[seed] GOTOWE. Zaimportowano łącznie: {added} rekordów.")

def get_session():
    return Session(engine)
