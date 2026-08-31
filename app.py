import os

from flask import Flask, request, jsonify
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

app = Flask(__name__)

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise RuntimeError("GROQ_API_KEY is not configured on the backend.")

client = Groq(api_key=api_key)


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AI Assistant Backend"
    })


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}

    message = str(data.get("message", "")).strip()

    if not message:
        return jsonify({
            "error": "Message is required."
        }), 400

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": "You are a smart AI personal assistant."
                },
                {
                    "role": "user",
                    "content": message
                }
            ]
        )

        reply = response.choices[0].message.content

        return jsonify({
            "reply": reply
        })

    except Exception as e:
        print("[Backend] Groq error:", e)

        return jsonify({
            "error": "AI service temporarily unavailable."
        }), 500


if __name__ == "__main__":
    print("=" * 50)
    print("AI Assistant Backend")
    print("=" * 50)
    print("Running on http://127.0.0.1:8000")
    print("=" * 50)

    app.run(
        host="127.0.0.1",
        port=8000,
        debug=False
    )