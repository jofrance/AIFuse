import tkinter as tk
from tkinter import scrolledtext, ttk
import threading
import requests
import json
import time
import config
from auth import get_access_token
from log_config import logger

# Global conversation history for chat mode.
conversation_history = []
# Global flag to ensure the custom system prompt is injected only once.
system_injected = False

# Construct the API endpoint using your configuration.
API_ENDPOINT = f'{config.apiUrl}experiment/{config.experimentId}'

def open_chat_window(root):
    """
    Opens a secondary chat window with two distinct sections:
    - Top: Displays conversation history.
    - Bottom: Input area for user messages.
    The window is positioned next to the main window.
    When the window is opened, the chat display is repopulated from the global conversation_history.
    """
    chat_window = tk.Toplevel(root)
    chat_window.title("Chat with Model")
    window_width = 500
    window_height = 500

    # Position the chat window next to the main window.
    root.update_idletasks()
    root_x = root.winfo_x()
    root_y = root.winfo_y()
    root_width = root.winfo_width()
    new_x = root_x + root_width + 10  # 10-pixel gap
    new_y = root_y
    chat_window.geometry(f"{window_width}x{window_height}+{new_x}+{new_y}")

    # When the chat window is closed, simply destroy it (but preserve conversation_history).
    chat_window.protocol("WM_DELETE_WINDOW", chat_window.destroy)

    # Top frame: Chat display area.
    top_frame = tk.Frame(chat_window)
    top_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)
    chat_display = scrolledtext.ScrolledText(top_frame, wrap=tk.WORD, state='disabled')
    chat_display.pack(fill=tk.BOTH, expand=True)

    # Re-populate the chat display from conversation_history.
    chat_display.config(state='normal')
    chat_display.delete('1.0', tk.END)
    if conversation_history:
        for msg in conversation_history:
            sender = msg["role"].capitalize()
            chat_display.insert(tk.END, f"{sender}: {msg['content']}\n")
            chat_display.insert(tk.END, " " * 50 + "\n")
    else:
        # If conversation_history is empty, inject the custom system prompt.
        custom_instruction = config.CONFIG.get("Custom Chat Instructions", "ChatCustomization",
                                                 fallback="Run a job to start the conversation.")
        system_message = {
            "id": "001",
            "role": "system",
            "content": custom_instruction
        }
        conversation_history.append(system_message)
        chat_display.insert(tk.END, f"System: {system_message['content']}\n")
        chat_display.insert(tk.END, " " * 50 + "\n")
    chat_display.config(state='disabled')
    chat_display.see(tk.END)

    # Bottom frame: Input area.
    bottom_frame = tk.Frame(chat_window)
    bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
    message_entry = tk.Entry(bottom_frame)
    message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
    message_entry.focus_set()
    send_button = ttk.Button(bottom_frame, text="Send", 
                             command=lambda: send_chat_message(chat_display, message_entry))
    send_button.pack(side=tk.RIGHT)
    message_entry.bind("<Return>", lambda event: send_chat_message(chat_display, message_entry))
    
    return chat_window

def send_chat_message(chat_display, message_entry):
    """
    Sends the user's message to the API using the shared token and API endpoint,
    then updates the conversation history.
    If errors occur, the API call is retried every 5 seconds until a valid response is received.
    Additionally, on the first API response, if there's no system message, the custom
    system prompt is injected.
    """
    message = message_entry.get().strip()
    if not message:
        return

    # Append the user's message to the display and conversation history.
    append_chat(chat_display, "You", message)
    conversation_history.append({
        "id": f"user-{len(conversation_history)+1}",
        "role": "user",
        "content": message
    })
    message_entry.delete(0, tk.END)

    # Build the payload.
    payload = {
        "dataSearchKey": "CaseNumber",
        "DataSearchOptions": {
            "Search": "123",
            "SearchMode": "all"
        },
        "chatHistory": {
            "messages": conversation_history
        },
        "MaxNumberOfRows": 5000
    }

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

    api_endpoint = f'{config.apiUrl}experiment/{config.experimentId}'

    def call_api():
        reply = None
        # Retry until a valid reply is obtained.
        while reply is None:
            try:
                response = requests.post(api_endpoint, headers=headers, data=json.dumps(payload), timeout=config.API_TIMEOUT)
                if response.status_code == 200:
                    data = response.json()
                    messages = data.get("chatHistory", {}).get("messages", [])
                    if messages:
                        last_message = messages[-1]
                        reply = last_message.get("content", "No content in reply.")
                    else:
                        reply = "No messages in API response."
                    # Update conversation_history from the API's entire chatHistory
                    # (which already includes the assistant's latest message).
                    if "chatHistory" in data and "messages" in data["chatHistory"]:
                        conversation_history[:] = data["chatHistory"]["messages"]
                else:
                    logger.error(f"Error {response.status_code}: {response.text}")
            except Exception as e:
                logger.error(f"Exception during API call: {e}")
            if reply is None:
                time.sleep(5)

        # If there's no system message, inject the custom system prompt.
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
            chat_display.after(0, lambda: append_chat(chat_display, "System", greeting))

        # IMPORTANT: We do NOT append the assistant message here, because the updated
        # conversation_history from the API already contains it. We only display it:
        chat_display.after(0, lambda: append_chat(chat_display, "Assistant", reply))

    threading.Thread(target=call_api, daemon=True).start()



def append_chat(chat_display, sender, message):
    """
    Appends a new message to the chat display along with a separator.
    """
    chat_display.config(state='normal')
    chat_display.insert(tk.END, f"{sender}: {message}\n")
    chat_display.insert(tk.END, " " * 50 + "\n")
    chat_display.config(state='disabled')
    chat_display.see(tk.END)


