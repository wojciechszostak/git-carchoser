from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional

from .db import init_db, seed_from_csv
from .repo import get_distinct_values, search

app = FastAPI(title="Car Chooser – lokalnie (ranking wg przebiegu)")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
async def startup_event():
    init_db()
    seed_from_csv(limit=100000)  # zmień na None, jeśli chcesz załadować cały CSV


def _to_float(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    x = x.strip()
    if x == "":
        return None
    try:
        return float(x.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _to_int(x: Optional[str]) -> Optional[int]:
    if x is None:
        return None
    x = x.strip()
    if x == "":
        return None
    try:
        return int(float(x.replace(",", ".").replace(" ", "")))
    except ValueError:
        return None


# ===== Konfiguracja wag (przebieg najważniejszy) =====
W_PRICE   = 0.25
W_MILEAGE = 0.50
W_YEAR    = 0.15
W_POWER   = 0.10
CURRENT_YEAR = 2025


def _safe_div(num, den):
    try:
        if den is None or den == 0:
            return 0.0
        return float(num) / float(den)
    except Exception:
        return 0.0


def _norm01(x):
    try:
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return 0.0


def _score_car(car, prefs):
    """
    Funkcja liczy punktację auta (0..1) na podstawie preferencji użytkownika.
    """
    price_max   = prefs.get("price_max")
    mileage_max = prefs.get("mileage_max")
    year_min    = prefs.get("year_min") or 0
    power_min   = prefs.get("power_min") or 0

    # 1) Cena – im bliżej 0 PLN w stosunku do max budżetu, tym wyższy score
    s_price = 0.0
    if car.price is not None and price_max is not None:
        s_price = _norm01(_safe_div(price_max - car.price, price_max))

    # 2) Przebieg – im bliżej 0 km w stosunku do max przebiegu, tym wyższy score
    s_mileage = 0.0
    if car.mileage is not None and mileage_max is not None:
        s_mileage = _norm01(_safe_div(mileage_max - car.mileage, mileage_max))

    # 3) Rok – premiuj nowsze auta powyżej year_min
    s_year = 0.0
    if car.year is not None and year_min:
        s_year = _norm01(_safe_div(car.year - year_min, max(1, CURRENT_YEAR - year_min)))

    # 4) Moc – premiuj powyżej minimalnej wymaganej mocy
    s_power = 0.0
    if car.power_hp is not None and power_min:
        skala = max(10.0, power_min)
        s_power = _norm01(_safe_div(car.power_hp - power_min, skala))

    # mały bonus za kompletność danych
    bonus = 0.0
    if car.link:
        bonus += 0.01
    if car.price is not None:
        bonus += 0.01

    score = (
        W_PRICE   * s_price +
        W_MILEAGE * s_mileage +
        W_YEAR    * s_year +
        W_POWER   * s_power +
        bonus
    )
    return float(score)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    fuel_types = get_distinct_values("fuel_type")
    gearboxes = get_distinct_values("gearbox")
    voivodeships = get_distinct_values("voivodeship")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "fuel_types": fuel_types,
            "gearboxes": gearboxes,
            "voivodeships": voivodeships,
        },
    )


@app.post("/results", response_class=HTMLResponse)
async def results(
    request: Request,
    fuel_type: Optional[str] = Form(None),
    gearbox: Optional[str] = Form(None),
    voivodeship: Optional[str] = Form(None),
    price_min: Optional[str] = Form(None),
    price_max: Optional[str] = Form(None),
    year_min: Optional[str] = Form(None),
    year_max: Optional[str] = Form(None),
    mileage_max: Optional[str] = Form(None),
    power_min: Optional[str] = Form(None),
):
    # konwersje
    price_min_f = _to_float(price_min)
    price_max_f = _to_float(price_max)
    year_min_i = _to_int(year_min)
    year_max_i = _to_int(year_max)
    mileage_max_f = _to_float(mileage_max)
    power_min_f = _to_float(power_min)

    # pobierz kandydatów z bazy
    candidates = search(
        fuel_type=fuel_type,
        gearbox=gearbox,
        voivodeship=voivodeship,
        price_min=price_min_f,
        price_max=price_max_f,
        year_min=year_min_i,
        year_max=year_max_i,
        mileage_max=mileage_max_f,
        power_min=power_min_f,
    )

    # preferencje użytkownika (do scoringu)
    prefs = {
        "price_max": price_max_f,
        "mileage_max": mileage_max_f,
        "year_min": year_min_i,
        "power_min": power_min_f,
    }

    # sortowanie wg punktacji
    ranked = sorted(candidates, key=lambda c: _score_car(c, prefs), reverse=True)
    top5 = ranked[:5]

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "results": ranked[:50],  # max 50 dla czytelności
            "top5": top5,
        },
    )


@app.get("/debug/stats", response_class=HTMLResponse)
async def debug_stats(request: Request):
    from .db import get_session
    from sqlmodel import select
    from .models import CarListing

    with get_session() as s:
        total = s.exec(select(CarListing)).all()
    return f"<pre>Liczba rekordów w bazie: {len(total)}</pre>"
