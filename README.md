# Eco-Travel Advisor

## Conversational Agent for Sustainable Tourism Planning using the Rasa Platform

## 1. Project Overview

Eco-Travel Advisor is a Rasa-based chatbot for sustainable tourism planning. It guides a user through a multi-turn trip planning conversation and collects the main travel details needed to compare lower-carbon options:

- Origin
- Destination
- Travel dates or duration
- Budget
- Sustainability preference
- Transport preference

Based on these details, the assistant recommends transport, accommodation and local activities. The project includes carbon estimates, carbon offset information, fallback repair, change and reset flows, same origin/destination validation, accidental slot overwrite protection, and a human advisor handover flow.

The Streamlit frontend provides a simple chat interface with quick-reply buttons and structured result cards for transport, accommodation, activities, offsets and handover summaries.

## 2. Main Features

- Multi-turn trip planning conversation
- Quick-reply guided flow
- Change and reset trip details
- Geoapify API integration for location, routing and places data
- Climatiq API integration for carbon estimates where suitable factors are available
- Weighted transport ranking based on carbon impact, price and user preferences
- Colour-coded carbon labels for transport, hotel and activity cards
- Geoapify Places-based hotel and activity cards
- Local JSON fallback data and deterministic fallback estimates
- Human handover context packaging after user confirmation
- Fallback and error recovery for unclear or invalid messages
- Streamlit UI for local demonstration

## 3. Tech Stack

- Python
- Rasa Open Source
- Rasa SDK
- Streamlit
- Requests
- Geoapify API
- Climatiq API
- JSON fallback data

## 4. System Architecture

The project is organised around a Rasa backend, custom action server and Streamlit frontend.

- `frontend/app.py`: Streamlit chat UI, quick-reply rendering, result card rendering and connection to the Rasa REST webhook.
- `rasa_bot/data/nlu.yml`: Intent and entity training examples for the Rasa NLU model.
- `rasa_bot/data/stories.yml`: Training stories for multi-turn dialogue behaviour.
- `rasa_bot/data/rules.yml`: Deterministic dialogue rules for common flows such as recommendations, reset, change details and handover.
- `rasa_bot/domain.yml`: Intents, entities, slots, responses, quick-reply buttons and custom action declarations.
- `rasa_bot/actions/actions.py`: Custom logic for API calls, fallback estimates, recommendations, ranking, carbon information, trip summary, slot safety and human handover.
- `rasa_bot/data_mock/`: Local fallback JSON data for transport, hotels, activities and offsets.
- `rasa_bot/tests/`: Controlled NLU and Core test files.
- `rasa_bot/results/`: Evaluation outputs from Rasa NLU and Core tests.

At runtime, the Streamlit frontend sends user messages to the Rasa REST webhook. Rasa predicts intents, manages dialogue state and calls the Rasa action server when custom logic is needed. The action server uses live APIs when possible and falls back to local data or deterministic estimates when live data is unavailable.

## 5. External API Integration

Geoapify is used for:

- City geocoding
- Route distance and duration where supported
- Places search for hotel and activity card generation

Climatiq is used for carbon estimates where a suitable emission factor is available. If a Climatiq factor cannot be found or the API request fails, the system falls back to deterministic prototype estimates.

Flight route distance uses a haversine fallback because Geoapify is not a flight booking API and does not provide live flight itinerary data. Amadeus was replaced because access was unavailable during implementation. Geoapify was used as the practical alternative for live geocoding, routing and places data.

## 6. Local Fallback Strategy

The project is designed to remain usable even when external API keys are missing or live requests fail.

- If Geoapify or Climatiq keys are not configured, the system uses local JSON fallback data or deterministic estimates.
- If live requests time out or return unusable data, fallback values are used instead.
- Fallback values are labelled as `fallback_estimate`.
- The system does not falsely label fallback values as live API data.
- Recommendation cards include source information so the user can understand whether live or fallback data was used.

## 7. Environment Variables

Create a local `.env` file based on `.env.example`:

```env
CLIMATIQ_API_KEY=
GEOAPIFY_API_KEY=
RASA_API_URL=http://localhost:5005/webhooks/rest/webhook
```

