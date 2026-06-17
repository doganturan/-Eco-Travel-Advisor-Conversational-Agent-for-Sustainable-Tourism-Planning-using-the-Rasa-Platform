# Eco Travel Advisor Chatbot

Eco Travel Advisor is a Rasa-based conversational AI prototype designed to help users plan more sustainable travel options. The chatbot provides eco-friendly recommendations for hotels, transport, and activities while also considering estimated carbon impact.

## Project Purpose

The purpose of this project is to design and implement a functional chatbot prototype using Rasa NLU and Rasa Core. The system aims to demonstrate how conversational AI can support sustainable travel planning through intent recognition, dialogue management, custom actions, recommendation logic, and basic carbon impact estimation.

## Main Features

- User intent recognition with Rasa NLU
- Conversation flow using Rasa Core stories and rules
- Custom actions for travel recommendations
- Mock data for hotels, transport, activities, and carbon offsets
- Basic carbon calculation or fallback mock carbon values
- Recommendation ranking based on eco-friendly criteria
- Human handover fallback
- Simple frontend prototype
- Testing documentation for NLU, Core, and user testing

## Project Structure

```text
eco-travel-advisor/
│
├── rasa_bot/
│   ├── data/
│   │   ├── nlu.yml
│   │   ├── stories.yml
│   │   └── rules.yml
│   ├── actions/
│   │   └── actions.py
│   ├── data_mock/
│   │   ├── hotels.json
│   │   ├── transport.json
│   │   ├── activities.json
│   │   └── offsets.json
│   ├── domain.yml
│   ├── config.yml
│   ├── endpoints.yml
│   └── credentials.yml
│
├── frontend/
│   └── app.py
│
├── report/
│   ├── assets/
│   └── notes.md
│
├── README.md
├── .env.example
├── .gitignore
└── requirements.txt

## Assignment Checklist

- [ ] Research completed
- [ ] Functional requirements table
- [ ] Non-functional requirements table
- [ ] Conversation flow diagram
- [ ] Rasa NLU implemented
- [ ] Rasa Core stories/rules implemented
- [ ] Custom actions implemented
- [ ] Carbon calculation / fallback mock data
- [ ] Recommendation ranking
- [ ] Human handover
- [ ] Frontend prototype
- [ ] NLU testing
- [ ] Core testing
- [ ] User testing
- [ ] Deployment documentation
- [ ] GitHub link
- [ ] Final report


## Technologies

- Python
- Rasa
- Streamlit or simple Python frontend
- JSON mock data
- GitHub for version control