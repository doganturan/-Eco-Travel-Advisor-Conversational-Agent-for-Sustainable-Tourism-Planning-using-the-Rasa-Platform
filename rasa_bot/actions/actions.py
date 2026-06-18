from typing import Any, Text, Dict, List, Optional, Tuple
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, FollowupAction
import json
import math
import os

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


if load_dotenv:
    project_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    load_dotenv(project_env)
    load_dotenv()


API_TIMEOUT = 3
GEOAPIFY_BASE_URL = "https://api.geoapify.com"
CLIMATIQ_BASE_URL = "https://api.climatiq.io"
CLIMATIQ_DATA_VERSION = "^34"

GEOCODE_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}
ROUTE_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}
CLIMATIQ_ACTIVITY_CACHE: Dict[str, Optional[str]] = {}
EMISSION_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}
TRANSPORT_OPTIONS_CACHE: Dict[str, List[Dict[str, Any]]] = {}
PLACES_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def load_json(filename: str) -> List[Dict[str, Any]]:
    """
    Loads local fallback data from rasa_bot/data_mock.
    Live APIs are tried first; these files keep the prototype usable offline.
    """
    base_dir = os.path.join(os.path.dirname(__file__), "..", "data_mock")
    file_path = os.path.abspath(os.path.join(base_dir, filename))

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def normalise(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip().lower()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def carbon_colour_label(co2_kg: float) -> str:
    """
    Frontend can use this value to display green, amber or red result cards.
    """
    if co2_kg <= 40:
        return "green"
    if co2_kg <= 100:
        return "amber"
    return "red"


def get_route_options(origin: Optional[str], destination: Optional[str]) -> List[Dict[str, Any]]:
    transport_options = load_json("transport.json")
    origin_norm = normalise(origin)
    destination_norm = normalise(destination)

    return [
        option for option in transport_options
        if normalise(option.get("origin")) == origin_norm
        and normalise(option.get("destination")) == destination_norm
    ]


def get_destination_items(filename: str, destination: Optional[str]) -> List[Dict[str, Any]]:
    items = load_json(filename)
    destination_norm = normalise(destination)

    return [
        item for item in items
        if normalise(item.get("destination")) == destination_norm
    ]


def geoapify_geocode_city(city_name: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("GEOAPIFY_API_KEY")
    if not api_key or not city_name:
        return None

    cache_key = normalise(city_name)
    if cache_key in GEOCODE_CACHE:
        return GEOCODE_CACHE[cache_key]

    try:
        response = requests.get(
            f"{GEOAPIFY_BASE_URL}/v1/geocode/search",
            params={
                "text": city_name,
                "type": "city",
                "limit": 1,
                "format": "json",
                "apiKey": api_key
            },
            timeout=API_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])

        if not results:
            return None

        result = results[0]
        lat = result.get("lat")
        lon = result.get("lon")

        if lat is None or lon is None:
            return None

        result_data = {
            "latitude": float(lat),
            "longitude": float(lon),
            "formatted": result.get("formatted") or result.get("city") or city_name,
            "city": result.get("city") or result.get("name") or city_name,
            "country": result.get("country"),
            "source": "Geoapify Geocoding"
        }
        GEOCODE_CACHE[cache_key] = result_data
        return result_data

    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError):
        GEOCODE_CACHE[cache_key] = None
        return None


def coords_tuple(coords: Dict[str, Any]) -> Tuple[float, float]:
    return float(coords["latitude"]), float(coords["longitude"])


def calculate_haversine_distance_km(lat1, lon1, lat2, lon2) -> float:
    radius_km = 6371.0
    lat1_rad = math.radians(float(lat1))
    lon1_rad = math.radians(float(lon1))
    lat2_rad = math.radians(float(lat2))
    lon2_rad = math.radians(float(lon2))

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(radius_km * c, 2)


def geoapify_modes_for_user_mode(mode: str) -> List[str]:
    mode_norm = normalise(mode)
    if mode_norm == "train":
        return ["transit", "approximated_transit"]
    if mode_norm == "bus":
        return ["bus", "approximated_transit"]
    if mode_norm == "car":
        return ["drive"]
    if mode_norm == "walk":
        return ["walk"]
    if mode_norm == "bicycle":
        return ["bicycle"]
    return []


