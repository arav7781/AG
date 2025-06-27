from flask import Flask, request, Response, send_from_directory, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
from groq import Groq
import os
import logging
from datetime import datetime
import requests
import base64
from requests.auth import HTTPBasicAuth
from google.cloud import texttospeech
import json

# Load environment variables
load_dotenv()

# Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
GROQ_API_KEY =  ""
ULTRAVOX_API_KEY =  ""

# Initialize clients
groq_client = Groq(api_key=GROQ_API_KEY)

# Initialize Flask app
app = Flask(__name__)
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("whatsapp_bot.log"),
        logging.StreamHandler()
    ]
)

ULTRAVOX_API_URL = 'https://api.ultravox.ai/api/calls'


prompt_file_path = os.path.join(os.path.dirname(__file__), "prompt1.md")
with open(prompt_file_path, "r") as file:
    PROMPT_TEMPLATE = file.read()



with open("prompt1.md", "r") as file:
    TEXT_PROMPT = file.read()


with open("vision_prompt.md", "r") as file:
    VISION_PROMPT = file.read()

# Ultravox configuration
ULTRAVOX_CALL_CONFIG = {
    "model": "fixie-ai/ultravox",
    "voice": "Riya-Rao-English-Indian",
    "temperature": 0.3,
    "firstSpeaker": "FIRST_SPEAKER_AGENT",
    "medium": {"twilio": {}}
}

# Ensure directories exist
for directory in ['audio_files', 'injury_reports']:
    if not os.path.exists(directory):
        os.makedirs(directory)

# Conversation state
conversation_state = {}

def create_ultravox_call(config):
    """Create Ultravox call and get join URL"""
    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': ULTRAVOX_API_KEY
    }
    response = requests.post(ULTRAVOX_API_URL, json=config, headers=headers)
    response.raise_for_status()
    return response.json()

def fetch_twilio_media(media_url, return_base64=False):
    """Fetch media from Twilio and return as raw bytes or Base64-encoded string."""
    try:
        response = requests.get(
            media_url,
            auth=HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=15
        )
        response.raise_for_status()
        if return_base64:
            content_type = response.headers.get('content-type', 'image/jpeg')
            image_data = base64.b64encode(response.content).decode('utf-8')
            return f"data:{content_type};base64,{image_data}"
        else:
            return response.content
    except Exception as e:
        logger.error(f"Failed to fetch media: {str(e)}")
        return None

def is_injury_related(image_description, user_message=""):
    """Determine if an image or message is injury-related using AI"""
    injury_keywords = [
        'wound', 'cut', 'bruise', 'burn', 'scrape', 'scratch', 'injury', 'hurt', 'pain',
        'bleeding', 'swollen', 'sprain', 'fracture', 'broken', 'dislocated', 'torn',
        'rash', 'bite', 'sting', 'laceration', 'abrasion', 'contusion', 'trauma',
        'accident', 'fall', 'hit', 'injured', 'medical', 'first aid', 'emergency'
    ]
    
    text_to_check = f"{image_description} {user_message}".lower()
    return any(keyword in text_to_check for keyword in injury_keywords)

def analyze_injury_with_streaming(messages):
    """Analyze injury using Groq streaming API"""
    try:
        completion = groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=messages,
            temperature=0.3,
            max_completion_tokens=1024,
            top_p=0.8,
            stream=True,
            stop=None,
        )
        
        response_text = ""
        for chunk in completion:
            if chunk.choices[0].delta.content:
                response_text += chunk.choices[0].delta.content
        
        return response_text.strip()
    except Exception as e:
        logger.error(f"Streaming analysis failed: {str(e)}")
        return "Sorry, I couldn't analyze the image at this time. Please try again or consult a medical professional."

def save_injury_report(sender_number, user_input, ai_response, image_data=None):
    """Save injury consultation report"""
    try:
        report = {
            'timestamp': datetime.now().isoformat(),
            'sender': sender_number,
            'user_input': user_input,
            'ai_response': ai_response,
            'has_image': image_data is not None
        }
        
        filename = f"injury_reports/report_{sender_number.replace(':', '_')}_{datetime.now().timestamp()}.json"
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Injury report saved: {filename}")
        return filename
    except Exception as e:
        logger.error(f"Failed to save injury report: {str(e)}")
        return None

