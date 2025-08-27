from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional, List, Dict, Any
import json
import re

from .db import init_db, seed_from_csv
from .repo import get_distinct_values, search

app = FastAPI(title="Car Assistant - Find Your Perfect Car")
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
    """Remove true duplicates based ONLY on normalized link.
    Listings without a link are kept (no dedup), to avoid false merges."""
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


class CarAssistant:
    """AI Assistant to help users find cars through conversation"""
    
    def __init__(self):
        self.conversation_states = {}
        
    def start_conversation(self, session_id: str) -> Dict[str, Any]:
        """Initialize a new conversation"""
        self.conversation_states[session_id] = {
            'step': 'welcome',
            'preferences': {},
            'context': {}
        }
        return {
            'message': "Hi! I'm your car assistant. I'll help you find the perfect car by asking a few simple questions. Let's start!\n\nWhat's your main use for this car?",
            'options': [
                "Daily commuting to work",
                "Family trips and weekend outings", 
                "City driving and parking",
                "Long highway drives",
                "I'm not sure yet"
            ],
            'step': 'usage'
        }
    
    def process_response(self, session_id: str, response: str, option_selected: Optional[str] = None) -> Dict[str, Any]:
        """Process user response and return next question"""
        if session_id not in self.conversation_states:
            return self.start_conversation(session_id)
            
        state = self.conversation_states[session_id]
        
        if state['step'] == 'usage' or state['step'] == 'welcome':
            return self._process_usage(session_id, option_selected or response)
        elif state['step'] == 'budget':
            return self._process_budget(session_id, option_selected or response)
        elif state['step'] == 'size':
            return self._process_size(session_id, option_selected or response)
        elif state['step'] == 'fuel':
            return self._process_fuel(session_id, option_selected or response)
        elif state['step'] == 'age':
            return self._process_age(session_id, option_selected or response)
        elif state['step'] == 'final_preferences':
            return self._process_final(session_id, response)
        
        return {'message': 'Sorry, something went wrong. Let me start over.', 'restart': True}
    
    def _process_usage(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        
        usage_mapping = {
            "Daily commuting to work": {"context": "commuter", "priorities": ["fuel_efficiency", "reliability"]},
            "Family trips and weekend outings": {"context": "family", "priorities": ["space", "safety", "comfort"]},
            "City driving and parking": {"context": "city", "priorities": ["compact", "maneuverability"]},
            "Long highway drives": {"context": "highway", "priorities": ["comfort", "power", "fuel_efficiency"]},
            "I'm not sure yet": {"context": "general", "priorities": ["versatility"]}
        }
        
        state['preferences']['usage'] = response
        if response in usage_mapping:
            state['context'].update(usage_mapping[response])
        
        state['step'] = 'budget'
        
        return {
            'message': "Great! Now, what's your budget range? Don't worry, we can find good options in any range.",
            'options': [
                "Under 20,000 PLN - Looking for a good deal",
                "20,000 - 50,000 PLN - Moderate budget",
                "50,000 - 100,000 PLN - Good budget for quality",
                "Over 100,000 PLN - Premium options",
                "I'm flexible with budget"
            ],
            'step': 'budget'
        }
    
    def _process_budget(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        
        budget_mapping = {
            "Under 20,000 PLN - Looking for a good deal": {"max": 20000, "focus": "value"},
            "20,000 - 50,000 PLN - Moderate budget": {"max": 50000, "focus": "balance"},
            "50,000 - 100,000 PLN - Good budget for quality": {"max": 100000, "focus": "quality"},
            "Over 100,000 PLN - Premium options": {"min": 100000, "focus": "premium"},
            "I'm flexible with budget": {"focus": "flexible"}
        }
        
        state['preferences']['budget'] = response
        if response in budget_mapping:
            state['context']['budget'] = budget_mapping[response]
        
        state['step'] = 'size'
        
        # Customize message based on usage
        if state['context'].get('context') == 'family':
            size_message = "For family use, you'll probably want something with good space. How many people do you usually need to seat?"
        else:
            size_message = "What size car feels right for you?"
        
        return {
            'message': size_message,
            'options': [
                "Small car - Easy to park, economical",
                "Medium car - Good balance of space and efficiency", 
                "Large car - Maximum space and comfort",
                "SUV - Higher driving position, versatile",
                "I'm not sure about size"
            ],
            'step': 'size'
        }
    
    def _process_size(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        state['preferences']['size'] = response
        state['step'] = 'fuel'
        
        return {
            'message': "What about fuel type? Each has its benefits:",
            'options': [
                "Petrol - Good performance, widely available",
                "Diesel - Better fuel economy for long drives",
                "Hybrid - Best of both worlds, eco-friendly",
                "Electric - Zero emissions, low running costs",
                "I don't have a strong preference"
            ],
            'step': 'fuel'
        }
    
    def _process_fuel(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        state['preferences']['fuel'] = response
        state['step'] = 'age'
        
        return {
            'message': "Finally, how do you feel about the car's age? Newer isn't always necessary!",
            'options': [
                "I want something quite new (2020 or newer)",
                "A few years old is fine (2015-2020)",
                "Older cars are okay if they're reliable (2010+)",
                "Age doesn't matter, just needs to work well",
                "Let me see all options"
            ],
            'step': 'age'
        }
    
    def _process_age(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        state['preferences']['age'] = response
        state['step'] = 'final_preferences'
        
        # Generate summary
        summary = self._generate_summary(state['preferences'])
        
        return {
            'message': f"Perfect! Based on our conversation:\n\n{summary}\n\nIs there anything specific you'd like to add or change? For example:\n- Automatic or manual transmission preference\n- Specific brands you like or want to avoid\n- Any other requirements\n\nOr just say 'search' to find your cars!",
            'step': 'final_preferences',
            'show_search': True
        }
    
    def _process_final(self, session_id: str, response: str) -> Dict[str, Any]:
        state = self.conversation_states[session_id]
        
        if response.lower().strip() in ['search', 'find cars', 'show results', 'go']:
            return self._generate_search_results(session_id)
        
        # Process additional preferences
        state['preferences']['additional'] = response
        return {
            'message': f"Got it! I've noted: {response}\n\nReady to search for your perfect car?",
            'show_search': True,
            'step': 'ready_to_search'
        }
    
    def _generate_summary(self, preferences: Dict[str, str]) -> str:
        """Generate a human-readable summary of preferences"""
        summary = []
        if 'usage' in preferences:
            summary.append(f"• Usage: {preferences['usage']}")
        if 'budget' in preferences:
            summary.append(f"• Budget: {preferences['budget']}")
        if 'size' in preferences:
            summary.append(f"• Size: {preferences['size']}")
        if 'fuel' in preferences:
            summary.append(f"• Fuel: {preferences['fuel']}")
        if 'age' in preferences:
            summary.append(f"• Age preference: {preferences['age']}")
        
        return "\n".join(summary)
    
    def _generate_search_results(self, session_id: str) -> Dict[str, Any]:
        """Convert preferences to search parameters and get results"""
        if session_id not in self.conversation_states:
            return {'error': 'Session not found'}
            
        state = self.conversation_states[session_id]
        search_params = self._preferences_to_search_params(state['preferences'])
        
        # Get candidates from database
        candidates = search(**search_params)
        candidates = _dedup_listings(candidates)
        
        # Simple scoring based on preferences context
        scored_candidates = self._score_by_preferences(candidates, state)
        
        return {
            'message': f"Great! I found {len(scored_candidates)} cars that match your preferences. Here are the best matches:",
            'results': scored_candidates[:20],  # Top 20 results
            'search_params': search_params,
            'preferences_summary': self._generate_summary(state['preferences'])
        }
    
    def _preferences_to_search_params(self, preferences: Dict[str, str]) -> Dict[str, Any]:
        """Convert user preferences to database search parameters"""
        params = {}
        
        # Budget mapping
        if 'budget' in preferences:
            budget = preferences['budget']
            if "Under 20,000" in budget:
                params['price_max'] = 20000.0
            elif "20,000 - 50,000" in budget:
                params['price_min'] = 20000.0
                params['price_max'] = 50000.0
            elif "50,000 - 100,000" in budget:
                params['price_min'] = 50000.0
                params['price_max'] = 100000.0
            elif "Over 100,000" in budget:
                params['price_min'] = 100000.0
        
        # Fuel type mapping
        if 'fuel' in preferences:
            fuel = preferences['fuel'].lower()
            if 'petrol' in fuel:
                params['fuel_type'] = 'petrol'
            elif 'diesel' in fuel:
                params['fuel_type'] = 'diesel'
            elif 'hybrid' in fuel:
                params['fuel_type'] = 'hybrid'
            elif 'electric' in fuel:
                params['fuel_type'] = 'electric'
        
        # Age/year mapping
        if 'age' in preferences:
            age = preferences['age']
            if "2020 or newer" in age:
                params['year_min'] = 2020
            elif "2015-2020" in age:
                params['year_min'] = 2015
                params['year_max'] = 2020
            elif "2010+" in age:
                params['year_min'] = 2010
        
        return params
    
    def _score_by_preferences(self, candidates, state) -> List:
        """Simple scoring based on user preferences and context"""
        context = state.get('context', {})
        preferences = state.get('preferences', {})
        
        scored = []
        for car in candidates:
            score = 0.0
            
            # Base score - newer cars get slight preference
            if car.year:
                age = CURRENT_YEAR - int(car.year)
                score += max(0, (20 - age) / 20 * 0.2)  # Max 0.2 points for age
            
            # Budget alignment - prefer cars in middle of budget range
            if car.price and 'budget' in context:
                budget_info = context['budget']
                if 'max' in budget_info and car.price <= budget_info['max']:
                    score += 0.3
                if 'min' in budget_info and car.price >= budget_info['min']:
                    score += 0.3
            
            # Usage-based scoring
            usage_context = context.get('context')
            if usage_context == 'city' and car.mileage:
                # City driving - prefer lower mileage
                if car.mileage < 100000:
                    score += 0.2
            elif usage_context == 'family':
                # Family use - prefer newer, reliable cars
                if car.year and int(car.year) >= 2015:
                    score += 0.3
            elif usage_context == 'highway' and car.power_hp:
                # Highway driving - prefer more power
                if car.power_hp >= 120:
                    score += 0.2
            
            # Completeness bonus
            if car.link:
                score += 0.05
            if all([car.price, car.year, car.mileage, car.power_hp]):
                score += 0.1
            
            scored.append((score, car))
        
        # Sort by score (descending), then by price (ascending), then by year (descending)
        scored.sort(key=lambda x: (-x[0], 
                                   x[1].price if x[1].price else float('inf'),
                                   -(x[1].year if x[1].year else 0)))
        
        return [car for _, car in scored]


# Global assistant instance
car_assistant = CarAssistant()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main page with AI assistant interface"""
    return templates.TemplateResponse(
        "assistant_index.html",
        {"request": request}
    )


@app.post("/chat", response_class=JSONResponse)
async def chat(request: Request):
    """Handle chat messages with the AI assistant"""
    body = await request.json()
    session_id = body.get('session_id', 'default')
    message = body.get('message', '')
    option_selected = body.get('option_selected')
    action = body.get('action', 'chat')
    
    if action == 'start':
        response = car_assistant.start_conversation(session_id)
    else:
        response = car_assistant.process_response(session_id, message, option_selected)
    
    return response


@app.get("/advanced", response_class=HTMLResponse)
async def advanced_search(request: Request):
    """Advanced search page for users who want manual control"""
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
    """Handle advanced search form submission"""
    # Convert form inputs
    price_min_f = _to_float(price_min)
    price_max_f = _to_float(price_max)
    year_min_i = _to_int(year_min)
    year_max_i = _to_int(year_max)
    mileage_max_f = _to_float(mileage_max)
    power_min_f = _to_float(power_min)

    # Search database
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
    
    # Simple sort by price, then year, then mileage
    def sort_key(car):
        return (
            car.price if car.price is not None else float('inf'),
            -(car.year if car.year is not None else 0),
            car.mileage if car.mileage is not None else float('inf')
        )
    
    candidates.sort(key=sort_key)

    return templates.TemplateResponse(
        "advanced_results.html",
        {
            "request": request,
            "results": candidates[:50],
            "total_found": len(candidates)
        },
    )