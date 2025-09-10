from flask import Flask, render_template, request, jsonify, session
import requests
import json
import os
from deep_translator import GoogleTranslator
import uuid
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')  # Change this in production

# Point to your ngrok tunnel that exposes server.py
SERVER_URL = "https://dd57d4e4fb6c.ngrok-free.app/chat"

# Language detection and translation setup
SUPPORTED_LANGUAGES = {
    'en': 'english',
    'hi': 'hindi', 
    'mr': 'marathi'
}

def detect_language(text):
    """
    Simple language detection based on script/characters
    Returns language code ('en', 'hi', 'mr', 'or')
    """
    # Check for Devanagari script (Hindi/Marathi)
    devanagari_chars = any('\u0900' <= char <= '\u097F' for char in text)
    # Check for Odia script
    odia_chars = any('\u0B00' <= char <= '\u0B7F' for char in text)
    
    if odia_chars:
        return 'or'  # Odia detected
    elif devanagari_chars:
        # Simple heuristic: check for Marathi-specific words/patterns
        marathi_indicators = ['आहे', 'मी', 'तू', 'आम्ही', 'तुम्ही', 'ते', 'त्या', 'करतो', 'करते']
        if any(word in text for word in marathi_indicators):
            return 'mr'
        else:
            return 'hi'  # Default to Hindi for Devanagari
    else:
        return 'en'  # Default to English for Latin script

def translate_text(text, target_lang, source_lang='auto'):
    """
    Translate text using Google Translator
    """
    try:
        if source_lang == target_lang or target_lang == 'en':
            return text
        
        translator = GoogleTranslator(source=source_lang, target=target_lang)
        translated = translator.translate(text)
        return translated
    except Exception as e:
        print(f"Translation error: {e}")
        return text  # Return original text if translation fails

def get_or_create_session_id():
    """
    Get or create a unique session ID for tracking user language preference
    """
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        session['created_at'] = datetime.now().isoformat()
    return session['session_id']

@app.route("/")
def home():
    get_or_create_session_id()  # Initialize session
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_msg = request.json.get("message", "")
    session_id = get_or_create_session_id()
    
    if not user_msg:
        return jsonify({"reply": "Please send a message."})
    
    try:
        # Step 1: Detect user input language
        detected_lang = detect_language(user_msg)
        
        # Step 2: Store user's preferred language in session
        session['user_language'] = detected_lang
        session.permanent = True  # Make session persistent
        app.permanent_session_lifetime = timedelta(hours=24)
        
        # Step 3: Translate user message to English if needed
        english_msg = user_msg
        if detected_lang != 'en':
            english_msg = translate_text(user_msg, 'en', detected_lang)
        
        # Step 4: Send English message to Ollama server
        response = requests.post(SERVER_URL, json={
            "message": english_msg,
            "session_id": session_id  # Pass session ID for context
        })
        
        if response.status_code == 200:
            data = response.json()
            english_reply = data.get("reply", "Sorry, I couldn't process that.")
            
            # Step 5: Translate response back to user's language
            if detected_lang != 'en':
                translated_reply = translate_text(english_reply, detected_lang, 'en')
                reply_text = translated_reply
            else:
                reply_text = english_reply
                
        else:
            error_msg = f"Error: server returned {response.status_code}"
            # Translate error message if needed
            if detected_lang != 'en':
                reply_text = translate_text(error_msg, detected_lang, 'en')
            else:
                reply_text = error_msg
                
    except Exception as e:
        error_msg = f"Error connecting to the server: {e}"
        detected_lang = session.get('user_language', 'en')
        
        # Translate error message if needed
        if detected_lang != 'en':
            reply_text = translate_text(error_msg, detected_lang, 'en')
        else:
            reply_text = error_msg

    return jsonify({
        "reply": reply_text,
        "detected_language": SUPPORTED_LANGUAGES.get(detected_lang, 'english'),
        "session_id": session_id
    })

@app.route("/set_language", methods=["POST"])
def set_language():
    """
    Allow manual language setting by user
    """
    lang_code = request.json.get("language", "en")
    if lang_code in SUPPORTED_LANGUAGES:
        session['user_language'] = lang_code
        return jsonify({
            "status": "success",
            "language": SUPPORTED_LANGUAGES[lang_code]
        })
    else:
        return jsonify({
            "status": "error",
            "message": "Unsupported language"
        }), 400

@app.route("/get_language")
def get_language():
    """
    Get current session language
    """
    current_lang = session.get('user_language', 'en')
    return jsonify({
        "language_code": current_lang,
        "language_name": SUPPORTED_LANGUAGES[current_lang]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)