def geoapify_get_route(
    origin_coords: Dict[str, Any],
    destination_coords: Dict[str, Any],
    mode: str
) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("GEOAPIFY_API_KEY")
    if not api_key or normalise(mode) == "flight":
        return None

    try:
        origin_lat, origin_lon = coords_tuple(origin_coords)
        destination_lat, destination_lon = coords_tuple(destination_coords)
    except (KeyError, TypeError, ValueError):
        return None

    cache_key = f"{origin_lat},{origin_lon}|{destination_lat},{destination_lon}|{normalise(mode)}"
    if cache_key in ROUTE_CACHE:
        return ROUTE_CACHE[cache_key]

    for api_mode in geoapify_modes_for_user_mode(mode):
        try:
            response = requests.get(
                f"{GEOAPIFY_BASE_URL}/v1/routing",
                params={
                    "waypoints": f"{origin_lat},{origin_lon}|{destination_lat},{destination_lon}",
                    "mode": api_mode,
                    "apiKey": api_key
                },
                timeout=API_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            features = data.get("features", [])
            if not features:
                continue

            properties = features[0].get("properties", {})
            distance_m = properties.get("distance")
            duration_s = properties.get("time")

            if distance_m is None:
                continue

            duration_hours = None
            if duration_s is not None:
                duration_hours = round(float(duration_s) / 3600, 1)

            result_data = {
                "distance_km": round(float(distance_m) / 1000, 1),
                "duration_hours": duration_hours,
                "mode": mode,
                "provider": "Geoapify Routing",
                "geoapify_mode": api_mode,
                "source": "Geoapify Routing"
            }
            ROUTE_CACHE[cache_key] = result_data
            return result_data

        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError):
            continue

    ROUTE_CACHE[cache_key] = None
    return None


def climatiq_headers() -> Optional[Dict[str, str]]:
    api_key = os.getenv("CLIMATIQ_API_KEY")
    if not api_key:
        return None
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }


def climatiq_query_for_mode(mode: str) -> str:
    queries = {
        "train": "passenger train distance",
        "bus": "passenger bus distance",
        "flight": "passenger flight distance",
        "car": "passenger car distance"
    }
    return queries.get(normalise(mode), f"passenger {mode} distance")


def climatiq_find_activity_id(mode: str) -> Optional[str]:
    headers = climatiq_headers()
    if not headers:
        return None

    mode_key = normalise(mode)
    if mode_key in CLIMATIQ_ACTIVITY_CACHE:
        return CLIMATIQ_ACTIVITY_CACHE[mode_key]

    configured_id = os.getenv(f"CLIMATIQ_ACTIVITY_ID_{mode_key.upper()}")
    if configured_id:
        CLIMATIQ_ACTIVITY_CACHE[mode_key] = configured_id
        return configured_id

    try:
        response = requests.get(
            f"{CLIMATIQ_BASE_URL}/data/v1/search",
            headers=headers,
            params={
                "query": climatiq_query_for_mode(mode),
                "data_version": CLIMATIQ_DATA_VERSION,
                "unit_type": "Distance",
                "results_per_page": 1
            },
            timeout=API_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        if not results:
            return None

        activity_id = results[0].get("activity_id")
        CLIMATIQ_ACTIVITY_CACHE[mode_key] = activity_id
        return activity_id

    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError):
        CLIMATIQ_ACTIVITY_CACHE[mode_key] = None
        return None


def climatiq_estimate_transport_emission(
    mode: str,
    distance_km: float
) -> Optional[Dict[str, Any]]:
    headers = climatiq_headers()
    if not headers or not distance_km:
        return None

    cache_key = f"{normalise(mode)}|{round(float(distance_km), 1)}"
    if cache_key in EMISSION_CACHE:
        return EMISSION_CACHE[cache_key]

    activity_id = climatiq_find_activity_id(mode)
    if not activity_id:
        return None

    try:
        response = requests.post(
            f"{CLIMATIQ_BASE_URL}/data/v1/estimate",
            headers=headers,
            json={
                "emission_factor": {
                    "activity_id": activity_id,
                    "data_version": CLIMATIQ_DATA_VERSION
                },
                "parameters": {
                    "distance": float(distance_km),
                    "distance_unit": "km"
                }
            },
            timeout=API_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        co2e = data.get("co2e")

        if co2e is None:
            return None

        result_data = {
            "co2e_kg": round(float(co2e), 2),
            "source": "Climatiq",
            "activity_id": activity_id,
            "co2e_unit": data.get("co2e_unit", "kg")
        }
        EMISSION_CACHE[cache_key] = result_data
        return result_data

    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError):
        EMISSION_CACHE[cache_key] = None
        return None


def fallback_transport_emission_kg(mode: str, distance_km: float) -> float:
    factors_kg_per_km = {
        "train": 0.035,
        "bus": 0.055,
        "flight": 0.255,
        "car": 0.171,
        "walk": 0.0,
        "bicycle": 0.0
    }
    factor = factors_kg_per_km.get(normalise(mode), 0.1)
    return round(float(distance_km) * factor, 2)


def estimate_price_eur(mode: str, distance_km: float) -> int:
    mode_norm = normalise(mode)
    if mode_norm == "bus":
        return int(max(20, round(distance_km * 0.10)))
    if mode_norm == "train":
        return int(max(35, round(distance_km * 0.16)))
    if mode_norm == "flight":
        return int(max(75, round(distance_km * 0.22)))
    return int(max(20, round(distance_km * 0.14)))


