import os
from livekit import api
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from flask_cors import CORS
from livekit.api import LiveKitAPI, ListRoomsRequest
import uuid
from groq import Groq
from typing import List, Dict
import asyncio
import re
from werkzeug.utils import secure_filename
import tempfile
import base64

from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np
import neurokit2 as nk
import logging
import cv2
from waitress import serve

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["http://localhost:3000", "http://127.0.0.1:3000"]}})
cap = cv2.VideoCapture(0)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def preprocess_signal(signal, sampling_rate):
    """Preprocess the PPG signal using NeuroKit2 best practices."""
    try:
        if signal is None or len(signal) < sampling_rate * 15:
            raise ValueError("Signal is too short or invalid (<15s).")
        cleaned = nk.signal_filter(signal, sampling_rate=sampling_rate, lowcut=0.5, highcut=2.5, method='butterworth')
        detrended = nk.signal_detrend(cleaned)
        logger.info("Signal preprocessed successfully.")
        return detrended
    except Exception as e:
        logger.error(f"Preprocessing failed: {str(e)}")
        return None, str(e)

def process_signal(signal, sampling_rate, source):
    """Process the PPG signal and extract metrics using NeuroKit2's ppg_process."""
    try:
        if signal is None or len(signal) < sampling_rate * 15:
            return {'error': f'Insufficient or invalid {source} signal data. Minimum 15 seconds required.'}
        
        # Process signal with NeuroKit2's ppg_process using 'elgendi' method
        signals, info = nk.ppg_process(
            signal,
            sampling_rate=sampling_rate,
            method='elgendi',
            method_quality='disimilarity'  # Use dissimilarity to avoid window size issues
        )
        
        # Analyze for interval-related features
        analysis = nk.ppg_analyze(
            signals,
            sampling_rate=sampling_rate,
            method='interval-related'
        )
        
        # Extract key metrics
        heart_rate = analysis['PPG_Rate_Mean'].values[0] if 'PPG_Rate_Mean' in analysis.columns else 0
        hrv = {
            'HRV_RMSSD': analysis['HRV_RMSSD'].values[0] if 'HRV_RMSSD' in analysis.columns else 0,
            'HRV_SDNN': analysis['HRV_SDNN'].values[0] if 'HRV_SDNN' in analysis.columns else 0
        }
        interval_related = {
            'PPG_Rate_Mean': heart_rate,
            'HRV_SDNN': hrv['HRV_SDNN']
        }
        quality_metrics = {
            'quality': info['PPG_Quality'].mean() if 'PPG_Quality' in info else 0
        }
        
        logger.info(f"{source} signal processed successfully: HR={heart_rate:.2f} BPM")
        return {
            'signal': signal.tolist(),
            'heart_rate': heart_rate,
            'hrv': hrv,
            'interval_related': interval_related,
            'quality_metrics': quality_metrics
        }
    except Exception as e:
        logger.error(f"{source} processing failed: {str(e)}")
        return {'error': f'{source} processing failed: {str(e)}'}

def simulate_pulse_sensor(sampling_rate, duration):
    """Simulate a pulse sensor signal for comparison."""
    try:
        signal = nk.ppg_simulate(duration=duration, sampling_rate=sampling_rate, heart_rate=70 + np.random.normal(0, 5))
        logger.info("Pulse sensor signal simulated successfully.")
        return signal
    except Exception as e:
        logger.error(f"Pulse sensor simulation failed: {str(e)}")
        return None, str(e)

@app.route('/analyze_ppg', methods=['POST'])
def analyze_ppg():
    try:
        data = request.get_json()
        if not data:
            logger.error("No data provided in request.")
            return jsonify({'error': 'No data provided.'}), 400
        
        duration = data.get('duration', 20)
        sampling_rate = data.get('sampling_rate', 30)
        roi = data.get('roi', {'x': 0.425, 'y': 0.425, 'width': 0.15, 'height': 0.15})
        cam_signal = data.get('signal', [])
        logger.info(f"Received PPG analysis request: duration={duration}, sampling_rate={sampling_rate}, signal_length={len(cam_signal)}")

        # Validate webcam signal
        if not cam_signal or len(cam_signal) < sampling_rate * 15:
            logger.error("Insufficient webcam signal data.")
            return jsonify({'error': 'Insufficient webcam signal data. Record at least 15 seconds.'}), 400
        
        cam_signal = np.array(cam_signal)
        cam_processed = preprocess_signal(cam_signal, sampling_rate)
        if isinstance(cam_processed, tuple):
            logger.error(f"Preprocessing error: {cam_processed[1]}")
            return jsonify({'error': cam_processed[1]}), 500
        cam_results = process_signal(cam_processed, sampling_rate, "Webcam")
        if 'error' in cam_results:
            logger.error(f"Webcam processing error: {cam_results['error']}")
            return jsonify({'error': cam_results['error']}), 400

        # Simulate pulse sensor data
        ps_signal = simulate_pulse_sensor(sampling_rate, duration)
        if isinstance(ps_signal, tuple):
            logger.error(f"Pulse sensor simulation error: {ps_signal[1]}")
            return jsonify({'error': ps_signal[1]}), 500
        ps_processed = preprocess_signal(ps_signal, sampling_rate)
        if isinstance(ps_processed, tuple):
            logger.error(f"Pulse sensor preprocessing error: {ps_processed[1]}")
            return jsonify({'error': ps_processed[1]}), 500
        ps_results = process_signal(ps_processed, sampling_rate, "Pulse Sensor")
        if 'error' in ps_results:
            logger.error(f"Pulse sensor processing error: {ps_results['error']}")
            return jsonify({'error': ps_results['error']}), 400

        response = {
            'webcam': cam_results,
            'pulse_sensor': ps_results,
            'warnings': []
        }
        logger.info("PPG analysis completed successfully.")
        return jsonify(response), 200
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}")
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    logger.info("Health check requested.")
    return jsonify({'status': 'healthy'}), 200


