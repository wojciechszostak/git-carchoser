from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional, Iterable, List, Dict, Any

from .db import init_db, seed_from_csv
from .repo import get_distinct_values, search

app = FastAPI(title="Car Chooser – wagi silne + deduplikacja + dynamiczna normalizacja")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

CURRENT_YEAR = 2025

# Silny wpływ wag i dopasowań (na stałe)
INTENSITY = 4
ALPHA = 1 + 0.5 * INTENSITY  # 3.0  -> wzmacnia wagi
TAU   = 1 + 0.5 * INTENSITY  # 3.0  -> wyostrza dopasowanie


@app.on_event("startup")
async def startup_event():
    init_db()
    seed_from_csv(limit=None)  # zmień na None dla pełnego importu


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


def _to_weight_small(x: Optional[str]) -> float:
    """Waga 0..10 (mniejsza skala)."""
    try:
        val = float((x or "").replace(",", ".").strip())
        return max(0.0, min(10.0, val))
    except Exception:
        return 0.0


def _norm01(x: float) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return 0.0


def _apply_intensity_fixed(weights: Dict[str, float]) -> Dict[str, float]:
    """
    Silnie wzmacnia względny wpływ wag:
      w' = (w^ALPHA) / sum(w^ALPHA),  gdzie ALPHA = 3.0
    """
    s = sum(weights.values()) or 1.0
    w = {k: v / s for k, v in weights.items()}
    powered = {k: (v ** ALPHA) for k, v in w.items()}
    z = sum(powered.values()) or 1.0
    return {k: powered[k] / z for k in powered}


# ---------- NOWOŚĆ: dynamiczna normalizacja po zbiorze kandydatów ----------

def _prep_scalers(candidates: Iterable) -> Dict[str, Dict[str, float]]:
    """
    Oblicza min/max dla cech w aktualnym zbiorze kandydatów.
    Dzięki temu wagi działają mocno nawet bez limitów użytkownika.
    """
    vals = {"price": [], "mileage": [], "year": [], "power_hp": []}
    for c in candidates:
        if c.price is not None:    vals["price"].append(float(c.price))
        if c.mileage is not None:  vals["mileage"].append(float(c.mileage))
        if c.year is not None:     vals["year"].append(int(c.year))
        if c.power_hp is not None: vals["power_hp"].append(float(c.power_hp))

    def mm(vs: List[float]):
        if not vs:
            return {"min": None, "max": None, "rng": None}
        mn, mx = min(vs), max(vs)
        rng = (mx - mn) if (mx is not None and mn is not None) else None
        if rng is not None and rng <= 0:
            rng = None
        return {"min": mn, "max": mx, "rng": rng}

    return {k: mm(v) for k, v in vals.items()}


def _minmax_score(value: Optional[float], cal: Dict[str, float], reverse: bool) -> float:
    """
    Min–max w obrębie kandydatów.
    reverse=True  -> niższa wartość lepsza (cena, przebieg)
    reverse=False -> wyższa wartość lepsza (rok, moc)
    W przypadku braku zróżnicowania (rng=None) zwraca 0.5 (neutralnie).
    """
    if value is None or cal["rng"] is None:
        return 0.5
    v = float(value)
    mn, mx, rng = cal["min"], cal["max"], cal["rng"]
    if reverse:
        # Niski przebieg / niska cena -> bliżej 1
        return _norm01((mx - v) / rng)
    else:
        # Wyższy rok / większa moc -> bliżej 1
        return _norm01((v - mn) / rng)


