# ArogyaMitra triage agent

A voice agent that does first-line patient triage in five languages, books appointments, and a small detector that
classifies skin wounds from a photo.

## Voice agent (`backend/agent.py`)

Built on LiveKit Agents. The patient joins a LiveKit room from the web app and talks to a `TriageAgent` that:

- speaks **English, Hindi, Marathi, Punjabi and Tamil**: Whisper large-v3-turbo on Groq for speech-to-text, Deepgram
  or ElevenLabs voices for speech, Silero VAD and a multilingual turn detector;
- identifies the patient (name, phone, email, optional insurance details);
- assesses an injury or mental-health concern from the described symptoms;
- books and lists appointments by specialty, date and time;
- stores patients, doctors and appointments in SQLite and emails a confirmation.

`backend/server.py` is a small Flask service that issues LiveKit access tokens (`/getToken`) and creates rooms.
`app/` is the Next.js client.

## Wound detector (`backend/`)

YOLO11n fine-tuned on a Roboflow wound dataset (~3,300 labelled images) with five classes: abrasion, bruise, burn,
cut and no abnormality.

| Metric (validation, best epoch) | Value |
| --- | --- |
| Precision | 0.748 |
| Recall | 0.681 |
| mAP@50 | 0.738 |
| mAP@50-95 | 0.434 |

Training notebook: `backend/yolo11_train.ipynb`; plots and per-epoch results: `backend/yolo_evaluation/`.

## Run

```bash
cd backend
pip install "livekit-agents[deepgram,groq,silero,elevenlabs,turn-detector]" flask flask-cors python-dotenv ultralytics
# .env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, GROQ_API_KEY, DEEPGRAM_API_KEY, ELEVEN_API_KEY
python server.py            # token service
python agent.py dev         # voice agent
cd ../app && npm install && npm run dev
```

## Tech

Python · LiveKit Agents · Groq (Whisper, Llama) · Deepgram · ElevenLabs · SQLite · Flask · Ultralytics YOLO11 · Next.js