def synthesize_text(text, language_code="en-US", voice_name="en-US-Wavenet-D", output_file="output.mp3"):
    """Synthesize text to speech using Google Cloud TTS"""
    try:
        # Uncomment when Google Cloud TTS is properly configured
        # input_text = texttospeech.SynthesisInput(text=text)
        # voice = texttospeech.VoiceSelectionParams(
        #     language_code=language_code,
        #     name=voice_name
        # )
        # audio_config = texttospeech.AudioConfig(
        #     audio_encoding=texttospeech.AudioEncoding.MP3
        # )
        # response = tts_client.synthesize_speech(
        #     input=input_text,
        #     voice=voice,
        #     audio_config=audio_config
        # )
        # with open(os.path.join('audio_files', output_file), "wb") as out:
        #     out.write(response.audio_content)
        # logger.info(f"Audio content written to audio_files/{output_file}")
        # return True
        
        # Placeholder for TTS functionality
        logger.info("TTS functionality not configured")
        return False
    except Exception as e:
        logger.error(f"TTS synthesis failed: {str(e)}")
        return False

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    """Handle incoming WhatsApp messages with enhanced injury analysis"""
    try:
        incoming_msg = request.form.get('Body', '').strip()
        sender_number = request.form.get('From', '')
        media_url = request.form.get('MediaUrl0')
        media_content_type = request.form.get('MediaContentType0')

        logger.info(f"Incoming message from {sender_number}: {incoming_msg}, Media: {media_url}")
        
        # Initialize conversation state
        if sender_number not in conversation_state:
            conversation_state[sender_number] = {
                'history': [],
                'last_interaction': datetime.now().isoformat(),
                'language': 'en',
                'injury_consultations': 0
            }

        # Handle reset command
        if incoming_msg.lower() in ["start over", "reset", "new consultation"]:
            conversation_state[sender_number]['history'] = []
            resp = MessagingResponse()
            resp.message("Conversation reset. Hello! I'm Tanya, your medical assistant at Symbiosis Hospital. I can help analyze injuries from images or answer medical questions. How can I assist you today?")
            return Response(str(resp), mimetype="application/xml")

        # Language handling
        language_map = {
            "en": ("en-US", "en-US-Wavenet-D"),
            "hi": ("hi-IN", "hi-IN-Wavenet-A"),
            "mr": ("mr-IN", "mr-IN-Wavenet-A")
        }
        for lang, (lang_code, voice_name) in language_map.items():
            if f"use {lang}" in incoming_msg.lower():
                conversation_state[sender_number]['language'] = lang
                incoming_msg = incoming_msg.replace(f"use {lang}", "").strip()
                logger.info(f"Language set to {lang} for {sender_number}")

        # Audio response handling
        audio_keywords = ["send as audio", "voice response", "audio reply"]
        request_audio = any(keyword in incoming_msg.lower() for keyword in audio_keywords)
        if request_audio:
            for keyword in audio_keywords:
                incoming_msg = incoming_msg.replace(keyword, "").strip()

        # Media processing
        has_image = media_url and media_content_type and media_content_type.startswith('image/')
        has_audio = media_url and media_content_type and media_content_type.startswith('audio/')

        # Process different media types
        if has_image:
            base64_image = fetch_twilio_media(media_url, return_base64=True)
            if not base64_image:
                user_content = "Sorry, I couldn't access the image. Please try sending it again."
                user_input_for_history = "Sent an image (failed to access)"
            else:
                user_content = []
                if incoming_msg:
                    user_content.append({"type": "text", "text": incoming_msg})
                    user_input_for_history = incoming_msg
                else:
                    user_input_for_history = "Sent an image for analysis"
                user_content.append({"type": "image_url", "image_url": {"url": base64_image}})

        elif has_audio:
            audio_data = fetch_twilio_media(media_url, return_base64=False)
            if audio_data:
                audio_file_path = f"audio_files/temp_audio_{datetime.now().timestamp()}.wav"
                with open(audio_file_path, "wb") as f:
                    f.write(audio_data)
                try:
                    with open(audio_file_path, "rb") as audio_file:
                        transcription = groq_client.audio.transcriptions.create(
                            model="whisper-large-v3-turbo",
                            file=audio_file
                        )
                    transcribed_text = transcription.text
                    user_content = transcribed_text
                    user_input_for_history = transcribed_text
                except Exception as e:
                    logger.error(f"Transcription failed: {str(e)}")
                    user_content = "Sorry, I couldn't transcribe the audio. Please try sending it again."
                    user_input_for_history = "Sent an audio message (transcription failed)"
                finally:
                    try:
                        if os.path.exists(audio_file_path):
                            os.remove(audio_file_path)
                    except PermissionError as e:
                        logger.warning(f"Could not delete {audio_file_path}: {str(e)}")
            else:
                user_content = "Sorry, I couldn't access the audio. Please try sending it again."
                user_input_for_history = "Sent an audio message (failed to access)"

        elif media_url:
            user_content = "Sorry, I can only process text, images, or audio messages."
            user_input_for_history = "Sent an unsupported media type"
        else:
            user_content = incoming_msg
            user_input_for_history = incoming_msg


        is_injury = has_image or is_injury_related(str(user_content), incoming_msg)
        
      
        if is_injury:
            system_prompt = VISION_PROMPT
            conversation_state[sender_number]['injury_consultations'] += 1
            logger.info(f"Injury consultation #{conversation_state[sender_number]['injury_consultations']} for {sender_number}")
        else:
            system_prompt = TEXT_PROMPT if not has_image else VISION_PROMPT

      
        messages = [{"role": "system", "content": system_prompt}]
        
     
        for turn in conversation_state[sender_number]['history']:
            messages.append({"role": "user", "content": turn['user']})
            messages.append({"role": "assistant", "content": str(turn['assistant'])})

        # Add current message
        messages.append({"role": "user", "content": user_content})

 
        if is_injury and has_image:
            llm_response = analyze_injury_with_streaming(messages)
       
            save_injury_report(sender_number, user_input_for_history, llm_response, base64_image)
        else:
            chat_completion = groq_client.chat.completions.create(
                messages=messages,
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                temperature=0.7,
                max_tokens=500
            )
            llm_response = chat_completion.choices[0].message.content.strip()

        logger.info(f"LLM Response: {llm_response}")

        # Update conversation history
        conversation_state[sender_number]['history'].append({
            'user': user_input_for_history,
            'assistant': llm_response
        })
        
        # Keep only last 5 exchanges
        if len(conversation_state[sender_number]['history']) > 5:
            conversation_state[sender_number]['history'] = conversation_state[sender_number]['history'][-5:]
        
        conversation_state[sender_number]['last_interaction'] = datetime.now().isoformat()

        # Prepare response
        resp = MessagingResponse()
        
        if request_audio:
            # Generate audio response
            audio_filename = f"response_{sender_number.replace(':', '_')}_{datetime.now().timestamp()}.mp3"
            lang = conversation_state[sender_number]['language']
            lang_code, voice_name = language_map.get(lang, ("en-US", "en-US-Wavenet-D"))
            
            success = synthesize_text(
                text=llm_response,
                language_code=lang_code,
                voice_name=voice_name,
                output_file=audio_filename
            )
            
            if success:
                base_url = os.getenv("BASE_URL", "http://localhost:5000")
                audio_url = f"{base_url}/audio/{audio_filename}"
                msg = resp.message()
                msg.body("Here is your audio response:")
                msg.media(audio_url)
                logger.info(f"Audio response generated: {audio_url}")
            else:
                resp.message("Sorry, I couldn't generate the audio response. Here's the text instead:\n" + llm_response)
        else:
            # Add injury consultation disclaimer if applicable
            if is_injury:
                disclaimer = "\n\n⚠️ IMPORTANT: Visit Our Hospital for Proper diagnosis."
                resp.message(llm_response + disclaimer)
            else:
                resp.message(llm_response)

        logger.info(f"Sending TwiML: {str(resp)}")
        return Response(str(resp), mimetype="application/xml")

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        resp = MessagingResponse()
        resp.message("Sorry, I encountered an issue processing your request. Please try again or contact Symbiosis Hospital directly for urgent medical concerns or call +151-522-5303.")
        return Response(str(resp), mimetype="application/xml")