def fallback_duration_hours(mode: str, distance_km: float) -> float:
    mode_norm = normalise(mode)
    speeds = {
        "train": 90,
        "bus": 70,
        "flight": 750,
        "car": 90,
        "walk": 5,
        "bicycle": 15
    }
    extra_hours = {
        "train": 0.5,
        "bus": 0.5,
        "flight": 2.0,
        "car": 0.3,
        "walk": 0.0,
        "bicycle": 0.0
    }
    speed = speeds.get(mode_norm, 70)
    return round((float(distance_km) / speed) + extra_hours.get(mode_norm, 0.0), 1)


def build_transport_option_from_apis(
    origin: str,
    destination: str,
    origin_geo: Dict[str, Any],
    destination_geo: Dict[str, Any],
    mode: str
) -> Dict[str, Any]:
    origin_lat, origin_lon = coords_tuple(origin_geo)
    destination_lat, destination_lon = coords_tuple(destination_geo)

    route = None
    if normalise(mode) != "flight":
        route = geoapify_get_route(origin_geo, destination_geo, mode)

    if route:
        distance_km = route["distance_km"]
        duration_hours = route.get("duration_hours") or fallback_duration_hours(mode, distance_km)
        route_source = route["source"]
    else:
        base_distance = calculate_haversine_distance_km(
            origin_lat,
            origin_lon,
            destination_lat,
            destination_lon
        )
        if normalise(mode) == "flight":
            # Flight paths are not road routes; this multiplier approximates non-direct routing.
            distance_km = round(base_distance * 1.15, 1)
        else:
            distance_km = round(base_distance * 1.2, 1)
        duration_hours = fallback_duration_hours(mode, distance_km)
        route_source = "haversine_fallback"

    emission = climatiq_estimate_transport_emission(mode, distance_km)
    if emission:
        co2_kg = emission["co2e_kg"]
        carbon_source = emission["source"]
    else:
        co2_kg = fallback_transport_emission_kg(mode, distance_km)
        carbon_source = "fallback_estimate"

    price = estimate_price_eur(mode, distance_km)
    live_route_note = (
        "Live Geoapify route data used."
        if route_source == "Geoapify Routing"
        else "Live route unavailable; distance/duration use a local fallback estimate."
    )
    carbon_note = (
        "Carbon estimate from Climatiq."
        if carbon_source == "Climatiq"
        else "Carbon estimate uses local fallback factors because Climatiq was unavailable."
    )

    return {
        "route_key": f"{normalise(origin)}-{normalise(destination)}",
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "provider": f"{route_source} + {carbon_source}",
        "estimated_co2_kg": co2_kg,
        "price_eur": price,
        "duration_hours": duration_hours,
        "distance_km": distance_km,
        "sustainability_label": carbon_colour_label(co2_kg),
        "comfort_level": "medium",
        "notes": (
            f"{live_route_note} {carbon_note} "
            f"Price is a deterministic prototype estimate, not a live ticket fare."
        ),
        "data_source": "live_api" if route_source == "Geoapify Routing" or carbon_source == "Climatiq" else "fallback_estimate",
        "route_source": route_source,
        "carbon_source": carbon_source
    }


def get_api_transport_options(origin: Optional[str], destination: Optional[str]) -> List[Dict[str, Any]]:
    if not origin or not destination:
        return []

    cache_key = f"{normalise(origin)}|{normalise(destination)}"
    if cache_key in TRANSPORT_OPTIONS_CACHE:
        return TRANSPORT_OPTIONS_CACHE[cache_key]

    origin_geo = geoapify_geocode_city(origin)
    destination_geo = geoapify_geocode_city(destination)

    if not origin_geo or not destination_geo:
        TRANSPORT_OPTIONS_CACHE[cache_key] = []
        return []

    options = []
    for mode in ["train", "bus", "flight"]:
        try:
            options.append(
                build_transport_option_from_apis(
                    origin,
                    destination,
                    origin_geo,
                    destination_geo,
                    mode
                )
            )
        except (ValueError, KeyError, TypeError):
            continue

    TRANSPORT_OPTIONS_CACHE[cache_key] = options
    return options


def get_transport_options(origin: Optional[str], destination: Optional[str]) -> List[Dict[str, Any]]:
    api_options = get_api_transport_options(origin, destination)
    if api_options:
        return api_options
    return get_route_options(origin, destination)


def calculate_transport_score(
    option: Dict[str, Any],
    sustainability_preference: Optional[str],
    transport_preference: Optional[str]
) -> float:
    """
    Simple weighted scoring function:
    - If sustainability is high, carbon impact has more weight.
    - If no strong sustainability preference is given, price has more influence.
    - If a transport preference matches, a small bonus is added.
    """
    co2 = safe_float(option.get("estimated_co2_kg"), 0)
    price = safe_float(option.get("price_eur"), 0)

    carbon_score = max(0, 100 - co2)
    price_score = max(0, 100 - (price / 2))

    sustainability = normalise(sustainability_preference)
    preferred_mode = normalise(transport_preference)
    option_mode = normalise(option.get("mode"))

    if sustainability in ["high", "very sustainable", "eco"]:
        total_score = (carbon_score * 0.70) + (price_score * 0.30)
    elif sustainability == "medium":
        total_score = (carbon_score * 0.55) + (price_score * 0.45)
    else:
        total_score = (carbon_score * 0.45) + (price_score * 0.55)

    if preferred_mode and preferred_mode != "no preference" and preferred_mode == option_mode:
        total_score += 10

    return round(total_score, 2)


