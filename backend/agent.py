import logging
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime
from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.llm import function_tool
from livekit.agents.voice import Agent, AgentSession, RunContext
from livekit.plugins import deepgram, groq, silero, elevenlabs
from livekit.plugins.turn_detector.multilingual import MultilingualModel
import aiohttp
import asyncio
import re
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("nurse-assistant")
logger.setLevel(logging.INFO)


load_dotenv()


required_env_vars = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "GROQ_API_KEY"]
for var in required_env_vars:
    if not os.getenv(var):
        logger.error(f"Missing required environment variable: {var}")
        raise ValueError(f"Environment variable {var} is not set")


def init_db():
    conn = sqlite3.connect("hospital.db")
    cursor = conn.cursor()

    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            insurance_provider TEXT,
            insurance_number TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            specialty TEXT NOT NULL
        )
    """)

 
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            doctor_id INTEGER,
            specialty TEXT NOT NULL,
            preferred_date TEXT NOT NULL,
            preferred_time TEXT NOT NULL,
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            FOREIGN KEY (doctor_id) REFERENCES doctors(id)
        )
    """)


    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insurance_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            insurance_provider TEXT,
            insurance_number TEXT,
            claim_amount REAL,
            status TEXT,
            claim_date TEXT NOT NULL,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medicines (
            name TEXT PRIMARY KEY,
            description TEXT,
            side_effects TEXT
        )
    """)

    doctors_data = [
        ("Dr. Anil Sharma", "General Medicine"), ("Dr. Priya Gupta", "General Medicine"),
        ("Dr. Rajesh Kumar", "General Medicine"), ("Dr. Neha Patel", "General Medicine"),
        ("Dr. Sanjay Desai", "General Medicine"), ("Dr. Anjali Mehta", "General Medicine"),
        ("Dr. Vikram Singh", "General Medicine"), ("Dr. Pooja Shah", "General Medicine"),
        ("Dr. Rakesh Verma", "General Medicine"), ("Dr. Sunita Joshi", "General Medicine"),
        ("Dr. Amit Choudhary", "Orthopedics"), ("Dr. Shalini Kapoor", "Orthopedics"),
        ("Dr. Manoj Patil", "Orthopedics"), ("Dr. Kavita Rana", "Orthopedics"),
        ("Dr. Deepak Malhotra", "Orthopedics"), ("Dr. Meera Nair", "Orthopedics"),
        ("Dr. Rohan Kulkarni", "Orthopedics"), ("Dr. Swati Thakur", "Orthopedics"),
        ("Dr. Vinod Agarwal", "Orthopedics"), ("Dr. Lakshmi Iyer", "Orthopedics"),
        ("Dr. Sameer Khan", "Psychiatry"), ("Dr. Ritu Saxena", "Psychiatry"),
        ("Dr. Arjun Menon", "Psychiatry"), ("Dr. Nisha Varghese", "Psychiatry"),
        ("Dr. Siddharth Bose", "Psychiatry"), ("Dr. Ananya Das", "Psychiatry"),
        ("Dr. Karan Oberoi", "Psychiatry"), ("Dr. Preeti Malhotra", "Psychiatry"),
        ("Dr. Vivek Sharma", "Psychiatry"), ("Dr. Smriti Jain", "Psychiatry"),
        ("Dr. Rahul Mehra", "Cardiology"), ("Dr. Suman Gupta", "Cardiology"),
        ("Dr. Ashok Reddy", "Cardiology"), ("Dr. Divya Sharma", "Cardiology"),
        ("Dr. Kunal Desai", "Cardiology"), ("Dr. Rekha Pillai", "Cardiology"),
        ("Dr. Manish Thakur", "Cardiology"), ("Dr. Seema Kapoor", "Cardiology"),
        ("Dr. Ajay Bhatt", "Cardiology"), ("Dr. Lakshmi Nair", "Cardiology"),
        ("Dr. Vikrant Singh", "Neurology"), ("Dr. Anjali Rao", "Neurology"),
        ("Dr. Sanjay Gupta", "Neurology"), ("Dr. Priyanka Shah", "Neurology"),
        ("Dr. Rohit Kumar", "Neurology"), ("Dr. Neeta Patel", "Neurology"),
        ("Dr. Aravind Menon", "Neurology"), ("Dr. Shalini Desai", "Neurology"),
        ("Dr. Rajiv Malhotra", "Neurology"), ("Dr. Meena Iyer", "Neurology")
    ]
    cursor.executemany("INSERT OR IGNORE INTO doctors (name, specialty) VALUES (?, ?)", doctors_data)

    # Insert sample patient data
    patients_data = [
        ("Arav Saxena", "+919876543210", "arav.saxena@example.com", "Star Health", "SH123456"),
        ("Priya Sharma", "+918765432109", "priya.sharma@example.com", "HDFC Ergo", "HE789012"),
        ("Rahul Mehta", "+917654321098", "rahul.mehta@example.com", None, None)
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO patients (name, phone, email, insurance_provider, insurance_number) VALUES (?, ?, ?, ?, ?)",
        patients_data
    )

 
    cursor.execute("SELECT id FROM patients WHERE name = 'Arav Saxena'")
    arav_id = cursor.fetchone()[0]
    cursor.execute("SELECT id FROM doctors WHERE name = 'Dr. Anil Sharma' AND specialty = 'General Medicine'")
    doctor1_id = cursor.fetchone()[0]
    cursor.execute("SELECT id FROM doctors WHERE name = 'Dr. Amit Choudhary' AND specialty = 'Orthopedics'")
    doctor2_id = cursor.fetchone()[0]
    appointments_data = [
        (arav_id, doctor1_id, "General Medicine", "2025-06-15", "10:00"),
        (arav_id, doctor2_id, "Orthopedics", "2025-06-20", "14:30"),
        (2, doctor1_id, "General Medicine", "2025-06-16", "11:00"),  # Priya Sharma
        (3, doctor2_id, "Orthopedics", "2025-06-18", "09:30")  # Rahul Mehta
    ]
    cursor.executemany(
        "INSERT INTO appointments (patient_id, doctor_id, specialty, preferred_date, preferred_time) VALUES (?, ?, ?, ?, ?)",
        appointments_data
    )

   
    current_date = datetime.now().strftime("%Y-%m-%d")
    insurance_claims_data = [
        (arav_id, "Star Health", "SH123456", 5000.0, "Pending", current_date),
        (2, "HDFC Ergo", "HE789012", 7500.0, "Approved", current_date)
    ]
    cursor.executemany(
        "INSERT INTO insurance_claims (patient_id, insurance_provider, insurance_number, claim_amount, status, claim_date) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        insurance_claims_data
    )


    medicines_data = [
        ("Paracetamol", "Pain reliever and fever reducer", "Nausea, rash, liver damage (rare)"),
        ("Ibuprofen", "Nonsteroidal anti-inflammatory drug", "Stomach pain, dizziness, headache"),
        ("Aspirin", "Pain reliever and blood thinner", "Stomach upset, bleeding risk"),
        ("Amoxicillin", "Antibiotic for bacterial infections", "Diarrhea, rash, allergic reactions")
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO medicines (name, description, side_effects) VALUES (?, ?, ?)",
        medicines_data
    )

    conn.commit()
    conn.close()


PROMPTS = {
    "en": (
        "You are Riya, a compassionate nurse assistant at Symbiosis Hospital. Do not use emojis or special characters. "
        "Your role is to assist patients with health assessments, appointment scheduling, insurance queries, and medicine information. "
        "Use the following tools for specific purposes: "
        "- For patient identification (collecting name, phone, email, and optional insurance details), use {identify_patient} tool. "
        "- For assessing physical injuries, use {assess_injury} tool first. Ask detailed questions about the cause of the injury (e.g., accident, fall, sports), location, pain level (1-10), duration, swelling, bruising, or mobility issues to determine the appropriate specialty. "
        "- For assessing mental health (inquiring about mood, sleep patterns, stress levels, anxiety, or depression symptoms, e.g., frequency, severity), use {assess_mental_health} tool. "
        "Based on the assessment from {assess_injury} or {assess_mental_health}, query the database to suggest a relevant specialist doctor. "
        "- For booking appointments, use {book_appointment} tool to select a doctor from the database matching the specialty identified by {assess_injury} or {assess_mental_health}. Collect full name, phone number, email, preferred date/time, and ask for insurance policy details (provider and policy number). "
        "- For viewing appointments (using the patient's phone number), use {view_appointments} tool. "
        "- For updating appointments (using the booking ID and optional new date, time, or specialty), use {update_appointment} tool. "
        "- For canceling appointments (using the booking ID), use {cancel_appointment} tool. "
        "- For checking insurance eligibility (using the phone number), use {check_insurance} tool. "
        "- For submitting insurance claims (using the phone number and claim amount), use {submit_insurance_claim} tool. "
        "- For providing detailed medicine information (using the medicine name), use {get_medicine_info} tool. "
        "Always confirm actions with the patient before executing tools. Respond in English."
    ),
    "hi": (
    """
        आप तान्या हैं, सिम्बायोसिस अस्पताल की एक सहानुभूतिशील और सांस्कृतिक रूप से संवेदनशील नर्स सहायक। हमेशा गर्मजोशी, पेशेवरता और सहानुभूति से बात करें, बिना इमोजी या विशेष वर्णों का उपयोग किए। रोगी की बात को ध्यान से सुनें, उनकी चिंता को मान्यता दें, और सरल, समझने योग्य भाषा का उपयोग करें। चिकित्सीय शब्दावली तभी प्रयोग करें जब आप उसे स्पष्ट रूप से समझा सकें।  
        हर बातचीत की शुरुआत इस तरह करें कि रोगी को उनकी मुख्य समस्या को उनके शब्दों में बताने के लिए आमंत्रित करें। स्पष्टता के लिए खुले, गैर-आलोचनात्मक प्रश्न पूछें, जैसे लक्षण कब शुरू हुए, कितने समय से हैं, कितनी तीव्रता है, क्या कोई ट्रिगर हैं, जीवनशैली कारक आदि। उनकी बात को दोहराकर पुष्टि करें, जैसे: "लगता है कि आपको [लक्षण] पिछले [अवधि] से हो रहा है। क्या यह सही है?"  
        यदि लक्षण हल्के या मध्यम और स्वयं प्रबंधनीय हैं, तो उपयुक्त ओवर-द-काउंटर दवाएं, स्पष्ट खुराक निर्देश और व्यावहारिक घरेलू देखभाल के सुझाव दें, जो मरीज की ज़रूरतों और पसंद के अनुसार हों। यदि लक्षण गंभीर, तेजी से बिगड़ने वाले, या जोखिम सूचक हों (जैसे तेज दर्द, सांस की तकलीफ, मानसिक भ्रम), तो सरल भाषा में चिंता समझाएं और तुरंत अपॉइंटमेंट बुक करने या आपातकालीन सेवा से संपर्क करने की सलाह दें।  
        यह स्पष्ट करें कि मरीज का डेटा गोपनीय है, सिम्बायोसिस अस्पताल की निजता नीतियों के अंतर्गत सुरक्षित रूप से संभाला जाता है, और केवल उनकी सहमति से एकत्र किया जाता है। उनकी सहमति के बाद {identify_patient} टूल का उपयोग करके उनका नाम, फोन नंबर, ईमेल और वैकल्पिक बीमा विवरण एकत्र करें।  
        निम्नलिखित टूल्स का उपयोग विशेष उद्देश्यों के लिए करें, और यह सुनिश्चित करें कि कार्यवाही मरीज की जरूरतों के अनुसार हो:
        - मरीज की पहचान के लिए (नाम, फोन, ईमेल और वैकल्पिक बीमा विवरण), सहमति के बाद {identify_patient} टूल का उपयोग करें।  
        - शारीरिक चोटों के लिए, {assess_injury} टूल का उपयोग करें। चोट के कारण (जैसे दुर्घटना, गिरना, खेल), स्थान, दर्द स्तर (1–10), अवधि, सूजन, नीला पड़ना, गतिशीलता की समस्याएं या अन्य लक्षणों के बारे में विस्तार से और सहानुभूतिपूर्वक पूछें।  
        - मानसिक स्वास्थ्य चिंताओं के लिए, {assess_mental_health} टूल का उपयोग करें। मूड, नींद का पैटर्न, तनाव स्तर, चिंता, अवसाद जैसे लक्षणों के बारे में संवेदनशीलता से पूछें (जैसे उनकी आवृत्ति, तीव्रता, और दैनिक जीवन पर प्रभाव)।  
        - {assess_injury} या {assess_mental_health} के परिणाम के आधार पर, मरीज की पसंद (जैसे भाषा, डॉक्टर का लिंग, उपलब्धता) ध्यान में रखते हुए उपयुक्त विशेषज्ञ डॉक्टर सुझावित करें।  
        - अपॉइंटमेंट बुक करने के लिए, {book_appointment} टूल का उपयोग करें और संबंधित विशेषज्ञता वाले डॉक्टर का चयन करें। मरीज का पूरा नाम, फोन नंबर, ईमेल, पसंदीदा तिथि/समय, और बीमा विवरण (यदि उपलब्ध हो) एकत्र करें।  
        - अपॉइंटमेंट देखने के लिए, मरीज का फोन नंबर लेकर {view_appointments} टूल का उपयोग करें।  
        - अपॉइंटमेंट अपडेट करने के लिए, {update_appointment} टूल का उपयोग करें और बुकिंग ID के साथ नई तिथि, समय, या विशेषज्ञता (यदि कोई हो) दर्ज करें।  
        - अपॉइंटमेंट रद्द करने के लिए, {cancel_appointment} टूल का उपयोग करें और बुकिंग ID दर्ज करें।  
        - बीमा पात्रता जांचने के लिए, मरीज के फोन नंबर के साथ {check_insurance} टूल का उपयोग करें।  
        - बीमा दावा प्रस्तुत करने के लिए, मरीज का फोन नंबर और दावा राशि के साथ {submit_insurance_claim} टूल का उपयोग करें।  
        - दवा की जानकारी प्रदान करने के लिए, {get_medicine_info} टूल का उपयोग करें और दवा का नाम दर्ज करें।  
        किसी भी टूल का उपयोग करने से पहले, संक्षेप में बताएं कि आप क्या करने जा रहे हैं (जैसे: "मैं आपकी संपर्क जानकारी एकत्र करना चाहती हूँ ताकि हम आगे बढ़ सकें। क्या यह ठीक है?") और उनकी पुष्टि प्राप्त करें। कार्य पूरा करने के बाद, परिणाम का सारांश दें, अगले कदम बताएं, और कोई भी घरेलू देखभाल निर्देश स्पष्ट रूप से साझा करें।  
        यदि कोई आपात स्थिति सामने आती है (जैसे छाती में तेज दर्द, अत्यधिक रक्तस्राव, आत्महत्या की प्रवृत्ति), तो तुरंत मरीज को आपातकालीन सेवा (जैसे 108) से संपर्क करने के लिए कहें और ऑन-कॉल डॉक्टर को सूचित करें, यह भी बताएं कि उन्हें आगे क्या करना चाहिए।  
        हमेशा स्पष्ट, सहानुभूतिपूर्ण हिंदी में उत्तर दें, मरीज की सुरक्षा, निजता और सुविधा को प्राथमिकता दें। ज़रूरत अनुसार फॉलो-अप या अतिरिक्त संसाधन (जैसे अस्पताल की संपर्क जानकारी, सेल्फ-केयर गाइड्स) की पेशकश करें।
    """
),

    "mr": (
    """
        आपण तान्या आहात, सिम्बायोसिस रुग्णालयातील एक सहानुभूतीपूर्ण आणि सांस्कृतिकदृष्ट्या संवेदनशील परिचारिका सहाय्यक. संवादात नेहमीच ऊबदार, व्यावसायिक आणि सहानुभूतीपूर्ण स्वर वापरा. इमोजी किंवा विशेष वर्णांचा वापर टाळा. रुग्णांचे बोलणे काळजीपूर्वक ऐका, त्यांच्या तक्रारींची दखल घ्या आणि वैद्यकीय संज्ञा न वापरता सोप्या भाषेत संवाद साधा, आणि वापरल्यास स्पष्टपणे समजावून सांगा.  
        प्रत्येक संवादाची सुरुवात रुग्णाला त्यांच्या समस्या स्वतःच्या शब्दांत सांगण्यासाठी प्रोत्साहित करून करा. लक्षणे स्पष्ट समजून घेण्यासाठी खुले, समजूतदार प्रश्न विचारा – जसे की सुरूवात कधी झाली, किती काळ चालू आहे, तीव्रता, कोणते ट्रिगर्स आहेत, जीवनशैलीशी संबंधित बाबी. त्यांच्या म्हणण्याची पुनरावृत्ती करून खात्री करा, उदाहरणार्थ: "आपण सांगत आहात की तुम्हाला [लक्षण] मागील [कालावधी] पासून आहे. हे बरोबर आहे का?"  
        सौम्य ते मध्यम स्वरूपाची, स्वतः व्यवस्थापित करता येणारी लक्षणे असल्यास, योग्य ओवर-द-काउंटर औषधे, स्पष्ट डोस मार्गदर्शन, आणि व्यवहार्य घरगुती उपाय सुचवा – हे रुग्णाच्या गरजेनुसार व प्राधान्यानुसार असावेत. जोखीम वाढवणारी किंवा गंभीर लक्षणे आढळल्यास (उदा. तीव्र वेदना, अचानक बिघाड, धोक्याची चिन्हे जसे की श्वास घेण्यास त्रास, भ्रम), त्या लक्षणांचे गांभीर्य सोप्या भाषेत समजावून सांगा आणि त्वरीत अपॉइंटमेंट बुक करणे किंवा आपत्कालीन सेवांशी संपर्क साधण्याची शिफारस करा.  
        रुग्णाचा डेटा गोपनीय ठेवला जातो, सिम्बायोसिस रुग्णालयाच्या गोपनीयता धोरणांनुसार सुरक्षितपणे हाताळला जातो, आणि फक्त त्यांच्या स्पष्ट संमतीनंतर गोळा केला जातो, हे स्पष्ट करा. रुग्णाच्या संमतीनंतर {identify_patient} टूल वापरून त्यांचे नाव, फोन क्रमांक, ईमेल, आणि वैकल्पिक विमा तपशील गोळा करा.  
        खालील टूल्स विशिष्ट गरजांसाठी वापरा, आणि कृती रुग्णाच्या गरजेनुसार सुसंगत असणे आवश्यक आहे:
        - रुग्णाची ओळख पटवण्यासाठी (नाव, फोन, ईमेल आणि वैकल्पिक विमा तपशील), {identify_patient} टूल वापरा.  
        - शारीरिक दुखापतींसाठी, {assess_injury} टूल वापरा. दुखापतीचे कारण (उदा. अपघात, पडणे, खेळ), दुखापतीचे स्थान, वेदना पातळी (1–10), कालावधी, सूज, फुगलेपणा, हालचाल करण्यास अडचण – याबद्दल सविस्तर आणि सहानुभूतीपूर्वक विचारा.  
        - मानसिक आरोग्य समस्यांसाठी, {assess_mental_health} टूल वापरा. मनःस्थिती, झोपेचे पॅटर्न, ताणाची पातळी, चिंता, नैराश्य यासंबंधी संवेदनशीलतेने विचारा (वारंवारता, तीव्रता, दैनंदिन आयुष्यावर परिणाम).  
        - {assess_injury} किंवा {assess_mental_health} च्या परिणामावर आधारित, रुग्णाच्या प्राधान्यानुसार (उदा. भाषा, डॉक्टरचे लिंग, उपलब्ध वेळा) संबंधित तज्ञ डॉक्टर सुचवा.  
        - अपॉइंटमेंट बुक करण्यासाठी, {book_appointment} टूल वापरा आणि संबंधित तज्ञ निवडा. रुग्णाचे संपूर्ण नाव, फोन क्रमांक, ईमेल, पसंतीची तारीख/वेळ, आणि विमा तपशील (असल्यास) गोळा करा.  
        - अपॉइंटमेंट पाहण्यासाठी, {view_appointments} टूल वापरा आणि फोन नंबर द्या.  
        - अपॉइंटमेंट अपडेट करण्यासाठी, {update_appointment} टूल वापरा आणि बुकिंग ID सोबत नवीन तारीख, वेळ किंवा तज्ञ तपशील द्या.  
        - अपॉइंटमेंट रद्द करण्यासाठी, {cancel_appointment} टूल वापरा आणि बुकिंग ID द्या.  
        - विमा पात्रता तपासण्यासाठी, {check_insurance} टूल वापरा आणि फोन क्रमांक द्या.  
        - विमा दावा सादर करण्यासाठी, {submit_insurance_claim} टूल वापरा आणि फोन क्रमांक व दावा रक्कम द्या.  
        - औषधांविषयी माहिती देण्यासाठी, {get_medicine_info} टूल वापरा आणि औषधाचे नाव सांगा.  
        कोणतेही टूल वापरण्यापूर्वी, आपण काय कृती करणार आहात हे थोडक्यात समजावून सांगा (उदा. “मी आपला संपर्क तपशील घेऊ इच्छिते जेणेकरून पुढील प्रक्रिया सुरू करता येईल. हे ठीक आहे का?”) आणि रुग्णाची स्पष्ट संमती घ्या.  
        कृती पूर्ण केल्यानंतर, त्याचे परिणाम, पुढील पावले, आणि आवश्यक असल्यास घरगुती काळजी टिप्स स्पष्टपणे सांगा.  
        आपत्कालीन परिस्थिती आढळल्यास (उदा. छातीत तीव्र वेदना, रक्तस्त्राव, आत्महत्या करण्याचा विचार), लगेच रुग्णाला आपत्कालीन सेवा (उदा. 108) शी संपर्क साधण्यास सांगा आणि ऑन-कॉल डॉक्टरला माहिती द्या.  
        नेहमीच स्पष्ट, सहानुभूतीपूर्ण मराठीत उत्तर द्या आणि रुग्णाच्या सुरक्षिततेला, गोपनीयतेला आणि आरामाला प्राधान्य द्या. रुग्णाच्या गरजेनुसार फॉलो-अप किंवा अतिरिक्त साधने (उदा. रुग्णालयाची संपर्क माहिती, स्वकाळजी मार्गदर्शक) देण्याची तयारी ठेवा.
    """
),
    "pa": (
        "ਤੁਸੀਂ ਰਿਆ ਹੋ, ਸਿਮਬਾਇਓਸਿਸ ਹਸਪਤਾਲ ਦੀ ਇੱਕ ਦਇਆਲੁ ਨਰਸ ਸਹਾਇਕ। ਕੋਈ ਇਮੋਜੀ ਜਾਂ ਵਿਸ਼ੇਸ਼ ਅੱਖਰ ਨਾ ਵਰਤੋ। "
        "ਤੁਹਾਡਾ ਕੰਮ ਮਰੀਜ਼ਾਂ ਨੂੰ ਸਿਹਤ ਮੁਲਾਂਕਣ, ਮੁਲਾਕਾਤ ਬੁਕਿੰਗ, ਬੀਮਾ ਪੁੱਛਗਿੱਛ, ਅਤੇ ਦਵਾਈ ਜਾਣਕਾਰੀ ਵਿੱਚ ਮਦਦ ਕਰਨਾ ਹੈ। "
        "ਸਿਹਤ ਮੁਲਾਂਕਣ ਲਈ, ਮਰੀਜ਼ ਦੀ ਸਥਿਤੀ ਨੂੰ ਸਮਝਣ ਲਈ ਵਿਸਤ੍ਰਿਤ ਸਵਾਲ ਪੁੱਛੋ: "
        "- ਸਰੀਰਕ ਸੱਟਾਂ ਲਈ, ਸੱਟ ਦੀ ਜਗ੍ਹਾ, ਦਰਦ ਦਾ ਪੱਧਰ (1-10), ਅਵਧੀ, ਸੋਜ, ਜਖਮ, ਜਾਂ ਹਿਲਜੁਲ ਦੀਆਂ ਸਮੱਸਿਆਵਾਂ ਬਾਰੇ ਪੁੱਛੋ। "
        "- ਮਾਨਸਿਕ ਸਿਹਤ ਲਈ, ਮੂਡ, ਸੌਣ ਦੇ ਪੈਟਰਨ, ਤਣਾਅ ਪੱਧਰ, ਚਿੰਤਾ, ਜਾਂ ਡਿਪਰੈਸ਼ਨ ਦੇ ਲੱਛਣ (ਉਦਾਹਰਨ ਲਈ, ਬਾਰੰਬਾਰਤਾ, ਗੰਭੀਰਤਾ) ਬਾਰੇ ਪੁੱਛੋ। "
        "ਮੁਲਾਂਕਣ ਦੇ ਆਧਾਰ 'ਤੇ, ਸੰਬੰਧਿਤ ਮਾਹਰ ਦਾ ਸੁਝਾਅ ਦਿਓ ਅਤੇ ਉਸ ਵਿਸ਼ੇਸ਼ਤਾ ਲਈ 10 ਭਾਰਤੀ ਡਾਕਟਰਾਂ ਦੀ ਸੂਚੀ ਪ੍ਰਦਾਨ ਕਰੋ। "
        "ਮੁਲਾਕਾਤ ਬੁਕ ਕਰਦੇ ਸਮੇਂ, ਹਮੇਸ਼ਾ ਪੁੱਛੋ ਕਿ ਕੀ ਮਰੀਜ਼ ਕੋਲ ਬੀਮਾ ਪਾਲਿਸੀ ਹੈ ਅਤੇ ਵੇਰਵੇ (ਪ੍ਰਦਾਤਾ ਅਤੇ ਪਾਲਿਸੀ ਨੰਬਰ) ਮੰਗੋ। "
        "ਮਰੀਜ਼ ਦਾ ਪੂਰਾ ਨਾਮ, ਫੋਨ ਨੰਬਰ, ਈਮੇਲ, ਅਤੇ ਪਸੰਦੀਦਾ ਮਿਤੀ/ਸਮਾਂ ਇਕੱਠਾ ਕਰੋ। "
        "ਮੁਲਾਕਾਤਾਂ ਵੇਖਣ ਲਈ, ਮਰੀਜ਼ ਦਾ ਫੋਨ ਨੰਬਰ ਮੰਗੋ। "
        "ਮੁਲਾਕਾਤਾਂ ਨੂੰ ਅਪਡੇਟ ਜਾਂ ਰੱਦ ਕਰਨ ਲਈ, ਬੁਕਿੰਗ ਆਈਡੀ ਮੰਗੋ। "
        "ਬੀਮਾ ਦਾਅਵਿਆਂ ਲਈ, ਫੋਨ ਨੰਬਰ ਦੀ ਵਰਤੋਂ ਕਰਕੇ ਯੋਗਤਾ ਦੀ ਜਾਂਚ ਕਰੋ ਅਤੇ ਦਾਅਵੇ ਦੇ ਵੇਰਵੇ ਇਕੱਠੇ ਕਰੋ। "
        "ਦਵਾਈ ਪੁੱਛਗਿੱਛ ਲਈ, ਦਵਾਈ ਬਾਰੇ ਵਿਸਤ੍ਰਿਤ ਜਾਣਕਾਰੀ ਪ੍ਰਦਾਨ ਕਰੋ। "
        "ਹਮੇਸ਼ਾ ਮਰੀਜ਼ ਨਾਲ ਕਾਰਵਾਈਆਂ ਦੀ ਪੁਸ਼ਟੀ ਕਰੋ। ਜਵਾਬ ਪੰਜਾਬੀ ਵਿੱਚ ਦਿਓ।"
    ),
    "ta": (
        "நீங்கள் ரியா, சிம்பயோசிஸ் மருத்துவமனையின் கனிவான செவிலியர் உதவியாளர். எமோஜிகள் அல்லது சிறப்பு எழுத்துக்களைப் பயன்படுத்த வேண்டாம். "
        "உங்கள் பணி நோயாளிகளுக்கு உடல்நல மதிப்பீடு, சந்திப்பு முன்பதிவு, காப்பீட்டு வினவல்கள், மற்றும் மருந்து தகவல்களில் உதவுவது. "
        "உடல்நல மதிப்பீட்டிற்கு, நோயாளியின் நிலையைப் புரிந்துகொள்ள விரிவான கேள்விகளைக் கேளுங்கள்: "
        "- உடல் காயங்களுக்கு, காயத்தின் இடம், வலியின் அளவு (1-10), கால அளவு, வீக்கம், காயங்கள், அல்லது இயக்க சிக்கல்கள் பற்றி கேளுங்கள். "
        "- மனநலத்திற்கு, மனநிலை, தூக்க முறைகள், மன அழுத்த நிலைகள், பதட்டம், அல்லது மனச்சோர்வு அறிகுறிகள் (எ.கா., அதிர்வு, தீவிரம்) பற்றி கேளுங்கள். "
        "மதிப்பீட்டின் அடிப்படையில், தொடர்புடைய நிபுணரைப் பரிந்துரை செய்யுங்கள் மற்றும் அந்த நிபுணத்துவத்திற்கு 10 இந்திய மருத்துவர்களின் பட்டியலை வழங்கவும். "
        "சந்திப்பு முன்பதிவு செய்யும்போது, எப்போதும் நோயாளிக்கு காப்பீடு பாலிசி இருக்கிறதா என்று கேளுங்கள் மற்றும் விவரங்களை (வழங்குநர் மற்றும் பாலிசி எண்) கோருங்கள். "
        "நோயாளியின் முழு பெயர், கைபேசி எண், மின்னஞ்சல், மற்றும் விருப்பமான தேதி/நேரத்தை சேகரிக்கவும். "
        "சந்திப்புகளைப் பார்க்க, நோயாளியின் கைபேசி எண்ணைக் கேளுங்கள். "
        "சந்திப்புகளை புதுப்பிக்க அல்லது ரத்து செய்ய, புக்கிங் ஐடியைக் கேளுங்கள். "
        "காப்பீட்டு உரிமைகோரல்களுக்கு, கைபேசி எண்ணைப் பயன்படுத்தி தகுதியைச் சரிபார்க்கவும் மற்றும் உரிமைகோரல் விவரங்களைச் சேகரிக்கவும். "
        "மருந்து வினவல்களுக்கு, மருந்து பற்றிய விரிவான தகவல்களை வழங்கவும். "
        "எப்போதும் நோயாளியுடன் செயல்களை உறுதிப்படுத்தவும். பதில்கள் தமிழில் இருக்க வேண்டும்。"
    )
}

@dataclass
class UserData:
    """Class to store patient data during a call."""
    ctx: Optional[JobContext] = None
    language: str = "en"
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    patient_id: Optional[int] = None
    current_booking: Optional[dict] = None
    insurance_provider: Optional[str] = None
    insurance_number: Optional[str] = None

    def is_identified(self) -> bool:
        """Check if the patient is identified."""
        return self.name is not None and self.phone is not None and self.email is not None

    def reset(self) -> None:
        """Reset patient information."""
        self.name = None
        self.phone = None
        self.email = None
        self.patient_id = None
        self.current_booking = None
        self.insurance_provider = None
        self.insurance_number = None

    def summarize(self) -> str:
        """Return a summary of the patient data."""
        if self.is_identified():
            return f"Patient: {self.name} (Phone: {self.phone}, ID: {self.patient_id})"
        return "Patient not yet identified."

RunContext_T = RunContext[UserData]

class TriageAgent(Agent):
    def __init__(self, language: str = "en") -> None:
        super().__init__(
            instructions=PROMPTS.get(language, PROMPTS["en"]),
            llm=groq.LLM(model="gemma2-9b-it", api_key=""),
            tts=self._get_tts(language),
            stt=self._get_stt(language),
            vad=silero.VAD.load(),
            turn_detection=MultilingualModel(),
        )
        self.language = language

    def _get_tts(self, language: str):
        """Return the appropriate TTS factory for the language."""
        tts_factories = {
            "en": lambda: deepgram.TTS(model="aura-asteria-en",api_key=""),
            "hi": lambda: elevenlabs.TTS(
                voice_id="mActWQg9kibLro6Z2ouY",
                model="eleven_multilingual_v2",
                api_key="",
            ),
            "mr": lambda: elevenlabs.TTS(
                voice_id="mActWQg9kibLro6Z2ouY",
                model="eleven_multilingual_v2",
                api_key="",
            ),
            "pa": lambda: deepgram.TTS(model="aura-asteria-en"),
            "ta": lambda: elevenlabs.TTS(
                voice_id="mActWQg9kibLro6Z2ouY",
                model="eleven_multilingual_v2",
                api_key="",
            ),
        }
        return tts_factories.get(language, tts_factories["en"])()

    def _get_stt(self, language: str):
        """Return the appropriate STT factory for the language."""
        stt_factories = {
            "en": lambda: groq.STT(model="whisper-large-v3-turbo", language="en", api_key=""),
            "hi": lambda: groq.STT(model="whisper-large-v3-turbo", language="hi", api_key=""),
            "mr": lambda: groq.STT(model="whisper-large-v3-turbo", language="mr", api_key=""),
            "pa": lambda: groq.STT(model="whisper-large-v3-turbo", language="pa", api_key=""),
            "ta": lambda: groq.STT(model="whisper-large-v3-turbo", language="ta", api_key=""),
        }
        return stt_factories.get(language, stt_factories["en"])()

    async def on_enter(self) -> None:
        logger.info("Entering TriageAgent")
        userdata: UserData = self.session.userdata
        if userdata.ctx and userdata.ctx.room:
            try:
                await userdata.ctx.room.local_participant.set_attributes({"agent": "TriageAgent"})
            except Exception as e:
                logger.error(f"Failed to set participant attributes: {e}")

        chat_ctx = self.chat_ctx.copy()
        chat_ctx.add_message(
            role="system",
            content=f"You are Riya, the Triage Assistant. {userdata.summarize()}"
        )
        await self.update_chat_ctx(chat_ctx)
        await self.session.say(self.get_greeting())
        self.session.generate_reply()

    def get_greeting(self) -> str:
        """Return a language-specific greeting."""
        greetings = {
            "en": "Hello, I am Riya, a nurse assistant at Symbiosis Hospital. How can I assist you today?",
            "hi": "नमस्ते, मैं सिम्बायोसिस अस्पताल की नर्स सहायक रिया हूँ। मैं आपकी आज कैसे मदद कर सकती हूँ?",
            "mr": "नमस्कार, मी सिम्बायोसिस हॉस्पिटलची नर्स सहाय्यक रिया आहे. मी तुम्हाला आज कशी मदत करू शकते?",
            "pa": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਮੈਂ ਸਿਮਬਾਇਓਸਿਸ ਹਸਪਤਾਲ ਦੀ ਨਰਸ ਸਹਾਇਕ ਰੀਆ ਹਾਂ। ਮੈਂ ਅੱਜ ਤੁਹਾਡੀ ਕਿਵੇਂ ਮਦਦ ਕਰ ਸਕਦੀ ਹਾਂ?",
            "ta": "வணக்கம், நான் சிம்பயோசிஸ் மருத்துவமனையின் செவிலியர் உதவியாளர் ரியா. இன்று உங்களுக்கு எப்படி உதவ முடியும்?"
        }
        return greetings.get(self.language, greetings["en"])

    @function_tool
    async def identify_patient(self, name: str, phone: str, email: str, insurance_provider: Optional[str] = None, insurance_number: Optional[str] = None) -> str:
        """Identify a patient by their name, phone, email, and optional insurance details."""
        userdata: UserData = self.session.userdata
        if not re.match(r'^(?:\+91[-\s]?)?[6789]\d{9}$', phone):
            return "Please provide a valid phone number (e.g., +919876543210)."
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return "Please provide a valid email address (e.g., example@domain.com)."

        try:
            conn = sqlite3.connect("hospital.db")
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO patients (name, phone, email, insurance_provider, insurance_number) VALUES (?, ?, ?, ?, ?)",
                (name, phone, email, insurance_provider, insurance_number)
            )
            conn.commit()
            patient_id = cursor.lastrowid
            conn.close()

            userdata.name = name
            userdata.phone = phone
            userdata.email = email
            userdata.patient_id = patient_id
            userdata.insurance_provider = insurance_provider
            userdata.insurance_number = insurance_number

            return f"Thank you, {name}. I've registered your details."
        except sqlite3.IntegrityError:
            return "This phone number or email is already registered. Please provide unique details."

    @function_tool
    async def assess_injury(self, symptoms: str) -> str:
        """Assess physical injury symptoms and suggest a specialty."""
        symptom_map = {
            "pain in arm": "Orthopedics",
            "leg pain": "Orthopedics",
            "back pain": "Orthopedics",
            "sports injury": "Orthopedics",
            "fracture": "Orthopedics",
            "chest pain": "Cardiology",
            "heart": "Cardiology",
            "headache": "Neurology",
            "seizure": "Neurology",
            "fever": "General Medicine",
            "cough": "General Medicine",
            "fall": "Orthopedics",
            "accident": "Orthopedics"
        }
        specialty = None
        for symptom, spec in symptom_map.items():
            if symptom.lower() in symptoms.lower():
                specialty = spec
                break
        if not specialty:
            specialty = "General Medicine"

        conn = sqlite3.connect("hospital.db")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM doctors WHERE specialty = ? LIMIT 10", (specialty,))
        doctors = [row[0] for row in cursor.fetchall()]
        conn.close()

        doctor_list = ", ".join(doctors) if doctors else "No doctors available."
        return (
            f"Based on your symptoms ('{symptoms}'), I recommend seeing a {specialty} specialist. "
            f"Available doctors: {doctor_list}. Would you like to book an appointment?"
        )

    @function_tool
    async def assess_mental_health(self, symptoms: str) -> str:
        """Assess mental health symptoms and suggest a specialty."""
        if any(keyword in symptoms.lower() for keyword in ["anxiety", "depression", "stress", "mood", "sleep"]):
            specialty = "Psychiatry"
        else:
            specialty = "General Medicine"

        conn = sqlite3.connect("hospital.db")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM doctors WHERE specialty = ? LIMIT 10", (specialty,))
        doctors = [row[0] for row in cursor.fetchall()]
        conn.close()

        doctor_list = ", ".join(doctors) if doctors else "No doctors available."
        return (
            f"Based on your symptoms ('{symptoms}'), I recommend seeing a {specialty} specialist. "
            f"Available doctors: {doctor_list}. Would you like to book an appointment?"
        )

    @function_tool
    async def book_appointment(self, specialty: str, preferred_date: str, preferred_time: str, insurance_provider: Optional[str] = None, insurance_number: Optional[str] = None) -> str:
        """Book an appointment for a patient with a specific specialty."""
        userdata: UserData = self.session.userdata
        if not userdata.is_identified():
            return "Please identify yourself first using name, phone, and email."

        try:
            datetime.strptime(preferred_date, "%Y-%m-%d")
            datetime.strptime(preferred_time, "%H:%M")
        except ValueError:
            return "Please provide date in YYYY-MM-DD format and time in HH:MM format."

        conn = sqlite3.connect("hospital.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM doctors WHERE specialty = ? LIMIT 1", (specialty,))
        doctor = cursor.fetchone()
        if not doctor:
            conn.close()
            return f"Specialty '{specialty}' is not available. Please choose another specialty."

        doctor_id, doctor_name = doctor

        # Update insurance details if provided
        if insurance_provider and insurance_number:
            cursor.execute(
                "UPDATE patients SET insurance_provider = ?, insurance_number = ? WHERE id = ?",
                (insurance_provider, insurance_number, userdata.patient_id)
            )
            conn.commit()
            userdata.insurance_provider = insurance_provider
            userdata.insurance_number = insurance_number

        try:
            cursor.execute(
                "INSERT INTO appointments (patient_id, doctor_id, specialty, preferred_date, preferred_time) "
                "VALUES (?, ?, ?, ?, ?)",
                (userdata.patient_id, doctor_id, specialty, preferred_date, preferred_time)
            )
            conn.commit()
            booking_id = cursor.lastrowid
        except sqlite3.Error as e:
            conn.close()
            return f"Failed to book appointment: {str(e)}"

        conn.close()

        email_sent = await self._send_confirmation_email(userdata.email, booking_id, specialty, preferred_date, preferred_time)
        userdata.current_booking = None

        if email_sent:
            return (
                f"Great! Your appointment (#{booking_id}) has been confirmed for {preferred_date} at {preferred_time} "
                f"with {doctor_name} ({specialty}). You'll receive a confirmation email."
            )
        return (
            f"Great! Your appointment (#{booking_id}) has been confirmed for {preferred_date} at {preferred_time} "
            f"with {doctor_name} ({specialty}). However, there was an issue sending the confirmation email. "
            f"Please check your email later or contact us if you don’t receive it."
        )

    @function_tool
    async def view_appointments(self, phone: str) -> str:
        """View upcoming appointments for a patient by phone number."""
        conn = sqlite3.connect("hospital.db")
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.id, d.name, a.specialty, a.preferred_date, a.preferred_time 
            FROM appointments a 
            JOIN patients p ON a.patient_id = p.id 
            JOIN doctors d ON a.doctor_id = d.id 
            WHERE p.phone = ?
            """,
            (phone,)
        )
        bookings = cursor.fetchall()
        conn.close()

        if not bookings:
            return "You have no upcoming appointments."
        appointment_list = "\n".join([
            f"- Appointment #{b[0]} with {b[1]} ({b[2]}) on {b[3]} at {b[4]}" for b in bookings
        ])
        return f"You have the following upcoming appointments:\n{appointment_list}"

    @function_tool
    async def update_appointment(self, booking_id: int, new_date: Optional[str] = None, new_time: Optional[str] = None, new_specialty: Optional[str] = None) -> str:
        """Update an existing appointment by booking ID."""
        conn = sqlite3.connect("hospital.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT patient_id, doctor_id, specialty, preferred_date, preferred_time FROM appointments WHERE id = ?",
            (booking_id,)
        )
        booking = cursor.fetchone()
        if not booking:
            conn.close()
            return "Appointment not found. Please check the booking ID."

        patient_id, current_doctor_id, current_specialty, current_date, current_time = booking
        new_specialty = new_specialty or current_specialty
        new_date = new_date or current_date
        new_time = new_time or current_time

        cursor.execute("SELECT id FROM doctors WHERE specialty = ? LIMIT 1", (new_specialty,))
        doctor = cursor.fetchone()
        if not doctor:
            conn.close()
            return f"Specialty '{new_specialty}' is not available. Please choose another specialty."

        new_doctor_id = doctor[0]

        try:
            datetime.strptime(new_date, "%Y-%m-%d")
            datetime.strptime(new_time, "%H:%M")
        except ValueError:
            conn.close()
            return "Please provide date in YYYY-MM-DD format and time in HH:MM format."

        cursor.execute(
            "UPDATE appointments SET doctor_id = ?, specialty = ?, preferred_date = ?, preferred_time = ? WHERE id = ?",
            (new_doctor_id, new_specialty, new_date, new_time, booking_id)
        )
        conn.commit()
        conn.close()
        return "Appointment updated successfully."

    @function_tool
    async def cancel_appointment(self, booking_id: int) -> str:
        """Cancel an appointment by booking ID."""
        conn = sqlite3.connect("hospital.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM appointments WHERE id = ?", (booking_id,))
        if cursor.rowcount == 0:
            conn.close()
            return "Appointment not found. Please check the booking ID."
        conn.commit()
        conn.close()
        return "Appointment canceled successfully."

    @function_tool
    async def check_insurance(self, phone: str) -> str:
        """Check if a patient has health insurance by phone number."""
        conn = sqlite3.connect("hospital.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, insurance_provider, insurance_number FROM patients WHERE phone = ?", (phone,))
        patient = cursor.fetchone()
        conn.close()
        if not patient:
            return "No patient found with this phone number."
        patient_id, insurance_provider, insurance_number = patient
        if insurance_provider and insurance_number:
            return f"Insurance found: Provider={insurance_provider}, Policy Number={insurance_number}."
        return "No insurance details found for this patient."

    @function_tool
    async def submit_insurance_claim(self, phone: str, claim_amount: float) -> str:
        """Submit an insurance claim for a patient."""
        conn = sqlite3.connect("hospital.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, insurance_provider, insurance_number FROM patients WHERE phone = ?", (phone,))
        patient = cursor.fetchone()
        if not patient:
            conn.close()
            return "No patient found with this phone number."

        patient_id, insurance_provider, insurance_number = patient
        if not insurance_provider or not insurance_number:
            conn.close()
            return "No insurance details found. Please provide insurance information first."

        current_date = datetime.now().strftime("%Y-%m-%d")
        cursor.execute(
            "INSERT INTO insurance_claims (patient_id, insurance_provider, insurance_number, claim_amount, status, claim_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (patient_id, insurance_provider, insurance_number, claim_amount, "Pending", current_date)
        )
        conn.commit()
        claim_id = cursor.lastrowid
        conn.close()
        return f"Insurance claim #{claim_id} submitted for {claim_amount} INR. Status: Pending."

    @function_tool
    async def get_medicine_info(self, name: str) -> str:
        """Get information about a specific medicine."""
        conn = sqlite3.connect("hospital.db")
        cursor = conn.cursor()
        cursor.execute("SELECT name, description, side_effects FROM medicines WHERE name = ?", (name,))
        medicine = cursor.fetchone()
        conn.close()

        if not medicine:
            return f"No information found for medicine: {name}"
        return (
            f"Medicine: {medicine[0]}\n"
            f"Description: {medicine[1]}\n"
            f"Side Effects: {medicine[2]}"
        )

    async def _send_confirmation_email(self, patient_email: str, booking_id: int, specialty: str, preferred_date: str, preferred_time: str) -> bool:
        """Send a confirmation email for the appointment."""
        try:
            email_sender = os.getenv("EMAIL_SENDER")
            email_password = os.getenv("EMAIL_PASSWORD")
            if not email_sender or not email_password:
                logger.error("Email credentials are missing in the environment variables.")
                return False

            msg = EmailMessage()
            msg['Subject'] = "Appointment Confirmation"
            msg['From'] = email_sender
            msg['To'] = patient_email
            msg.set_content(
                f"Hello {self.session.userdata.name}, your appointment (#{booking_id}) is scheduled for "
                f"{preferred_date} at {preferred_time} with a {specialty} specialist."
            )

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(email_sender, email_password)
                server.send_message(msg)

            logger.info(f"Confirmation email sent to {patient_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {patient_email}: {e}")
            return False


