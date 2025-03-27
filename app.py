from flask import Flask, render_template, request, jsonify
import threading
import requests
import json
import time
import config
from auth import get_access_token
from log_config import logger

app = Flask(__name__)

# Global conversation history for chat mode.
conversation_history = []
# Global flag to track if the custom system prompt has been injected.
system_injected = False

# Construct the API endpoint using your configuration.
API_ENDPOINT = f'{config.apiUrl}experiment/{config.experimentId}'

def call_chat_api(payload, headers):
    """Keep retrying the API call until a valid reply is received."""
    reply = None
    while reply is None:
        try:
            response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(payload), timeout=config.API_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                messages = data.get("chatHistory", {}).get("messages", [])
                if messages:
                    # Use the last message as the reply.
                    last_message = messages[-1]
                    reply = last_message.get("content", "No content in reply.")
                else:
                    reply = "No messages in API response."
                # Update conversation_history from API if provided.
                if "chatHistory" in data and "messages" in data["chatHistory"]:
                    conversation_history[:] = data["chatHistory"]["messages"]
            else:
                logger.error(f"Error {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Exception during API call: {e}")
        if reply is None:
            time.sleep(5)
    return reply

@app.route("/")
def index():
    return render_template("chat.html")

@app.route("/chat", methods=["POST"])
def chat():
    global system_injected
    # Get the user message from the form.
    user_message = request.form.get("message", "").strip()
    if user_message:
        conversation_history.append({
            "id": f"user-{len(conversation_history)+1}",
            "role": "user",
            "content": user_message
        })
    else:
        # If no input and conversation is empty, use a default.
        if not conversation_history:
            default_search = "2405160050001621"
            conversation_history.append({
                "id": f"user-{len(conversation_history)+1}",
                "role": "user",
                "content": default_search
            })
            user_message = default_search

    # Build the payload (always include chatHistory).
    payload = {
        "dataSearchKey": "CaseNumber",
        "DataSearchOptions": {
            "Search": "123",   # Adjust as needed (must be a string)
            "SearchMode": "all"
        },
        "chatHistory": {
            "messages": conversation_history
        },
        "MaxNumberOfRows": 5000
    }

    # Retrieve token.
    with config.token_lock:
        token = config.access_token
    if not token:
        token = get_access_token()
        with config.token_lock:
            config.access_token = token

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Call the API (this call will block until a valid reply is received).
    reply = call_chat_api(payload, headers)

    # Inject the custom system prompt if no system message exists.
    if not any(msg["role"] == "system" for msg in conversation_history):
        custom_instruction = config.CONFIG.get("Custom Chat Instructions", "ChatCustomization",
                                               fallback="Run a job to start the conversation.")
        greeting = f"Hi, {custom_instruction}"
        system_msg = {
            "id": "system-001",
            "role": "system",
            "content": greeting
        }
        conversation_history.append(system_msg)

    # Append assistant reply.
    conversation_history.append({
        "id": f"assistant-{len(conversation_history)+1}",
        "role": "assistant",
        "content": reply
    })

    # Return the latest conversation history and reply.
    return jsonify({"reply": reply, "conversation_history": conversation_history})

if __name__ == "__main__":
    app.run(debug=True)