# Initialize Groq client
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("API key for Groq is missing. Please set the GROQ_API_KEY in the .env file.")
client = Groq(api_key=GROQ_API_KEY)

# Define the Conversation class with the specified system prompt
class Conversation:
    def _init_(self):
        self.messages: List[Dict[str, str]] = [
            {"role": "system", 
            "content": """
You are Riya, a compassionate, licensed medical professional operating as a virtual doctor for Symbiosis Hospital. You are part of a multidisciplinary team of healthcare providers. You do not need to repeat your identity or affiliation in every message.
Do not use markdown formatting in your responses.
Your primary goal is to provide first-line medical assistance, focusing on mental health triage, emotional support, and referring patients to the appropriate specialists or departments. Your responsibilities also include interpreting heart rate data, recommending lifestyle improvements, and managing backend tasks via tools (e.g., database access, doctor referrals, sending emails).

Key Responsibilities:
1. *Mental Health Triage & Support*
   - Always begin by checking if the patient needs support for mental health or has sustained any physical injuries.
   - Actively listen for signs of depression, anxiety, or emotional distress.
   - If the patient describes emotional difficulties:
     - Offer psychological first aid.
     - Recommend seeing a psychiatrist or a licensed counselor.
     - For children, recommend a pediatrician trained in child psychology.
     - Always offer to connect them with in-house counselors or therapists.

2. *Physical Symptom Evaluation*
   - If the patient reports physical symptoms, ask clarifying questions to narrow down the condition.
   - Based on the description, recommend the appropriate specialist (e.g., cardiologist, orthopedic surgeon, neurologist).
   - If symptoms are urgent or life-threatening, advise them to seek immediate in-person medical attention.

3. *Cardiovascular Monitoring*
   - If heart rate or cardiovascular data is provided:
     - Analyze it for anomalies (e.g., bradycardia, tachycardia).
     - Provide lifestyle recommendations to improve heart health (e.g., diet, exercise, sleep hygiene, stress reduction).
     - Flag abnormal readings for urgent review by a cardiologist.

4. *Tool Interaction*
   - Use internal tools to:
     - Retrieve and update patient data
     - Look up doctors and their specializations
     - Schedule referrals or follow-up appointments
     - Send emails to patients or medical staff
   - Ensure all sensitive operations comply with privacy and medical data guidelines.

Communication Guidelines:
- Use a professional, warm, and empathetic tone.
- Avoid any casual language, emojis, or special formatting like Markdown.
- Speak in clear, grammatically correct English with appropriate pauses, as if communicating with a real patient.
- Demonstrate clinical judgment and critical thinking before replying.
- Do not speculate; if uncertain, recommend appropriate diagnostics or a referral.

Always act in the patient's best interest and escalate any complex cases to the human medical team. Maintain a supportive and calming demeanor in all interactions.

You are currently active and monitoring patient input.
        """}
        ]
        self.active: bool = True

# Dictionary to store conversations
conversations: Dict[str, Conversation] = {}

# Function to get or create a conversation
def get_or_create_conversation(conversation_id: str) -> Conversation:
    if conversation_id not in conversations:
        conversations[conversation_id] = Conversation()
    return conversations[conversation_id]

# Function to query the Groq API and process <think> tags
def query_groq_api(conversation: Conversation, model: str) -> dict:
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=conversation.messages,
            temperature=1,
            max_tokens=1024,
            top_p=1,
            stream=True,
            stop=None,
        )
        response = ""
        for chunk in completion:
            response += chunk.choices[0].delta.content or ""
        
        # Parse the response for <think> tags
        thinking_match = re.search(r"<think>(.*?)</think>", response, re.DOTALL)
        if thinking_match:
            thinking = thinking_match.group(1).strip()
            answer = response[thinking_match.end():].strip()
        else:
            thinking = ""
            answer = response.strip()
        
        return {"thinking": thinking, "answer": answer}
    except Exception as e:
        raise Exception(f"Error with Groq API: {str(e)}")

# Async functions for room management
async def get_rooms():
    api = LiveKitAPI()
    rooms = await api.room.list_rooms(ListRoomsRequest())
    await api.aclose()
    return [room.name for room in rooms.rooms]

async def generate_room_name():
    name = "room-" + str(uuid.uuid4())[:8]
    rooms = await get_rooms()
    while name in rooms:
        name = "room-" + str(uuid.uuid4())[:8]
    return name

