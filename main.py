import queue
import threading
import time
import openai
import re
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# OpenAI API Key
openai.api_key = "YOUR_OPENAI_API_KEY"

# Queue Setup
incoming_queue = queue.Queue()
agent_input_queue = queue.Queue()
agent_output_queue = queue.Queue()
outgoing_queue = queue.Queue()

# Conversation Memory
conversation_history = []

# Lock to Block New Inputs Until AI Responds
response_ready = threading.Event()
response_ready.set()  # Initially ready for input

# FastAPI App
app = FastAPI()

# Default Instruction
DEFAULT_FORMAT_INSTRUCTION = (
    "For every user input, respond naturally as a helpful assistant. "
    "Then at the end of your message, include a JSON object like this:\n"
    "{\"intent\": <guessed_intent>}.\n"
    "Only one JSON object should be present. Do not explain the JSON."
)

# Listener
def listener(incoming_queue, agent_input_queue):
    while True:
        if not incoming_queue.empty():
            msg = incoming_queue.get()
            print(f"[Listener] Received: {msg}")
            agent_input_queue.put(msg)

# AI Agent
def ai_agent(agent_input_queue, agent_output_queue):
    while True:
        if not agent_input_queue.empty():
            user_msg = agent_input_queue.get()
            print(f"[Agent] Processing: {user_msg}")
            messages = [{"role": "system", "content": DEFAULT_FORMAT_INSTRUCTION}]
            messages += conversation_history + [{"role": "user", "content": user_msg}]
            conversation_history.append({"role": "user", "content": user_msg})

            try:
                response = openai.chat.completions.create(
                    model="gpt-4",
                    messages=messages
                )
                reply = response.choices[0].message.content.strip()
            except Exception as e:
                reply = f"Error: {str(e)}"

            conversation_history.append({"role": "assistant", "content": reply})
            formatted_reply = f"\n🧠 AI Assistant:\n----------------\n{reply}\n----------------\n"
            print(f"[Agent] Response: {reply}")
            agent_output_queue.put(formatted_reply)

# Communicator
def communicator(agent_output_queue, outgoing_queue):
    while True:
        if not agent_output_queue.empty():
            response = agent_output_queue.get()
            try:
                intent_json = re.search(r"\{.*\}", response)
                if intent_json:
                    intent_data = json.loads(intent_json.group())
                    intent = intent_data.get("intent", "").lower()
                    print(f"[Communicator] Detected intent: {intent}")
                    if intent == "task":
                        print("📅 Scheduler: Task recognized. Forwarding to scheduler module...")
            except Exception as e:
                print(f"[Communicator] Intent parsing failed: {e}")
            outgoing_queue.put(response)
            response_ready.set()

# Start background threads
def start_background_threads():
    threading.Thread(target=listener, args=(incoming_queue, agent_input_queue), daemon=True).start()
    threading.Thread(target=ai_agent, args=(agent_input_queue, agent_output_queue), daemon=True).start()
    threading.Thread(target=communicator, args=(agent_output_queue, outgoing_queue), daemon=True).start()

# FastAPI endpoint (Webhook)
@app.post("/webhook")
async def webhook_handler(request: Request):
    data = await request.json()
    message = data.get("message") or data.get("text") or ""
    print(f"\n📩 Incoming webhook message: {message}")
    if not message:
        return JSONResponse(content={"error": "No message provided"}, status_code=400)

    response_ready.clear()
    incoming_queue.put(message)

    while not response_ready.is_set():
        time.sleep(0.2)

    # Get AI response
    if not outgoing_queue.empty():
        response = outgoing_queue.get()
        return {"reply": response.strip()}
    else:
        return {"reply": "No response available yet."}

# Run app
if __name__ == "__main__":
    start_background_threads()
    uvicorn.run(app, host="0.0.0.0", port=3000)