def choose_best_transport(
    origin: Optional[str],
    destination: Optional[str],
    sustainability_preference: Optional[str],
    transport_preference: Optional[str]
) -> Optional[Dict[str, Any]]:
    options = get_transport_options(origin, destination)

    if not options:
        return None

    preferred = normalise(transport_preference)

    if preferred and preferred != "no preference":
        preferred_options = [
            option for option in options
            if normalise(option.get("mode")) == preferred
        ]
        if preferred_options:
            options = preferred_options

    ranked = sorted(
        options,
        key=lambda option: calculate_transport_score(
            option,
            sustainability_preference,
            transport_preference
        ),
        reverse=True
    )

    return ranked[0]


def format_transport_option(option: Dict[str, Any], score: Optional[float] = None) -> str:
    score_text = f"\nScore: {score}/100" if score is not None else ""

    return (
        f"{option.get('mode', 'Transport').title()} by {option.get('provider', 'provider')}\n"
        f"Route: {option.get('origin')} to {option.get('destination')}\n"
        f"Estimated CO2e: {option.get('estimated_co2_kg')} kg\n"
        f"Price: EUR {option.get('price_eur')}\n"
        f"Duration: {option.get('duration_hours')} hours\n"
        f"Carbon label: {carbon_colour_label(safe_float(option.get('estimated_co2_kg'), 0))}"
        f"{score_text}\n"
        f"Note: {option.get('notes')}"
    )


def geoapify_search_places(
    coords: Dict[str, Any],
    categories: str,
    radius_m: int = 6000,
    limit: int = 6
) -> List[Dict[str, Any]]:
    api_key = os.getenv("GEOAPIFY_API_KEY")
    if not api_key:
        return []

    try:
        lat, lon = coords_tuple(coords)
        cache_key = f"{round(lat, 4)}|{round(lon, 4)}|{categories}|{radius_m}|{limit}"
        if cache_key in PLACES_CACHE:
            return PLACES_CACHE[cache_key]

        response = requests.get(
            f"{GEOAPIFY_BASE_URL}/v2/places",
            params={
                "categories": categories,
                "filter": f"circle:{lon},{lat},{radius_m}",
                "bias": f"proximity:{lon},{lat}",
                "limit": limit,
                "apiKey": api_key
            },
            timeout=API_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        features = data.get("features", [])
        places = [
            feature.get("properties", {})
            for feature in features
            if feature.get("properties")
        ]
        PLACES_CACHE[cache_key] = places
        return places

    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError):
        return []


def build_api_hotel_cards(destination: Optional[str]) -> List[Dict[str, Any]]:
    if not destination:
        return []

    geo = geoapify_geocode_city(destination)
    if not geo:
        return []

    places = geoapify_search_places(
        geo,
        "accommodation.hotel,accommodation.hostel,accommodation.guest_house",
        radius_m=8000,
        limit=6
    )

    cards = []
    for index, place in enumerate(places[:3], start=1):
        name = place.get("name") or place.get("address_line1") or "Accommodation option"
        distance_km = round(safe_float(place.get("distance"), 0) / 1000, 1)
        co2_per_night = round(8 + (index * 2) + min(distance_km, 3), 1)

        cards.append({
            "name": name,
            "eco_certification": "Not verified via API",
            "price_per_night_eur": 80 + (index * 18),
            "rating": "Not provided by API",
            "distance_to_public_transport_km": None,
            "estimated_co2_kg_per_night": co2_per_night,
            "sustainability_label": "API place data, certification unverified",
            "features": [
                "live Geoapify place data",
                place.get("formatted") or "near destination",
                f"{distance_km} km from search centre"
            ],
            "why_recommended": (
                "Selected from live place data near the destination; "
                "eco-certification should be verified before booking."
            ),
            "carbon_label": carbon_colour_label(co2_per_night),
            "data_source": "Geoapify Places"
        })

    return cards


def build_api_activity_cards(destination: Optional[str]) -> List[Dict[str, Any]]:
    if not destination:
        return []

    geo = geoapify_geocode_city(destination)
    if not geo:
        return []

    places = geoapify_search_places(
        geo,
        "tourism.sights,entertainment.culture,leisure.park,natural,activity.community_center",
        radius_m=9000,
        limit=8
    )

    cards = []
    for index, place in enumerate(places[:3], start=1):
        categories = place.get("categories", [])
        category = categories[0] if categories else "local experience"
        name = place.get("name") or place.get("address_line1") or "Local activity"
        co2_kg = round(0.5 + (index * 0.4), 1)

        cards.append({
            "name": name,
            "category": category,
            "price_eur": 10 + (index * 8),
            "estimated_co2_kg": co2_kg,
            "sustainability_label": "low",
            "community_benefit": "supports local cultural and visitor economy when booked locally",
            "duration_hours": 1.5 + (index * 0.5),
            "description": (
                "Selected from live Geoapify place data near the destination. "
                "Price and emissions are approximate prototype estimates."
            ),
            "carbon_label": carbon_colour_label(co2_kg),
            "data_source": "Geoapify Places"
        })

    return cards