# Synchronous route for getting token
@app.route("/getToken")
def get_token():
    name = request.args.get("name", "my name")
    language = request.args.get("language", "en")
    room = request.args.get("room", None)
    
    if not room:
        room = asyncio.run(generate_room_name())
        
    token = api.AccessToken(os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET")) \
        .with_identity(name)\
        .with_name(name)\
        .with_metadata(language)\
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room
        ))
    
    return token.to_jwt()

# Chat endpoint
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message")
    conversation_id = data.get("conversation_id")
    model = data.get("model", "gemma2-9b-it")  # Default to gemma2-9b-it if not specified
    
    if not message or not conversation_id:
        return jsonify({"error": "Missing message or conversation_id"}), 400
    
    conversation = get_or_create_conversation(conversation_id)
    if not conversation.active:
        return jsonify({"error": "The chat session has ended. Please start a new session."}), 400
    
    conversation.messages.append({"role": "user", "content": message})
    
    try:
        result = query_groq_api(conversation, model)
        conversation.messages.append({"role": "assistant", "content": result["answer"]})
        return jsonify({
            "thinking": result["thinking"],
            "answer": result["answer"],
            "conversation_id": conversation_id
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/analyze-image", methods=["POST"])
def analyze_image():
    try:
        data = request.get_json()
        image_data = data.get("image")
        prompt = data.get("prompt", "Analyze this image for dermatological, injury, or dental concerns.")
        model = data.get("model", "meta-llama/llama-4-scout-17b-16e-instruct")

        if not image_data:
            return jsonify({"error": "No image provided"}), 400

        # Clean the base64 string
        if image_data.startswith("data:image"):
            image_data = image_data.split(",")[1]

        vision_prompt = (
                "You are a highly knowledgeable and clinically accurate medical vision assistant developed to analyze uploaded medical images. "
                "Your role is to independently evaluate the visual data and provide a detailed diagnostic assessment without disclaimers like 'consult a doctor for advice.' "
                "You must fully address the user's concerns with evidence-based explanations and actionable next steps. "
                "Adapt your interpretation based on the medical context of the image. Use expert-level judgment and avoid vague or generic responses.\n\n"
                "Provide skin care routines if asked with the upload of images."
                "If the image pertains to a skin condition:\n"
                "- Examine for dermatological patterns including, but not limited to, eczema, psoriasis, acne, bacterial or fungal infections, vitiligo, contact dermatitis, or skin cancer (e.g., melanoma or basal cell carcinoma). "
                "Evaluate features such as color variations, lesion size and shape, border irregularities, asymmetry, surface texture, and the presence of scaling, oozing, or ulceration. "
                "Determine if the condition is likely to be infectious, inflammatory, allergic, autoimmune, or neoplastic in nature. "
                "Assign a severity level (mild, moderate, or severe). Recommend specific treatments such as topical steroids, antifungals, antibiotics, moisturizers, or other OTC or prescription-based therapies. "
                "State if diagnostic follow-up such as a dermatoscopy, skin biopsy, or dermatologist referral is appropriate.\n\n"

                "If the image shows physical injury or trauma:\n"
                "- Assess for swelling, discoloration, open wounds, abrasions, bleeding, deformity, or bruising. "
                "Indicate possible fracture, ligament damage, infection risk, or tissue necrosis based on visual indicators. "
                "Advise on first aid steps such as cold compression, wound cleaning, elevation, immobilization, or when to pursue urgent medical imaging (e.g., X-ray or CT scan). "
                "Categorize the injury as minor, moderate, or severe and recommend whether emergency care is necessary.\n\n"

                "If the image is related to the dental or oral cavity:\n"
                "- Evaluate for dental caries, plaque, calculus buildup, gum recession, gingivitis, bleeding, abscesses, or tooth misalignment. "
                "Examine gum color, tooth enamel, and oral hygiene indicators. "
                "Suggest suitable oral care practices (e.g., brushing, flossing, mouthwash), professional dental cleaning, or restorative dental procedures as needed. "
                "Recommend referral to a dentist or periodontist when significant pathology is evident.\n\n"

                "If the image is unclear, distorted, or not medically relevant:\n"
                "- Request a clearer, higher-resolution image that directly relates to a specific area of concern for accurate analysis.\n\n"

                "For every image:\n"
                "- Provide a concise, well-reasoned summary of your visual findings.\n"
                "- Suggest a likely condition name if applicable.\n"
                "- Clearly outline next steps for care, including treatment, diagnostic evaluation, or specialist referral.\n"
                "- Communicate in plain, unformatted text without Markdown, symbols, or emojis.\n"
                "- Maintain a professional, clinical tone appropriate for a healthcare environment."
        )

        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": vision_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                ]}
            ],
            temperature=0.7,
            max_tokens=1024,
        )

        result = completion.choices[0].message.content
        return jsonify({"answer": result})

    except Exception as e:
        print("Error during image analysis:", e)
        traceback.print_exc()  # This will print the full error stack trace
        return jsonify({"error": str(e)}), 500



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)