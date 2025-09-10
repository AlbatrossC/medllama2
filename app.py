from flask import Flask, render_template, request, jsonify
import requests
import json
import os

app = Flask(__name__)

# Point to your ngrok tunnel that exposes server.py
# server.py handles /chat -> Ollama
SERVER_URL = "https://dd57d4e4fb6c.ngrok-free.app/chat"

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_msg = request.json.get("message", "")

    try:
        # Send message in the format server.py expects
        response = requests.post(SERVER_URL, json={"message": user_msg})

        if response.status_code == 200:
            data = response.json()
            reply_text = data.get("reply", "Sorry, I couldn't process that.")
        else:
            reply_text = f"Error: server returned {response.status_code}"
    except Exception as e:
        reply_text = f"Error connecting to the server: {e}"

    return jsonify({"reply": reply_text})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