`.env` must not be committed. `.env.example` is provided as a safe template for required environment variables.

## 8. Installation

Create a virtual environment and install the project dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 9. Running the Project Locally

Run the project with three terminals.

Terminal 1:

```bash
cd rasa_bot
rasa run actions
```

Terminal 2:

```bash
cd rasa_bot
rasa run --enable-api --cors "*"
```

Terminal 3:

```bash
streamlit run frontend/app.py
```

By default, the Streamlit frontend sends messages to:

```env
http://localhost:5005/webhooks/rest/webhook
```

## 10. Testing

Run the Rasa validation and test commands from the `rasa_bot` directory:

```bash
cd rasa_bot
rasa data validate
rasa train --force
rasa test nlu --nlu tests/test_nlu.yml --out results/nlu
rasa test core --stories tests/test_stories.yml --out results/core
```

Current latest controlled test results:

- NLU intent accuracy: 100% on controlled test set
- Entity extraction accuracy: 100% on controlled test set
- Core conversation accuracy: 12/12 correct on controlled test stories

These results are interpreted as controlled functional validation, not broad real-world generalisation.

## 11. Deployment Notes

Local deployment uses three services:

- Rasa action server on port `5055`
- Rasa REST server on port `5005`
- Streamlit frontend on port `8501`

For cloud deployment:

- Configure API keys as platform secrets.
- Do not expose `.env`.
- Set `RASA_API_URL` to the deployed Rasa REST endpoint.
- For Hugging Face Spaces or Docker deployment, the frontend and Rasa services may need separate containers or a startup script.
- The assignment prototype can be demonstrated locally using the three-service setup.

## Hugging Face Spaces Docker Deployment

This repository includes single-container Docker support for Hugging Face Spaces.

Deployment steps:

1. Create a new Hugging Face Space.
2. Choose Docker as the SDK.
3. Set Space visibility according to submission needs.
4. Add these secrets in Space Settings:

- `CLIMATIQ_API_KEY`
- `GEOAPIFY_API_KEY`

5. Add this variable if needed:

- `RASA_API_URL=http://localhost:5005/webhooks/rest/webhook`

6. Push the repository files to the Space repository.
7. Hugging Face will build the Docker image and run `start.sh`.
8. The public app will be available through the Space URL.

In the Docker deployment, Streamlit is exposed on port `7860`. The Rasa REST server on port `5005` and the Rasa action server on port `5055` run internally inside the same container. The Streamlit frontend calls the internal Rasa REST endpoint through `RASA_API_URL=http://localhost:5005/webhooks/rest/webhook`.

The `.env` file is not committed and is excluded from the Docker image. API keys should be configured as Hugging Face Space Secrets. Fallback estimates remain available if API keys are missing or live API calls fail.

First startup may take time because `start.sh` trains the Rasa model inside the container before starting the action server, REST server and Streamlit frontend.

## 12. Privacy, Ethics and Sustainability Notes

- The bot only prepares human advisor handover context after user confirmation.
- The handover contains trip details and selected options only.
- Geoapify hotel data does not prove eco-certification, so cards use "Not verified via API" where applicable.
- The bot warns against greenwashing and does not claim offsets make a trip fully carbon-neutral.
- API keys are kept out of GitHub through `.env` and `.gitignore`.
- Carbon estimates should be treated as planning support rather than audited emissions accounting.

## 13. Known Limitations

- Price values are deterministic prototype estimates, not live ticket fares.
- Geoapify does not provide flight booking data.
- Some transport modes may use fallback estimates if live routing or Climatiq factor matching is unavailable.
- Hotel eco-certification must be verified externally before booking.
- The test set is small and controlled.
- Live API behaviour depends on key availability, quota, network access and third-party service responses.

## 14. Repository Submission Note

GitHub repository: https://github.com/doganturan/-Eco-Travel-Advisor-Conversational-Agent-for-Sustainable-Tourism-Planning-using-the-Rasa-Platform

Live demo: <insert Hugging Face Space link here>