class ActionExtractTripDetails(Action):
    def name(self) -> Text:
        return "action_extract_trip_details"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        events = []

        for entity in tracker.latest_message.get("entities", []):
            entity_name = entity.get("entity")
            value = entity.get("value")

            if entity_name == "origin":
                events.append(SlotSet("origin", value))
            elif entity_name == "destination":
                events.append(SlotSet("destination", value))
            elif entity_name == "travel_date":
                events.append(SlotSet("travel_dates", value))
            elif entity_name == "budget":
                events.append(SlotSet("budget", value))
            elif entity_name == "sustainability_preference":
                events.append(SlotSet("sustainability_preference", value))
            elif entity_name == "transport_preference":
                events.append(SlotSet("transport_preference", value))

        dispatcher.utter_message(
            text="I have saved the trip details I could identify from your message."
        )

        return events


class ActionAskMissingSlot(Action):
    def name(self) -> Text:
        return "action_ask_missing_slot"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        if not tracker.get_slot("origin"):
            dispatcher.utter_message(response="utter_ask_origin")
            return [SlotSet("fallback_count", 0)]

        if not tracker.get_slot("destination"):
            dispatcher.utter_message(response="utter_ask_destination")
            return [SlotSet("fallback_count", 0)]

        if not tracker.get_slot("travel_dates"):
            dispatcher.utter_message(response="utter_ask_travel_dates")
            return [SlotSet("fallback_count", 0)]

        if not tracker.get_slot("budget"):
            dispatcher.utter_message(response="utter_ask_budget")
            return [SlotSet("fallback_count", 0)]

        if not tracker.get_slot("sustainability_preference"):
            dispatcher.utter_message(response="utter_ask_sustainability_preference")
            return [SlotSet("fallback_count", 0)]

        if not tracker.get_slot("transport_preference"):
            dispatcher.utter_message(response="utter_ask_transport_preference")
            return [SlotSet("fallback_count", 0)]

        dispatcher.utter_message(
            text="Great, I have the key trip details. I will now compare sustainable options."
        )
        return [SlotSet("fallback_count", 0)]


class ActionRecommendTransport(Action):
    def name(self) -> Text:
        return "action_recommend_transport"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        try:
            origin = tracker.get_slot("origin")
            destination = tracker.get_slot("destination")
            sustainability_preference = tracker.get_slot("sustainability_preference")
            transport_preference = tracker.get_slot("transport_preference")

            best_option = choose_best_transport(
                origin,
                destination,
                sustainability_preference,
                transport_preference
            )

            if not best_option:
                dispatcher.utter_message(
                    text=(
                        "I could not find live or fallback transport data for that route. "
                        "Please try a supported city pair such as Berlin to Amsterdam, Copenhagen or Munich."
                    )
                )
                return []

            score = calculate_transport_score(
                best_option,
                sustainability_preference,
                transport_preference
            )

            dispatcher.utter_message(
                text="Recommended transport option:\n\n" + format_transport_option(best_option, score)
            )

            dispatcher.utter_message(
                json_message={
                    "type": "transport_card",
                    "title": f"{best_option.get('mode', '').title()} to {destination}",
                    "mode": best_option.get("mode"),
                    "provider": best_option.get("provider"),
                    "estimated_co2_kg": best_option.get("estimated_co2_kg"),
                    "price_eur": best_option.get("price_eur"),
                    "duration_hours": best_option.get("duration_hours"),
                    "carbon_label": carbon_colour_label(safe_float(best_option.get("estimated_co2_kg"), 0)),
                    "score": score,
                    "notes": best_option.get("notes"),
                    "data_source": best_option.get("data_source"),
                    "route_source": best_option.get("route_source"),
                    "carbon_source": best_option.get("carbon_source")
                }
            )

            return [
                SlotSet("selected_transport", best_option.get("mode")),
                SlotSet("selected_transport_co2_kg", best_option.get("estimated_co2_kg")),
                SlotSet("selected_transport_source", best_option.get("carbon_source") or best_option.get("data_source")),
                SlotSet("fallback_count", 0)
            ]

        except Exception:
            dispatcher.utter_message(
                text="Sorry, I could not retrieve transport recommendations right now."
            )
            return []


