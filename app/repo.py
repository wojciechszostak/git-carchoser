# app/repo.py
from typing import Iterable, Optional, List
from sqlmodel import select
from .models import CarListing
from .db import get_session


def get_distinct_values(column: str, limit: int = 200) -> List[str]:
    """
    Zwraca posortowaną listę unikalnych wartości dla wskazanej kolumny modelu CarListing.
    Uwaga: `column` musi być nazwą atrybutu w CarListing (np. "fuel_type", "gearbox", "voivodeship").
    """
    col = getattr(CarListing, column)
    with get_session() as s:
        values = s.exec(
            select(col).where(col.is_not(None)).distinct()
        ).all()
    vals = [v for v in values if v is not None]
    vals.sort()
    return vals[:limit]


def search(
    *,
    fuel_type: Optional[str] = None,
    gearbox: Optional[str] = None,
    voivodeship: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    mileage_max: Optional[float] = None,
    power_min: Optional[float] = None,
    limit: int = 200,
    order_by_price_asc: bool = False,
) -> Iterable[CarListing]:
    """
    Filtruje oferty wg przekazanych kryteriów.
    KLUCZOWE: mileage_max filtruje po kolumnie liczbowej `mileage` (upewnij się, że w db.py konwertujesz przebieg na liczbę).

    Parametry:
      - limit: maksymalna liczba rekordów (dla bezpieczeństwa UI)
      - order_by_price_asc: True -> sortuj rosnąco po cenie, False -> brak sortowania (kolejność z bazy)
    """
    with get_session() as s:
        q = select(CarListing)

        # --- filtry kategoryczne ---
        if fuel_type:
            q = q.where(CarListing.fuel_type == fuel_type)
        if gearbox:
            q = q.where(CarListing.gearbox == gearbox)
        if voivodeship:
            q = q.where(CarListing.voivodeship == voivodeship)

        # --- filtry liczbowe ---
        if price_min is not None:
            q = q.where(CarListing.price >= price_min)
        if price_max is not None:
            q = q.where(CarListing.price <= price_max)

        if year_min is not None:
            q = q.where(CarListing.year >= year_min)
        if year_max is not None:
            q = q.where(CarListing.year <= year_max)

        # ⬇ kluczowy filtr – maksymalny przebieg
        if mileage_max is not None:
            q = q.where(CarListing.mileage <= mileage_max)

        if power_min is not None:
            q = q.where(CarListing.power_hp >= power_min)

        # --- sortowanie / limit ---
        if order_by_price_asc:
            q = q.order_by(CarListing.price.asc())

        q = q.limit(limit)

        return s.exec(q).all()
