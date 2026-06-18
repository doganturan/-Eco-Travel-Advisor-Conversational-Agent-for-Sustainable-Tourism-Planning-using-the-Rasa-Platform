import os
import requests
import streamlit as st


RASA_API_URL = os.getenv(
    "RASA_API_URL",
    "http://localhost:5005/webhooks/rest/webhook"
)


st.set_page_config(
    page_title="Eco-Travel Advisor",
    page_icon="🌱",
    layout="centered"
)


st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
    }

    .subtitle {
        color: #4b5563;
        margin-bottom: 1.5rem;
    }

    .eco-card {
        border-radius: 14px;
        padding: 16px;
        margin: 12px 0;
        background: #ffffff;
        border: 1px solid #e5e7eb;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }

    .green-card {
        border-left: 8px solid #16a34a;
    }

    .amber-card {
        border-left: 8px solid #f59e0b;
    }

    .red-card {
        border-left: 8px solid #dc2626;
    }

    .neutral-card {
        border-left: 8px solid #64748b;
    }

    .card-title {
        font-size: 1.05rem;
        font-weight: 700;
        margin-bottom: 6px;
    }

    .card-meta {
        color: #374151;
        font-size: 0.94rem;
        line-height: 1.55;
    }

    .warning-box {
        padding: 12px;
        border-radius: 10px;
        background: #fff7ed;
        border-left: 6px solid #f97316;
        margin: 10px 0;
    }

    .handover-box {
        padding: 14px;
        border-radius: 12px;
        background: #eff6ff;
        border-left: 8px solid #2563eb;
        margin: 12px 0;
    }

    .small-label {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 700;
        background: #f3f4f6;
        margin-top: 4px;
    }

    .eco-card,
    .eco-card *,
    .warning-box,
    .warning-box *,
    .handover-box,
    .handover-box * {
    color: #111827;
}
    </style>
    """,
    unsafe_allow_html=True
)


def get_card_class(label):
    if label == "green":
        return "green-card"
    if label == "amber":
        return "amber-card"
    if label == "red":
        return "red-card"
    return "neutral-card"


def send_message_to_rasa(message):
    try:
        response = requests.post(
            RASA_API_URL,
            json={
                "sender": st.session_state.sender_id,
                "message": message
            },
            timeout=60
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException:
        return [
            {
                "text": (
                    "I could not reach the Rasa server. "
                    "Please make sure `rasa run --enable-api --cors \"*\"` is running."
                )
            }
        ]


def add_user_message(text):
    st.session_state.messages.append(
        {
            "role": "user",
            "text": text
        }
    )


def add_bot_message(message):
    st.session_state.messages.append(
        {
            "role": "assistant",
            "text": message.get("text"),
            "buttons": message.get("buttons"),
            "custom": message.get("custom")
        }
    )


def process_user_input(text):
    add_user_message(text)
    bot_responses = send_message_to_rasa(text)

    for response in bot_responses:
        add_bot_message(response)


def render_transport_card(data):
    card_class = get_card_class(data.get("carbon_label"))

    st.markdown(
        f"""
        <div class="eco-card {card_class}">
            <div class="card-title">{data.get("title", "Transport option")}</div>
            <div class="card-meta">
                <strong>Mode:</strong> {data.get("mode", "-")}<br>
                <strong>Provider:</strong> {data.get("provider", "-")}<br>
                <strong>Estimated CO₂e:</strong> {data.get("estimated_co2_kg", "-")} kg<br>
                <strong>Price:</strong> €{data.get("price_eur", "-")}<br>
                <strong>Duration:</strong> {data.get("duration_hours", "-")} hours<br>
                <strong>Score:</strong> {data.get("score", "-")}/100<br>
                <span class="small-label">Label: {data.get("carbon_label", "neutral")}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if data.get("carbon_label") == "red":
        st.markdown(
            """
            <div class="warning-box">
                This is a high-emission option. Consider train or bus before choosing this route.
            </div>
            """,
            unsafe_allow_html=True
        )


def render_ranked_transport_cards(data):
    cards = data.get("cards", [])

    if not cards:
        return

    st.markdown("#### Ranked transport options")

    for card in cards:
        card_class = get_card_class(card.get("carbon_label"))

        st.markdown(
            f"""
            <div class="eco-card {card_class}">
                <div class="card-title">
                    #{card.get("rank")} — {str(card.get("mode", "Transport")).title()}
                </div>
                <div class="card-meta">
                    <strong>Provider:</strong> {card.get("provider", "-")}<br>
                    <strong>Estimated CO₂e:</strong> {card.get("estimated_co2_kg", "-")} kg<br>
                    <strong>Price:</strong> €{card.get("price_eur", "-")}<br>
                    <strong>Duration:</strong> {card.get("duration_hours", "-")} hours<br>
                    <strong>Score:</strong> {card.get("score", "-")}/100<br>
                    <span class="small-label">Label: {card.get("carbon_label", "neutral")}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )


def render_hotel_cards(data):
    cards = data.get("cards", [])

    if not cards:
        return

    st.markdown("#### Eco-friendly accommodation")

    for card in cards:
        card_class = get_card_class(card.get("carbon_label"))
        features = ", ".join(card.get("features", []))

        st.markdown(
            f"""
            <div class="eco-card {card_class}">
                <div class="card-title">{card.get("name", "Hotel")}</div>
                <div class="card-meta">
                    <strong>Eco certification:</strong> {card.get("eco_certification", "-")}<br>
                    <strong>Price:</strong> €{card.get("price_per_night_eur", "-")}/night<br>
                    <strong>Rating:</strong> {card.get("rating", "-")}<br>
                    <strong>Estimated CO₂e:</strong> {card.get("estimated_co2_kg_per_night", "-")} kg/night<br>
                    <strong>Features:</strong> {features}<br>
                    <span class="small-label">Label: {card.get("carbon_label", "neutral")}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        if card.get("eco_certification") == "Not verified":
            st.markdown(
                """
                <div class="warning-box">
                    Sustainability evidence is limited for this accommodation. The claim should be treated cautiously.
                </div>
                """,
                unsafe_allow_html=True
            )


def render_activity_cards(data):
    cards = data.get("cards", [])

    if not cards:
        return

    st.markdown("#### Low-impact local activities")

    for card in cards:
        card_class = get_card_class(card.get("carbon_label"))

        st.markdown(
            f"""
            <div class="eco-card {card_class}">
                <div class="card-title">{card.get("name", "Activity")}</div>
                <div class="card-meta">
                    <strong>Category:</strong> {card.get("category", "-")}<br>
                    <strong>Price:</strong> €{card.get("price_eur", "-")}<br>
                    <strong>Estimated CO₂e:</strong> {card.get("estimated_co2_kg", "-")} kg<br>
                    <strong>Duration:</strong> {card.get("duration_hours", "-")} hours<br>
                    <strong>Community benefit:</strong> {card.get("community_benefit", "-")}<br>
                    <strong>Description:</strong> {card.get("description", "-")}<br>
                    <span class="small-label">Label: {card.get("carbon_label", "neutral")}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )


def render_offset_cards(data):
    cards = data.get("cards", [])

    if not cards:
        return

    st.markdown("#### Carbon offset information")

    st.markdown(
        """
        <div class="warning-box">
            Offsets are presented cautiously. Reducing emissions first is preferred before compensation.
        </div>
        """,
        unsafe_allow_html=True
    )

    for card in cards:
        st.markdown(
            f"""
            <div class="eco-card amber-card">
                <div class="card-title">{card.get("name", "Offset option")}</div>
                <div class="card-meta">
                    <strong>Project type:</strong> {card.get("project_type", "-")}<br>
                    <strong>Verification:</strong> {card.get("verification_level", "-")}<br>
                    <strong>Cost per tonne:</strong> €{card.get("cost_per_tonne_eur", "-")}<br>
                    <strong>Estimated contribution:</strong> €{card.get("estimated_contribution_eur", "-")}<br>
                    <strong>Caution:</strong> {card.get("caution_note", "-")}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )


def render_trip_summary(data):
    st.markdown("#### Final trip summary")

    st.markdown(
        f"""
        <div class="eco-card green-card">
            <div class="card-title">Eco-travel plan</div>
            <div class="card-meta">
                <strong>Origin:</strong> {data.get("origin", "-")}<br>
                <strong>Destination:</strong> {data.get("destination", "-")}<br>
                <strong>Dates/duration:</strong> {data.get("travel_dates", "-")}<br>
                <strong>Budget:</strong> {data.get("budget", "-")}<br>
                <strong>Sustainability preference:</strong> {data.get("sustainability_preference", "-")}<br>
                <strong>Transport:</strong> {data.get("selected_transport", "-")}<br>
                <strong>Accommodation:</strong> {data.get("selected_hotel", "-")}<br>
                <strong>Activity:</strong> {data.get("selected_activity", "-")}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_handover(data):
    context = data.get("context", {})

    st.session_state.handover_active = True

    st.markdown(
        f"""
        <div class="handover-box">
            <div class="card-title">Human advisor handover requested</div>
            <div class="card-meta">
                A human advisor can continue from this point. The following trip context is prepared:<br><br>
                <strong>Origin:</strong> {context.get("origin", "-")}<br>
                <strong>Destination:</strong> {context.get("destination", "-")}<br>
                <strong>Dates/duration:</strong> {context.get("travel_dates", "-")}<br>
                <strong>Budget:</strong> {context.get("budget", "-")}<br>
                <strong>Sustainability preference:</strong> {context.get("sustainability_preference", "-")}<br>
                <strong>Selected transport:</strong> {context.get("selected_transport", "-")}<br>
                <strong>Selected hotel:</strong> {context.get("selected_hotel", "-")}<br>
                <strong>Selected activity:</strong> {context.get("selected_activity", "-")}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_custom_payload(custom):
    if not custom:
        return

    payload_type = custom.get("type")

    if payload_type == "transport_card":
        render_transport_card(custom)
    elif payload_type == "ranked_transport_options":
        render_ranked_transport_cards(custom)
    elif payload_type == "hotel_cards":
        render_hotel_cards(custom)
    elif payload_type == "activity_cards":
        render_activity_cards(custom)
    elif payload_type == "offset_cards":
        render_offset_cards(custom)
    elif payload_type == "trip_summary":
        render_trip_summary(custom)
    elif payload_type == "human_handover":
        render_handover(custom)
    else:
        st.json(custom)


def render_message(message, index):
    role = message.get("role", "assistant")
    text = message.get("text")
    buttons = message.get("buttons")
    custom = message.get("custom")

    with st.chat_message(role):
        if text:
            st.markdown(text)

        render_custom_payload(custom)

        if buttons:
            columns = st.columns(len(buttons))

            for button_index, button in enumerate(buttons):
                title = button.get("title", "Option")
                payload = button.get("payload", title)

                with columns[button_index]:
                    if st.button(title, key=f"btn_{index}_{button_index}_{title}"):
                        process_user_input(payload)
                        st.rerun()


if "messages" not in st.session_state:
    st.session_state.messages = []

if "sender_id" not in st.session_state:
    st.session_state.sender_id = "streamlit_user"

if "handover_active" not in st.session_state:
    st.session_state.handover_active = False


st.markdown('<div class="main-title">🌱 Eco-Travel Advisor</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">Plan lower-carbon trips with transport, accommodation, activity, offset and human handover support.</div>',
    unsafe_allow_html=True
)


with st.sidebar:
    st.header("Prototype status")

    if st.session_state.handover_active:
        st.success("Human handover requested")
    else:
        st.info("Bot conversation active")

    st.markdown("**Rasa endpoint:**")
    st.code(RASA_API_URL)

    if st.button("Reset conversation"):
        st.session_state.messages = []
        st.session_state.handover_active = False
        st.rerun()

    st.markdown("---")
    st.markdown(
        "This prototype uses approximate carbon values and mock datasets. "
        "Sustainability claims should be presented transparently."
    )


for index, message in enumerate(st.session_state.messages):
    render_message(message, index)


user_input = st.chat_input("Type your message...")

if user_input:
    process_user_input(user_input)
    st.rerun()