class ActionCalculateCarbonImpact(Action):
    def name(self) -> Text:
        return "action_calculate_carbon_impact"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        try:
            origin = tracker.get_slot("origin")
            destination = tracker.get_slot("destination")
            sustainability_preference = tracker.get_slot("sustainability_preference")
            selected_transport = tracker.get_slot("selected_transport")
            transport_preference = selected_transport or tracker.get_slot("transport_preference")

            option = choose_best_transport(
                origin,
                destination,
                sustainability_preference,
                transport_preference
            )

            if not option:
                dispatcher.utter_message(
                    text="I need a supported origin and destination before I can estimate carbon impact."
                )
                return []

            co2 = safe_float(option.get("estimated_co2_kg"), 0)
            colour = carbon_colour_label(co2)
            source = option.get("carbon_source") or option.get("data_source") or "fallback data"

            dispatcher.utter_message(
                text=(
                    f"The estimated carbon impact for the {option.get('mode')} option "
                    f"from {origin} to {destination} is approximately {co2} kg CO2e. "
                    f"Source: {source}. This is shown as a {colour} emission label in the prototype."
                )
            )

            if colour == "red":
                dispatcher.utter_message(
                    text="This is a high-emission option. I recommend comparing lower-carbon alternatives such as rail or coach before considering offsets."
                )

            return [
                SlotSet("selected_transport", option.get("mode")),
                SlotSet("selected_transport_co2_kg", option.get("estimated_co2_kg")),
                SlotSet("selected_transport_source", source),
                SlotSet("fallback_count", 0)
            ]

        except Exception:
            dispatcher.utter_message(
                text="Sorry, I could not calculate the carbon impact right now."
            )
            return []


class ActionRankOptions(Action):
    def name(self) -> Text:
        return "action_rank_options"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        try:
            origin = tracker.get_slot("origin")
            destination = tracker.get_slot("destination")
            sustainability_preference = tracker.get_slot("sustainability_preference")
            transport_preference = tracker.get_slot("transport_preference")

            options = get_transport_options(origin, destination)

            if not options:
                dispatcher.utter_message(
                    text="I could not rank transport options because live and fallback route data are unavailable for this route."
                )
                return []

            ranked_options = sorted(
                options,
                key=lambda option: calculate_transport_score(
                    option,
                    sustainability_preference,
                    transport_preference
                ),
                reverse=True
            )

            lines = ["Ranked transport options:"]
            cards = []

            for index, option in enumerate(ranked_options, start=1):
                score = calculate_transport_score(
                    option,
                    sustainability_preference,
                    transport_preference
                )

                lines.append(
                    f"{index}. {option.get('mode').title()} - "
                    f"{option.get('estimated_co2_kg')} kg CO2e, "
                    f"EUR {option.get('price_eur')}, "
                    f"score {score}/100"
                )

                cards.append({
                    "rank": index,
                    "mode": option.get("mode"),
                    "provider": option.get("provider"),
                    "estimated_co2_kg": option.get("estimated_co2_kg"),
                    "price_eur": option.get("price_eur"),
                    "duration_hours": option.get("duration_hours"),
                    "carbon_label": carbon_colour_label(safe_float(option.get("estimated_co2_kg"), 0)),
                    "score": score,
                    "notes": option.get("notes"),
                    "data_source": option.get("data_source"),
                    "route_source": option.get("route_source"),
                    "carbon_source": option.get("carbon_source")
                })

            dispatcher.utter_message(text="\n".join(lines))

            dispatcher.utter_message(
                json_message={
                    "type": "ranked_transport_options",
                    "cards": cards
                }
            )

            best_option = ranked_options[0]
            return [
                SlotSet("selected_transport", best_option.get("mode")),
                SlotSet("selected_transport_co2_kg", best_option.get("estimated_co2_kg")),
                SlotSet("selected_transport_source", best_option.get("carbon_source") or best_option.get("data_source")),
                SlotSet("fallback_count", 0)
            ]

        except Exception:
            dispatcher.utter_message(
                text="Sorry, I could not rank the options right now."
            )
            return []


class ActionRecommendHotels(Action):
    def name(self) -> Text:
        return "action_recommend_hotels"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        try:
            destination = tracker.get_slot("destination")
            hotels = build_api_hotel_cards(destination)

            if not hotels:
                hotels = get_destination_items("hotels.json", destination)

            if not hotels:
                dispatcher.utter_message(
                    text="I could not find live or fallback accommodation data for this destination."
                )
                return []

            hotels = sorted(
                hotels,
                key=lambda hotel: (
                    safe_float(hotel.get("estimated_co2_kg_per_night"), 999),
                    safe_float(hotel.get("price_per_night_eur"), 999)
                )
            )

            best_hotel = hotels[0]

            lines = ["Eco-friendly accommodation options:"]
            cards = []

            for hotel in hotels[:3]:
                lines.append(
                    f"- {hotel.get('name')} ({hotel.get('eco_certification')}), "
                    f"EUR {hotel.get('price_per_night_eur')}/night, "
                    f"{hotel.get('estimated_co2_kg_per_night')} kg CO2e/night. "
                    f"{hotel.get('why_recommended')}"
                )

                co2_per_night = safe_float(hotel.get("estimated_co2_kg_per_night"), 0)
                cards.append({
                    "name": hotel.get("name"),
                    "eco_certification": hotel.get("eco_certification"),
                    "price_per_night_eur": hotel.get("price_per_night_eur"),
                    "rating": hotel.get("rating"),
                    "estimated_co2_kg_per_night": hotel.get("estimated_co2_kg_per_night"),
                    "carbon_label": hotel.get("carbon_label") or carbon_colour_label(co2_per_night),
                    "features": hotel.get("features", []),
                    "why_recommended": hotel.get("why_recommended"),
                    "sustainability_label": hotel.get("sustainability_label"),
                    "data_source": hotel.get("data_source", "local_fallback_json")
                })

            dispatcher.utter_message(text="\n".join(lines))

            dispatcher.utter_message(
                json_message={
                    "type": "hotel_cards",
                    "destination": destination,
                    "cards": cards
                }
            )

            return [SlotSet("selected_hotel", best_hotel.get("name"))]

        except Exception:
            dispatcher.utter_message(
                text="Sorry, I could not retrieve hotel recommendations right now."
            )
            return []


