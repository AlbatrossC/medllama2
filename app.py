from flask import Flask, render_template, request, jsonify, session
import requests
import json
import os
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')

# Point to your ngrok tunnel that exposes server.py
SERVER_URL = "https://965bd6518c33.ngrok-free.app/chat"

# Get or create a unique session ID
def get_or_create_session_id():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        session['created_at'] = datetime.now().isoformat()
    return session['session_id']

# Render homepage and initialize session
@app.route("/")
def home():
    get_or_create_session_id()  # Initialize session
    return render_template("index.html")

# Handle user chat requests
@app.route("/chat", methods=["POST"])
def chat():
    user_msg = request.json.get("message", "")
    session_id = get_or_create_session_id()
    
    if not user_msg:
        return jsonify({"reply": "Please send a message."})
    
    try:
        # Send message directly to Ollama server
        response = requests.post(SERVER_URL, json={
            "message": user_msg,
            "session_id": session_id
        })
        
        if response.status_code == 200:
            data = response.json()
            reply_text = data.get("reply", "Sorry, I couldn't process that.")
        else:
            reply_text = f"Error: server returned {response.status_code}"
                
    except Exception as e:
        reply_text = f"Error connecting to the server: {e}"

    return jsonify({
        "reply": reply_text,
        "session_id": session_id
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)