async def entrypoint(ctx: JobContext):
    logger.info(f"Attempting to connect to LiveKit server at {os.getenv('LIVEKIT_URL')}")
    try:
        await ctx.connect()
    except Exception as e:
        logger.error(f"Failed to connect to LiveKit server: {e}")
        raise

    # Wait for a participant to join
    while len(ctx.room.remote_participants) < 1:
        await asyncio.sleep(0.1)

    user_participant = next(iter(ctx.room.remote_participants.values()))
    language = user_participant.metadata or "en"

    logger.info(f"Job {ctx.job.id} received for language: {language}")

    # Initialize user data with context and language
    userdata = UserData(ctx=ctx, language=language)

    # Create triage agent
    triage_agent = TriageAgent(language=language)

    # Create session with userdata
    session = AgentSession[UserData](userdata=userdata)

    # Start the session with the triage agent
    try:
        await session.start(
            agent=triage_agent,
            room=ctx.room,
        )
    except Exception as e:
        logger.error(f"Failed to start agent session: {e}")
        raise

    # Placeholder for metrics collection
    async def log_usage():
        logger.info(f"Job {ctx.job.id}: Metrics collection placeholder")

    ctx.add_shutdown_callback(log_usage)
    logger.info(f"Job {ctx.job.id}: Shutdown callback added")

if __name__ == "__main__":
    init_db()
    worker_options = WorkerOptions(
        entrypoint_fnc=entrypoint,
       
    )
    cli.run_app(worker_options)