class ActionRecommendActivities(Action):
    def name(self) -> Text:
        return "action_recommend_activities"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        try:
            destination = tracker.get_slot("destination")
            activities = build_api_activity_cards(destination)

            if not activities:
                activities = get_destination_items("activities.json", destination)

            if not activities:
                dispatcher.utter_message(
                    text="I could not find live or fallback activity data for this destination."
                )
                return []

            activities = sorted(
                activities,
                key=lambda activity: (
                    safe_float(activity.get("estimated_co2_kg"), 999),
                    safe_float(activity.get("price_eur"), 999)
                )
            )

            best_activity = activities[0]

            lines = ["Low-impact local activities:"]
            cards = []

            for activity in activities[:3]:
                lines.append(
                    f"- {activity.get('name')} ({activity.get('category')}), "
                    f"EUR {activity.get('price_eur')}, "
                    f"{activity.get('estimated_co2_kg')} kg CO2e. "
                    f"Community benefit: {activity.get('community_benefit')}."
                )

                co2_kg = safe_float(activity.get("estimated_co2_kg"), 0)
                cards.append({
                    "name": activity.get("name"),
                    "category": activity.get("category"),
                    "price_eur": activity.get("price_eur"),
                    "estimated_co2_kg": activity.get("estimated_co2_kg"),
                    "carbon_label": activity.get("carbon_label") or carbon_colour_label(co2_kg),
                    "community_benefit": activity.get("community_benefit"),
                    "duration_hours": activity.get("duration_hours"),
                    "description": activity.get("description"),
                    "data_source": activity.get("data_source", "local_fallback_json")
                })

            dispatcher.utter_message(text="\n".join(lines))

            dispatcher.utter_message(
                json_message={
                    "type": "activity_cards",
                    "destination": destination,
                    "cards": cards
                }
            )

            return [SlotSet("selected_activity", best_activity.get("name"))]

        except Exception:
            dispatcher.utter_message(
                text="Sorry, I could not retrieve activity recommendations right now."
            )
            return []


class ActionCarbonOffsetInfo(Action):
    def name(self) -> Text:
        return "action_carbon_offset_info"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        try:
            origin = tracker.get_slot("origin")
            destination = tracker.get_slot("destination")
            sustainability_preference = tracker.get_slot("sustainability_preference")
            selected_transport = tracker.get_slot("selected_transport")
            transport_preference = selected_transport or tracker.get_slot("transport_preference")
            selected_co2 = tracker.get_slot("selected_transport_co2_kg")
            selected_source = tracker.get_slot("selected_transport_source")

            if selected_co2 is not None:
                estimated_trip_co2 = safe_float(selected_co2, 0)
                source = selected_source or "stored selected transport estimate"
            else:
                option = choose_best_transport(
                    origin,
                    destination,
                    sustainability_preference,
                    transport_preference
                )
                estimated_trip_co2 = safe_float(option.get("estimated_co2_kg"), 0) if option else 0
                source = option.get("carbon_source") if option else "fallback data"

            offsets = load_json("offsets.json")

            lines = [
                "Offset information should be treated carefully. Reducing emissions first is better than relying on offsets.",
                f"Estimated transport emissions currently used for this advice: {estimated_trip_co2} kg CO2e ({source})."
            ]

            cards = []

            for offset in offsets:
                estimated_cost = round((estimated_trip_co2 / 1000) * safe_float(offset.get("cost_per_tonne_eur"), 0), 2)

                lines.append(
                    f"- {offset.get('name')} ({offset.get('project_type')}), "
                    f"verification: {offset.get('verification_level')}, "
                    f"estimated contribution for this transport impact: EUR {estimated_cost}. "
                    f"Caution: {offset.get('caution_note')}"
                )

                cards.append({
                    "name": offset.get("name"),
                    "project_type": offset.get("project_type"),
                    "verification_level": offset.get("verification_level"),
                    "cost_per_tonne_eur": offset.get("cost_per_tonne_eur"),
                    "estimated_contribution_eur": estimated_cost,
                    "caution_note": offset.get("caution_note")
                })

            dispatcher.utter_message(text="\n".join(lines))

            dispatcher.utter_message(
                json_message={
                    "type": "offset_cards",
                    "estimated_transport_co2_kg": estimated_trip_co2,
                    "transport_emission_source": source,
                    "cards": cards
                }
            )

            return [SlotSet("fallback_count", 0)]

        except Exception:
            dispatcher.utter_message(
                text="Sorry, I could not retrieve offset information right now."
            )
            return []