def _dedup_listings(candidates: Iterable):
    """
    Usuwa duplikaty:
    1) po linku (case-insensitive, bez trailing slash),
    2) gdy brak linku – po (title_norm, int(price), int(year), int(mileage)).
    """
    seen = set()
    out = []
    for c in candidates:
        if c.link:
            key = str(c.link).strip().rstrip("/").lower()
        else:
            title_norm = (c.title or "").strip().lower()
            price_i = int(c.price) if c.price is not None else None
            year_i = int(c.year) if c.year is not None else None
            mileage_i = int(c.mileage) if c.mileage is not None else None
            key = ("NO_LINK", title_norm, price_i, year_i, mileage_i)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _score_car(car, weights_strong: Dict[str, float], scalers: Dict[str, Dict[str, float]]) -> float:
    """
    Punktacja 0..1 (wyżej = lepiej), liczone per-zapytanie:
      - najpierw min–max po aktualnych kandydatach,
      - potem wyostrzenie składowych do potęgi TAU,
      - na końcu wagi wzmocnione (ALPHA).
    """
    s_price   = _minmax_score(car.price,   scalers["price"],   reverse=True)   # niższa cena lepsza
    s_mileage = _minmax_score(car.mileage, scalers["mileage"], reverse=True)   # niższy przebieg lepszy
    s_year    = _minmax_score(car.year,    scalers["year"],    reverse=False)  # nowszy lepszy
    s_power   = _minmax_score(car.power_hp,scalers["power_hp"],reverse=False)  # mocniejszy lepszy

    # wyostrzenie dopasowania (TAU = 3.0)
    s_price   = s_price   ** TAU
    s_mileage = s_mileage ** TAU
    s_year    = s_year    ** TAU
    s_power   = s_power   ** TAU

    # drobne premie za kompletność oferty
    bonus = 0.0
    if car.link:               bonus += 0.01
    if car.price is not None:  bonus += 0.01

    score = (
        weights_strong["price"]   * s_price +
        weights_strong["mileage"] * s_mileage +
        weights_strong["year"]    * s_year +
        weights_strong["power"]   * s_power +
        bonus
    )
    return float(score)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    fuel_types = get_distinct_values("fuel_type")
    gearboxes = get_distinct_values("gearbox")
    voivodeships = get_distinct_values("voivodeship")
    # domyślne wagi 0..10 (mniejsze suwaki)
    defaults = {"w_price": 3, "w_mileage": 7, "w_year": 2, "w_power": 1}
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "fuel_types": fuel_types,
            "gearboxes": gearboxes,
            "voivodeships": voivodeships,
            **defaults,
        },
    )


@app.post("/results", response_class=HTMLResponse)
async def results(
    request: Request,
    # filtry
    fuel_type: Optional[str] = Form(None),
    gearbox: Optional[str] = Form(None),
    voivodeship: Optional[str] = Form(None),
    price_min: Optional[str] = Form(None),
    price_max: Optional[str] = Form(None),
    year_min: Optional[str] = Form(None),
    year_max: Optional[str] = Form(None),
    mileage_max: Optional[str] = Form(None),
    power_min: Optional[str] = Form(None),
    # wagi 0..10
    w_price: Optional[str] = Form("3"),
    w_mileage: Optional[str] = Form("7"),
    w_year: Optional[str] = Form("2"),
    w_power: Optional[str] = Form("1"),
):
    # konwersje filtrów
    price_min_f = _to_float(price_min)
    price_max_f = _to_float(price_max)
    year_min_i = _to_int(year_min)
    year_max_i = _to_int(year_max)
    mileage_max_f = _to_float(mileage_max)
    power_min_f = _to_float(power_min)

    # pobranie kandydatów z bazy + deduplikacja
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
    candidates = _dedup_listings(candidates)

    # wagi 0..10 -> normalizacja -> silne wzmocnienie
    w_price_v   = _to_weight_small(w_price)
    w_mileage_v = _to_weight_small(w_mileage)
    w_year_v    = _to_weight_small(w_year)
    w_power_v   = _to_weight_small(w_power)
    w_sum = w_price_v + w_mileage_v + w_year_v + w_power_v
    if w_sum <= 0:
        w_price_v, w_mileage_v, w_year_v, w_power_v = 3.0, 7.0, 2.0, 1.0
        w_sum = 13.0
    weights = {
        "price":   w_price_v / w_sum,
        "mileage": w_mileage_v / w_sum,
        "year":    w_year_v / w_sum,
        "power":   w_power_v / w_sum,
    }
    weights_strong = _apply_intensity_fixed(weights)

    # skalery min–max po aktualnym zbiorze
    scalers = _prep_scalers(candidates)

    # liczymy wynik i stosujemy sortowanie drugorzędne dla remisów
    scored = []
    for c in candidates:
        s = _score_car(c, weights_strong, scalers)
        # tie-break: najpierw wyższy score, potem mniejszy przebieg, potem niższa cena, na końcu nowszy rocznik
        scored.append((s, c))

    # sortowanie: malejąco po score, rosnąco po przebiegu, rosnąco po cenie, malejąco po roku
    def sort_key(t):
        s, c = t
        return (-s,
                float(c.mileage) if c.mileage is not None else float("inf"),
                float(c.price) if c.price is not None else float("inf"),
                -(int(c.year) if c.year is not None else -10**9))

    scored.sort(key=sort_key)
    ranked = [c for _, c in scored]

    top5 = ranked[:5]
    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "results": ranked[:50],
            "top5": top5,
            "weights": weights_strong,
            "w_raw": {"price": w_price_v, "mileage": w_mileage_v, "year": w_year_v, "power": w_power_v},
        },
    )
