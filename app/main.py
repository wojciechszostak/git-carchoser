from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional, List, Dict, Any
import json

from .db import init_db, seed_from_csv
from .repo import get_distinct_values, search

app = FastAPI(title="Asystent Samochodowy – Znajdź idealne auto")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

CURRENT_YEAR = 2025


@app.on_event("startup")
async def startup_event():
    init_db()
    seed_from_csv(limit=100000)


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


def _dedup_listings(candidates):
    """Usuwa duplikaty na podstawie znormalizowanego linku.
    Ogłoszenia bez linku zostają (bez dedupu), by uniknąć błędnych zlewań."""
    seen_links = set()
    out = []
    for c in candidates:
        lk = (str(c.link).strip().rstrip("/").lower()) if getattr(c, "link", None) else None
        if lk:
            if lk in seen_links:
                continue
            seen_links.add(lk)
        out.append(c)
    return out


# ---------- Prosty rule-based Asystent ----------

class CarAssistant:
    """Prosty asystent rozmowy doboru auta (bez modeli AI)"""

    def __init__(self):
        self.conversation_states: Dict[str, Dict[str, Any]] = {}

    def start_conversation(self, session_id: str) -> Dict[str, Any]:
        self.conversation_states[session_id] = {
            "step": "usage",
            "preferences": {},
            "context": {}
        }
        return {
            "message": (
                "Cześć! Jestem Twoim asystentem samochodowym. "
                "Pomogę Ci znaleźć auto, zadając kilka prostych pytań.\n\n"
                "Do czego głównie będzie Ci służyć samochód?"
            ),
            "options": [
                "Codzienne dojazdy do pracy",
                "Wyjazdy rodzinne i weekendowe",
                "Jazda miejska i parkowanie",
                "Długie trasy autostradowe",
                "Jeszcze nie wiem"
            ],
            "step": "usage"
        }

    def process_response(self, session_id: str, response: str, option_selected: Optional[str] = None) -> Dict[str, Any]:
        if session_id not in self.conversation_states:
            return self.start_conversation(session_id)

        state = self.conversation_states[session_id]
        user_input = (option_selected or response or "").strip()

        if state["step"] == "usage":
            return self._process_usage(session_id, user_input)
        elif state["step"] == "budget":
            return self._process_budget(session_id, user_input)
        elif state["step"] == "size":
            return self._process_size(session_id, user_input)
        elif state["step"] == "fuel":
            return self._process_fuel(session_id, user_input)
        elif state["step"] == "age":
            return self._process_age(session_id, user_input)
        elif state["step"] == "final_preferences":
            return self._process_final(session_id, user_input)
        elif state["step"] == "ready_to_search":
            # pozwól wywołać wyszukiwanie komendą „szukaj”
            return self._process_final(session_id, user_input)

        return {"message": "Przepraszam, coś poszło nie tak. Zacznijmy od nowa.", "restart": True}

    # ----- Kroki rozmowy -----

    def _process_usage(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        usage_mapping = {
            "Codzienne dojazdy do pracy": {"context": "commuter", "priorities": ["fuel_efficiency", "reliability"]},
            "Wyjazdy rodzinne i weekendowe": {"context": "family", "priorities": ["space", "safety", "comfort"]},
            "Jazda miejska i parkowanie": {"context": "city", "priorities": ["compact", "maneuverability"]},
            "Długie trasy autostradowe": {"context": "highway", "priorities": ["comfort", "power", "fuel_efficiency"]},
            "Jeszcze nie wiem": {"context": "general", "priorities": ["versatility"]},
        }
        state["preferences"]["usage"] = response
        if response in usage_mapping:
            state["context"].update(usage_mapping[response])

        state["step"] = "budget"
        return {
            "message": (
                "Świetnie! Jaki przedział budżetu Cię interesuje? "
                "Spokojnie, w każdej kwocie da się znaleźć dobre opcje."
            ),
            "options": [
                "Poniżej 20 000 PLN – szukam okazji",
                "20 000 – 50 000 PLN – umiarkowany budżet",
                "50 000 – 100 000 PLN – dobry budżet na jakość",
                "Powyżej 100 000 PLN – opcje premium",
                "Jestem elastyczny z budżetem"
            ],
            "step": "budget"
        }

    def _process_budget(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        state["preferences"]["budget"] = response
        # zachowaj do lekkiego punktowania
        budget_mapping = {
            "Poniżej 20 000 PLN – szukam okazji": {"max": 20000},
            "20 000 – 50 000 PLN – umiarkowany budżet": {"min": 20000, "max": 50000},
            "50 000 – 100 000 PLN – dobry budżet na jakość": {"min": 50000, "max": 100000},
            "Powyżej 100 000 PLN – opcje premium": {"min": 100000},
            "Jestem elastyczny z budżetem": {}
        }
        if response in budget_mapping:
            state["context"]["budget"] = budget_mapping[response]

        state["step"] = "size"
        size_message = (
            "Przy zastosowaniu rodzinnym przyda się przestrzeń. Na ile osób zwykle potrzebujesz miejsca?"
            if state["context"].get("context") == "family"
            else "Jaki rozmiar auta będzie dla Ciebie odpowiedni?"
        )
        return {
            "message": size_message,
            "options": [
                "Małe auto – łatwe parkowanie, oszczędne",
                "Średnie auto – balans przestrzeni i ekonomii",
                "Duże auto – maksimum przestrzeni i komfortu",
                "SUV – wyższa pozycja, wszechstronny",
                "Nie mam preferencji co do rozmiaru"
            ],
            "step": "size"
        }

    def _process_size(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        state["preferences"]["size"] = response
        state["step"] = "fuel"
        return {
            "message": "A co z rodzajem paliwa? Każdy ma swoje plusy:",
            "options": [
                "Benzyna – dobra dynamika, wszędzie dostępna",
                "Diesel – lepsza ekonomia na długie trasy",
                "Hybryda – kompromis, ekologiczna",
                "Elektryczny – zero emisji, niskie koszty",
                "Nie mam preferencji"
            ],
            "step": "fuel"
        }

    def _process_fuel(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        state["preferences"]["fuel"] = response
        state["step"] = "age"
        return {
            "message": "Na koniec – jak podchodzisz do wieku auta?",
            "options": [
                "Chcę coś dość nowego (2020 lub nowszy)",
                "Kilkuletni też może być (2015–2020)",
                "Starsze auta też wchodzą w grę, byle pewne (2010+)",
                "Wiek nieistotny, ważne żeby dobrze jeździł",
                "Pokaż wszystkie opcje"
            ],
            "step": "age"
        }

    def _process_age(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        state["preferences"]["age"] = response
        state["step"] = "final_preferences"
        summary = self._generate_summary(state["preferences"])
        return {
            "message": (
                "Super! Na podstawie naszej rozmowy:\n\n"
                f"{summary}\n\n"
                "Czy chcesz coś dodać (skrzynia, marki itp.)? "
                "Albo napisz „szukaj”, aby pokazać wyniki."
            ),
            "show_search": True,
            "step": "final_preferences"
        }

    def _process_final(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        if response.strip().lower() in {"szukaj", "wyszukaj", "pokaż wyniki", "pokaz wyniki"}:
            return self._generate_search_results(session_id)

        state["preferences"]["additional"] = response
        return {
            "message": "Zapisane. Jeśli chcesz zobaczyć oferty, napisz „szukaj”.",
            "show_search": True,
            "step": "ready_to_search"
        }

    # ----- Pomocnicze -----

    def _generate_summary(self, preferences: Dict[str, str]) -> str:
        parts = []
        if "usage" in preferences:
            parts.append(f"• Zastosowanie: {preferences['usage']}")
        if "budget" in preferences:
            parts.append(f"• Budżet: {preferences['budget']}")
        if "size" in preferences:
            parts.append(f"• Rozmiar: {preferences['size']}")
        if "fuel" in preferences:
            parts.append(f"• Paliwo: {preferences['fuel']}")
        if "age" in preferences:
            parts.append(f"• Wiek: {preferences['age']}")
        return "\n".join(parts)

    def _preferences_to_search_params(self, preferences: Dict[str, str]) -> Dict[str, Any]:
        params: Dict[str, Any] = {}

        # Budżet
        if "budget" in preferences:
            b = preferences["budget"]
            if "Poniżej 20 000" in b:
                params["price_max"] = 20000.0
            elif "20 000 – 50 000" in b or "20 000 - 50 000" in b:
                params["price_min"] = 20000.0
                params["price_max"] = 50000.0
            elif "50 000 – 100 000" in b or "50 000 - 100 000" in b:
                params["price_min"] = 50000.0
                params["price_max"] = 100000.0
            elif "Powyżej 100 000" in b:
                params["price_min"] = 100000.0

        # Paliwo
        if "fuel" in preferences:
            f = preferences["fuel"].lower()
            if "benzyn" in f:
                params["fuel_type"] = "petrol"
            elif "diesel" in f:
                params["fuel_type"] = "diesel"
            elif "hybryd" in f:
                params["fuel_type"] = "hybrid"
            elif "elektry" in f:
                params["fuel_type"] = "electric"

        # Wiek / rocznik
        if "age" in preferences:
            a = preferences["age"]
            if "2020" in a and ("nowszy" in a or "nowsze" in a):
                params["year_min"] = 2020
            elif "2015–2020" in a or "2015-2020" in a:
                params["year_min"] = 2015
                params["year_max"] = 2020
            elif "2010+" in a:
                params["year_min"] = 2010
            elif "Wiek nieistotny" in a or "Pokaż wszystkie" in a:
                pass  # brak zawężenia

        return params

    def _score_by_preferences(self, candidates, state) -> List:
        context = state.get("context", {})
        scored = []
        for car in candidates:
            score = 0.0
            if getattr(car, "year", None):
                age = CURRENT_YEAR - int(car.year)
                score += max(0, (20 - age) / 20 * 0.2)
            if getattr(car, "price", None) and "budget" in context:
                bud = context["budget"]
                if "max" in bud and car.price <= bud["max"]:
                    score += 0.3
                if "min" in bud and car.price >= bud["min"]:
                    score += 0.3
            if context.get("context") == "city" and getattr(car, "mileage", None):
                if car.mileage < 100000:
                    score += 0.2
            if context.get("context") == "family" and getattr(car, "year", None):
                if int(car.year) >= 2015:
                    score += 0.3
            if context.get("context") == "highway" and getattr(car, "power_hp", None):
                if car.power_hp >= 120:
                    score += 0.2
            if getattr(car, "link", None):
                score += 0.05
            if all([getattr(car, "price", None), getattr(car, "year", None), getattr(car, "mileage", None), getattr(car, "power_hp", None)]):
                score += 0.1
            scored.append((score, car))
        scored.sort(key=lambda x: (-x[0],
                                   x[1].price if x[1].price is not None else float("inf"),
                                   -(x[1].year if x[1].year is not None else 0)))
        return [c for _, c in scored]

    def _generate_search_results(self, session_id: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        params = self._preferences_to_search_params(state["preferences"])
        candidates = search(**params)
        candidates = _dedup_listings(candidates)
        ranked = self._score_by_preferences(candidates, state)
        return {
            "message": f"Znalazłem {len(ranked)} ofert. Oto najlepsze dopasowania:",
            "results": ranked[:20],
            "search_params": params,
            "preferences_summary": self._generate_summary(state["preferences"])
        }


# Globalny asystent
car_assistant = CarAssistant()


# ---------- ROUTES ----------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Strona główna z interfejsem asystenta"""
    return templates.TemplateResponse("assistant_index.html", {"request": request})


@app.post("/chat", response_class=JSONResponse)
async def chat(request: Request):
    """Obsługa czatu z prostym asystentem (bez OpenAI)"""
    body = await request.json()
    session_id = body.get("session_id", "default")
    message = body.get("message", "")
    option_selected = body.get("option_selected")
    action = body.get("action", "chat")

    if action == "start":
        resp = car_assistant.start_conversation(session_id)
    else:
        resp = car_assistant.process_response(session_id, message, option_selected)

    return resp


@app.get("/advanced", response_class=HTMLResponse)
async def advanced_search(request: Request):
    """Wyszukiwanie zaawansowane dla osób, które wolą ręczne filtry"""
    fuel_types = get_distinct_values("fuel_type")
    gearboxes = get_distinct_values("gearbox")
    voivodeships = get_distinct_values("voivodeship")

    return templates.TemplateResponse(
        "advanced_search.html",
        {
            "request": request,
            "fuel_types": fuel_types,
            "gearboxes": gearboxes,
            "voivodeships": voivodeships,
        },
    )


@app.post("/advanced_results", response_class=HTMLResponse)
async def advanced_results(
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
    """Obsługa formularza wyszukiwania zaawansowanego"""
    price_min_f = _to_float(price_min)
    price_max_f = _to_float(price_max)
    year_min_i = _to_int(year_min)
    year_max_i = _to_int(year_max)
    mileage_max_f = _to_float(mileage_max)
    power_min_f = _to_float(power_min)

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

    def sort_key(car):
        return (
            car.price if car.price is not None else float("inf"),
            -(car.year if car.year is not None else 0),
            car.mileage if car.mileage is not None else float("inf"),
        )

    candidates.sort(key=sort_key)

    return templates.TemplateResponse(
        "advanced_results.html",
        {"request": request, "results": candidates[:50], "total_found": len(candidates)},
    )