class ActionTripSummary(Action):
    def name(self) -> Text:
        return "action_trip_summary"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        origin = tracker.get_slot("origin") or "not provided"
        destination = tracker.get_slot("destination") or "not provided"
        travel_dates = tracker.get_slot("travel_dates") or "not provided"
        budget = tracker.get_slot("budget") or "not provided"
        sustainability_preference = tracker.get_slot("sustainability_preference") or "not provided"
        selected_transport = tracker.get_slot("selected_transport") or "not selected"
        selected_transport_co2 = tracker.get_slot("selected_transport_co2_kg") or "not estimated"
        selected_transport_source = tracker.get_slot("selected_transport_source") or "not available"
        selected_hotel = tracker.get_slot("selected_hotel") or "not selected"
        selected_activity = tracker.get_slot("selected_activity") or "not selected"

        summary = (
            "Eco-travel summary:\n"
            f"- Origin: {origin}\n"
            f"- Destination: {destination}\n"
            f"- Dates/duration: {travel_dates}\n"
            f"- Budget: {budget}\n"
            f"- Sustainability preference: {sustainability_preference}\n"
            f"- Recommended transport: {selected_transport}\n"
            f"- Transport CO2e: {selected_transport_co2} kg ({selected_transport_source})\n"
            f"- Recommended accommodation: {selected_hotel}\n"
            f"- Recommended activity: {selected_activity}\n\n"
            "This prototype combines live API data where available with transparent fallback estimates."
        )

        dispatcher.utter_message(text=summary)

        dispatcher.utter_message(
            json_message={
                "type": "trip_summary",
                "origin": origin,
                "destination": destination,
                "travel_dates": travel_dates,
                "budget": budget,
                "sustainability_preference": sustainability_preference,
                "selected_transport": selected_transport,
                "selected_transport_co2_kg": selected_transport_co2,
                "selected_transport_source": selected_transport_source,
                "selected_hotel": selected_hotel,
                "selected_activity": selected_activity
            }
        )

        return [SlotSet("fallback_count", 0)]


class ActionPrepareHandover(Action):
    def name(self) -> Text:
        return "action_prepare_handover"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        handover_context = {
            "origin": tracker.get_slot("origin"),
            "destination": tracker.get_slot("destination"),
            "travel_dates": tracker.get_slot("travel_dates"),
            "budget": tracker.get_slot("budget"),
            "sustainability_preference": tracker.get_slot("sustainability_preference"),
            "transport_preference": tracker.get_slot("transport_preference"),
            "selected_transport": tracker.get_slot("selected_transport"),
            "selected_transport_co2_kg": tracker.get_slot("selected_transport_co2_kg"),
            "selected_transport_source": tracker.get_slot("selected_transport_source"),
            "selected_hotel": tracker.get_slot("selected_hotel"),
            "selected_activity": tracker.get_slot("selected_activity")
        }

        dispatcher.utter_message(
            text=(
                "I have prepared a human advisor handover summary with the trip context collected so far. "
                "Only relevant trip planning details are included."
            )
        )

        dispatcher.utter_message(
            json_message={
                "type": "human_handover",
                "status": "requested",
                "message": "Human advisor handover has been prepared.",
                "context": handover_context
            }
        )

        return [
            SlotSet("handover_required", True),
            SlotSet("fallback_count", 0)
        ]


class ActionDefaultFallback(Action):
    def name(self) -> Text:
        return "action_default_fallback"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        current_count = tracker.get_slot("fallback_count") or 0
        new_count = float(current_count) + 1

        if new_count >= 2:
            dispatcher.utter_message(
                text=(
                    "I am still not fully sure what you need. "
                    "I can continue with trip planning, show carbon impact, or prepare human advisor handover."
                ),
                buttons=[
                    {"title": "Plan a trip", "payload": "/start_trip_planning"},
                    {"title": "Carbon impact", "payload": "/ask_carbon_impact"},
                    {"title": "Human help", "payload": "/request_human_handover"}
                ]
            )
        else:
            dispatcher.utter_message(
                text=(
                    "I am not fully sure I understood. "
                    "Are you asking about trip planning, carbon impact, recommendations, offsets or human help?"
                ),
                buttons=[
                    {"title": "Plan a trip", "payload": "/start_trip_planning"},
                    {"title": "Recommendations", "payload": "/ask_recommendations"},
                    {"title": "Human help", "payload": "/request_human_handover"}
                ]
            )

        return [
            SlotSet("fallback_count", new_count),
            FollowupAction("action_listen")
        ]