@app.route('/audio/<filename>')
def serve_audio(filename):
    """Serve audio files from the audio_files directory"""
    return send_from_directory('audio_files', filename)

@app.route("/incoming", methods=['POST'])
def handle_incoming_call():
    """Handle incoming voice calls"""
    print("Incoming call received")
    try:
        caller_number = request.form.get('From')
        print(f"Incoming call from: {caller_number}")

        dynamic_system_prompt = PROMPT_TEMPLATE.format(caller_number=caller_number)

        call_config = ULTRAVOX_CALL_CONFIG.copy()
        call_config["systemPrompt"] = dynamic_system_prompt

        call_response = create_ultravox_call(call_config)
        join_url = call_response.get('joinUrl')

        twiml = VoiceResponse()
        connect = twiml.connect()
        connect.stream(url=join_url, name='ultravox')

        return Response(str(twiml), content_type='text/xml')

    except Exception as e:
        print(f"Error handling incoming call: {e}")
        twiml = VoiceResponse()
        twiml.say('Sorry, there was an error connecting your call.')
        return Response(str(twiml), content_type='text/xml')

@app.route("/injury-stats", methods=['GET'])
def injury_stats():
    """Get injury consultation statistics"""
    try:
        total_consultations = 0
        active_users = 0
        
        for user_id, state in conversation_state.items():
            if state.get('injury_consultations', 0) > 0:
                total_consultations += state['injury_consultations']
                active_users += 1
        
        return jsonify({
            'total_injury_consultations': total_consultations,
            'active_users_with_injuries': active_users,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting injury stats: {str(e)}")
        return jsonify({'error': 'Unable to retrieve statistics'}), 500

@app.route("/health", methods=['GET'])
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "features": ["injury_analysis", "streaming_ai", "multi_language", "audio_support"]
    }, 200

if __name__ == "__main__":
    logger.info("Starting Enhanced Medical Assistant with Injury Analysis")
    app.run(host="0.0.0.0", port=5000, debug=False)