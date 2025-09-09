from flask import Flask, render_template, request, jsonify
import requests
import json
import os

app = Flask(__name__)

# Ngrok endpoint for your Ollama handler
NGROK_URL = "https://ce57dee50b07.ngrok-free.app/whatsapp"

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_msg = request.json.get("message", "")

    # Send the message to the Ollama endpoint via ngrok
    payload = {
        "Body": user_msg,
        "From": "+10000000000"  # Dummy number
    }
    response = requests.post(NGROK_URL, data=payload)

    # Parse Twilio XML response
    reply_text = "Sorry, I couldn't process that."
    try:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(response.text)
        msg = root.find("Message")
        if msg is not None:
            reply_text = msg.text
    except:
        pass

    return jsonify({"reply": reply_text})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))  # Use Vercel's port or 8000 locally
    app.run(host="0.0.0.0", port=port, debug=True)
