from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import requests
import json
import threading
import psycopg2
import os
import logging
import sys
from datetime import datetime
from colorama import Fore, Style, init
import traceback
from dotenv import load_dotenv

# Load environment
load_dotenv()
init(autoreset=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default-secret")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
RASA_URL = os.environ.get("RASA_URL", "http://localhost:5005/model/parse")

TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_AUTH = os.environ.get("TWILIO_AUTH")
TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER")

# Twilio client will be None if not configured (safe-guard)
client = None
if TWILIO_SID and TWILIO_AUTH:
    try:
        client = Client(TWILIO_SID, TWILIO_AUTH)
    except Exception:
        client = None

DB_CONFIG = {
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "dbname": os.environ.get("DB_NAME")
}

class SimpleLogger:
    def __init__(self):
        logging.basicConfig(level=logging.INFO, format='%(message)s', handlers=[logging.StreamHandler(sys.stdout)])
        self.logger = logging.getLogger("chatbot")

    def ts(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def start(self, channel, endpoint):
        color = Fore.MAGENTA if channel == "whatsapp" else Fore.BLUE
        self.logger.info(f"{color}>>> {channel.upper()} {endpoint} | {self.ts()} {Style.RESET_ALL}")

    def info(self, key, value, color=Fore.WHITE):
        self.logger.info(f"{color}{key}: {Style.RESET_ALL}{value}")

    def success(self, msg):
        self.logger.info(f"{Fore.GREEN}✔ {msg}{Style.RESET_ALL}")

    def warn(self, msg):
        self.logger.info(f"{Fore.YELLOW}⚠ {msg}{Style.RESET_ALL}")

    def error(self, msg):
        self.logger.info(f"{Fore.RED}✖ {msg}{Style.RESET_ALL}")

logger = SimpleLogger()

# Helper: safe json preview
def preview(obj, length=400):
    try:
        s = json.dumps(obj, default=str)
    except Exception:
        s = str(obj)
    return s if len(s) <= length else s[:length] + "..."

# Startup banner
def startup_banner():
    logger.info("SERVER START", f"Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", Fore.CYAN)
    logger.info("Ollama URL", OLLAMA_URL)
    logger.info("Rasa URL", RASA_URL)
    logger.info("Twilio WhatsApp", TWILIO_WHATSAPP_NUMBER or "Not configured")

def classify_intent(text):
    """Return (intent_name, confidence, entities)"""
    try:
        resp = requests.post(RASA_URL, json={"text": text}, timeout=5)
        data = resp.json()
        intent = data.get("intent", {})
        name = intent.get("name")
        confidence = intent.get("confidence", 0)
        entities = data.get("entities", [])
        return name, confidence, entities
    except Exception as e:
        logger.error(f"RASA error: {e}")
        return None, 0, []


def call_ollama(user_message, model="medllama2"):
    try:
        payload = {"model": model, "prompt": user_message}
        headers = {"Content-Type": "application/json"}
        resp = requests.post(OLLAMA_URL, json=payload, headers=headers, timeout=20)

        # Ollama streaming sometimes returns line-delimited JSON; aggregate safely
        reply_text = ""
        if resp is None:
            return "Sorry, no response from Ollama."

        # If text is JSON-lines, try to parse; otherwise fallback to full text
        for line in resp.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                # common key names: 'response' or 'text'
                if isinstance(d, dict):
                    reply_text += d.get('response', d.get('text', ''))
            except Exception:
                reply_text += line + "\n"

        reply_text = reply_text.strip()
        return reply_text or "Sorry, I couldn't generate a response."
    except Exception as e:
        logger.error(f"Ollama call failed: {e}")
        return "Sorry, I couldn't contact the AI service."

def handle_intent(user_number, msg, intent, confidence, entities, channel="whatsapp"):
    logger.start(channel, "intent-handler")
    logger.info("From", user_number)
    logger.info("Message", msg)
    logger.info("Intent", f"{intent} (confidence={confidence:.2f})")
    logger.info("Entities", preview(entities))

    try:
        if intent == "call_ai_agent":
            logger.info("Action", "Call AI Agent")
            reply = call_ollama(msg)

            if channel == "whatsapp" and client:
                try:
                    client.messages.create(body=reply, from_=TWILIO_WHATSAPP_NUMBER, to=user_number)
                    logger.success(f"Sent WhatsApp reply to {user_number}")
                except Exception as e:
                    logger.error(f"Twilio send failed: {e}")
            return reply

        elif intent == "check_schedule":
            logger.info("Action", "Check schedule")
            user_id = next((ent.get('value') for ent in entities if ent.get('entity') == 'user_id'), None)
            reply = fetch_schedule_from_db(user_id)

            if channel == "whatsapp" and client:
                try:
                    client.messages.create(body=reply, from_=TWILIO_WHATSAPP_NUMBER, to=user_number)
                    logger.success(f"Sent schedule to {user_number}")
                except Exception as e:
                    logger.error(f"Twilio send failed: {e}")
            return reply

        else:
            logger.warn("Unknown intent")
            default = "Sorry, I couldn't understand that."
            if channel == "whatsapp" and client:
                try:
                    client.messages.create(body=default, from_=TWILIO_WHATSAPP_NUMBER, to=user_number)
                except Exception:
                    pass
            return default

    except Exception as e:
        logger.error(f"Handler error: {e}\n" + traceback.format_exc())
        return "Sorry, something went wrong while processing your request."

def fetch_schedule_from_db(user_id):
    if not user_id:
        return "Please provide your user ID."
    query = "SELECT name, event, event_date FROM schedules WHERE user_id = %s"
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(query, (user_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            name, event, date = row
            return f"Hi {name}, your {event} is on {date}"
        return "No schedule found for this ID."
    except Exception as e:
        logger.error(f"DB error: {e}")
        return f"Database error: {e}"

@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    logger.start("whatsapp", "/whatsapp")
    try:
        incoming_msg = request.form.get("Body", "").strip()
        from_number = request.form.get("From")

        logger.info("Received (whatsapp)", f"From={from_number}, Msg={incoming_msg}")

        # immediate ack
        resp = MessagingResponse()
        resp.message("Processing your request...")

        # classify and handle in background thread to avoid Twilio timeout
        intent, confidence, entities = classify_intent(incoming_msg)
        threading.Thread(target=handle_intent, args=(from_number, incoming_msg, intent, confidence, entities, "whatsapp"), daemon=True).start()

        logger.success("Acknowledged and processing in background")
        return str(resp)
    except Exception as e:
        logger.error(f"WhatsApp webhook error: {e}\n" + traceback.format_exc())
        resp = MessagingResponse()
        resp.message("Sorry, there was an error processing your message.")
        return str(resp)

@app.route("/chat", methods=["POST"])
def webchat_reply():
    logger.start("webchat", "/chat")
    try:
        data = request.json or {}
        user_msg = (data.get("message") or "").strip()
        logger.info("Received (webchat)", preview(data))

        intent, confidence, entities = classify_intent(user_msg)
        reply = handle_intent("web", user_msg, intent, confidence, entities, "webchat")

        logger.success("Webchat processed")
        return jsonify({"reply": reply})
    except Exception as e:
        logger.error(f"Webchat error: {e}\n" + traceback.format_exc())
        return jsonify({"reply": "Sorry, there was an error processing your message."}), 500

@app.route("/health", methods=["GET"])
def health_check():
    logger.start("system", "/health")
    health = {"status": "healthy", "timestamp": datetime.now().isoformat(), "services": {}}

    # check services quickly
    try:
        requests.get(OLLAMA_URL, timeout=2)
        health["services"]["ollama"] = "running"
    except:
        health["services"]["ollama"] = "down"

    try:
        requests.get(RASA_URL, timeout=2)
        health["services"]["rasa"] = "running"
    except:
        health["services"]["rasa"] = "down"

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
        health["services"]["database"] = "running"
    except:
        health["services"]["database"] = "down"

    logger.info("Health", preview(health))
    return jsonify(health)

if __name__ == "__main__":
    startup_banner()
    logger.success("Server starting on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000)
