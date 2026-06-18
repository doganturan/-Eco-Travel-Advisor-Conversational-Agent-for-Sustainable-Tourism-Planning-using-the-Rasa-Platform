from typing import Any, Text, Dict, List, Optional
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
import json
import os


def load_json(filename: str) -> List[Dict[str, Any]]:
    """
    Loads local mock data from rasa_bot/data_mock.
    The same structure can later be replaced with real API calls.
    """
    base_dir = os.path.join(os.path.dirname(__file__), "..", "data_mock")
    file_path = os.path.abspath(os.path.join(base_dir, filename))

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def normalise(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip().lower()


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
    co2 = float(option.get("estimated_co2_kg", 0))
    price = float(option.get("price_eur", 0))

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
    options = get_route_options(origin, destination)

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
        f"Estimated CO2: {option.get('estimated_co2_kg')} kg\n"
        f"Price: €{option.get('price_eur')}\n"
        f"Duration: {option.get('duration_hours')} hours\n"
        f"Carbon label: {carbon_colour_label(float(option.get('estimated_co2_kg', 0)))}"
        f"{score_text}\n"
        f"Note: {option.get('notes')}"
    )


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

        required_slots = [
            ("origin", "Where are you travelling from?"),
            ("destination", "What is your destination?"),
            ("travel_dates", "What are your travel dates or trip duration?"),
            ("budget", "What is your approximate budget for the trip?"),
            ("sustainability_preference", "How important is sustainability for this trip? Low, medium or high?"),
            ("transport_preference", "Do you prefer train, bus, flight, or no preference?")
        ]

        for slot_name, question in required_slots:
            if not tracker.get_slot(slot_name):
                dispatcher.utter_message(text=question)
                return []

        dispatcher.utter_message(
            text="Great, I have the key trip details. Ask me to show recommendations when you are ready."
        )
        return []


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
                        "I could not find transport data for that route in the prototype dataset. "
                        "Current prototype routes include Berlin to Amsterdam, Berlin to Copenhagen and Berlin to Munich."
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
                    "carbon_label": carbon_colour_label(float(best_option.get("estimated_co2_kg", 0))),
                    "score": score,
                    "notes": best_option.get("notes")
                }
            )

            return [SlotSet("selected_transport", best_option.get("mode"))]

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

            co2 = float(option.get("estimated_co2_kg", 0))
            colour = carbon_colour_label(co2)

            dispatcher.utter_message(
                text=(
                    f"The estimated carbon impact for the {option.get('mode')} option "
                    f"from {origin} to {destination} is approximately {co2} kg CO2e. "
                    f"This is shown as a {colour} emission label in the prototype."
                )
            )

            if colour == "red":
                dispatcher.utter_message(
                    text="This is a high-emission option. I recommend comparing lower-carbon alternatives such as rail or coach before considering offsets."
                )

            return []

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

            options = get_route_options(origin, destination)

            if not options:
                dispatcher.utter_message(
                    text="I could not rank transport options because this route is not in the prototype dataset."
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
                    f"€{option.get('price_eur')}, "
                    f"score {score}/100"
                )

                cards.append({
                    "rank": index,
                    "mode": option.get("mode"),
                    "provider": option.get("provider"),
                    "estimated_co2_kg": option.get("estimated_co2_kg"),
                    "price_eur": option.get("price_eur"),
                    "duration_hours": option.get("duration_hours"),
                    "carbon_label": carbon_colour_label(float(option.get("estimated_co2_kg", 0))),
                    "score": score
                })

            dispatcher.utter_message(text="\n".join(lines))

            dispatcher.utter_message(
                json_message={
                    "type": "ranked_transport_options",
                    "cards": cards
                }
            )

            return []

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
            hotels = get_destination_items("hotels.json", destination)

            if not hotels:
                dispatcher.utter_message(
                    text="I could not find accommodation data for this destination in the prototype dataset."
                )
                return []

            hotels = sorted(
                hotels,
                key=lambda hotel: (
                    float(hotel.get("estimated_co2_kg_per_night", 999)),
                    float(hotel.get("price_per_night_eur", 999))
                )
            )

            best_hotel = hotels[0]

            lines = ["Eco-friendly accommodation options:"]
            cards = []

            for hotel in hotels[:3]:
                lines.append(
                    f"- {hotel.get('name')} ({hotel.get('eco_certification')}), "
                    f"€{hotel.get('price_per_night_eur')}/night, "
                    f"{hotel.get('estimated_co2_kg_per_night')} kg CO2e/night. "
                    f"{hotel.get('why_recommended')}"
                )

                cards.append({
                    "name": hotel.get("name"),
                    "eco_certification": hotel.get("eco_certification"),
                    "price_per_night_eur": hotel.get("price_per_night_eur"),
                    "rating": hotel.get("rating"),
                    "estimated_co2_kg_per_night": hotel.get("estimated_co2_kg_per_night"),
                    "carbon_label": carbon_colour_label(float(hotel.get("estimated_co2_kg_per_night", 0))),
                    "features": hotel.get("features"),
                    "why_recommended": hotel.get("why_recommended")
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
            activities = get_destination_items("activities.json", destination)

            if not activities:
                dispatcher.utter_message(
                    text="I could not find activity data for this destination in the prototype dataset."
                )
                return []

            activities = sorted(
                activities,
                key=lambda activity: (
                    float(activity.get("estimated_co2_kg", 999)),
                    float(activity.get("price_eur", 999))
                )
            )

            best_activity = activities[0]

            lines = ["Low-impact local activities:"]
            cards = []

            for activity in activities[:3]:
                lines.append(
                    f"- {activity.get('name')} ({activity.get('category')}), "
                    f"€{activity.get('price_eur')}, "
                    f"{activity.get('estimated_co2_kg')} kg CO2e. "
                    f"Community benefit: {activity.get('community_benefit')}."
                )

                cards.append({
                    "name": activity.get("name"),
                    "category": activity.get("category"),
                    "price_eur": activity.get("price_eur"),
                    "estimated_co2_kg": activity.get("estimated_co2_kg"),
                    "carbon_label": carbon_colour_label(float(activity.get("estimated_co2_kg", 0))),
                    "community_benefit": activity.get("community_benefit"),
                    "duration_hours": activity.get("duration_hours"),
                    "description": activity.get("description")
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

            option = choose_best_transport(
                origin,
                destination,
                sustainability_preference,
                transport_preference
            )

            estimated_trip_co2 = float(option.get("estimated_co2_kg", 0)) if option else 0
            offsets = load_json("offsets.json")

            lines = [
                "Offset information should be treated carefully. Reducing emissions first is better than relying on offsets.",
                f"Estimated transport emissions currently used for this advice: {estimated_trip_co2} kg CO2e."
            ]

            cards = []

            for offset in offsets:
                estimated_cost = round((estimated_trip_co2 / 1000) * float(offset.get("cost_per_tonne_eur", 0)), 2)

                lines.append(
                    f"- {offset.get('name')} ({offset.get('project_type')}), "
                    f"verification: {offset.get('verification_level')}, "
                    f"estimated contribution for this transport impact: €{estimated_cost}. "
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
                    "cards": cards
                }
            )

            return []

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
            f"- Recommended accommodation: {selected_hotel}\n"
            f"- Recommended activity: {selected_activity}\n\n"
            "This prototype uses approximate carbon values and should present sustainability claims transparently."
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
                "selected_hotel": selected_hotel,
                "selected_activity": selected_activity
            }
        )

        return []


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
            SlotSet("handover_required", True)
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
            SlotSet("fallback_count", new_count)
        ]