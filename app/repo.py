from typing import Iterable, Optional
from sqlmodel import select
from .models import CarListing
from .db import get_session

def get_distinct_values(column: str, limit: int = 200) -> list[str]:
    col = getattr(CarListing, column)
    with get_session() as s:
        q = s.exec(select(col).where(col.is_not(None)).distinct()).all()
    vals = [v for v in q if v is not None]
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
) -> Iterable[CarListing]:
    with get_session() as s:
        q = select(CarListing)
        if fuel_type:
            q = q.where(CarListing.fuel_type == fuel_type)
        if gearbox:
            q = q.where(CarListing.gearbox == gearbox)
        if voivodeship:
            q = q.where(CarListing.voivodeship == voivodeship)
        if price_min is not None:
            q = q.where(CarListing.price >= price_min)
        if price_max is not None:
            q = q.where(CarListing.price <= price_max)
        if year_min is not None:
            q = q.where(CarListing.year >= year_min)
        if year_max is not None:
            q = q.where(CarListing.year <= year_max)
        if mileage_max is not None:
            q = q.where(CarListing.mileage <= mileage_max)
        if power_min is not None:
            q = q.where(CarListing.power_hp >= power_min)

        q = q.limit(200)
        return s.exec(q).all()
