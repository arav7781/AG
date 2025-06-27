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