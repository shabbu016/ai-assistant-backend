import os
from flask import Flask, request, jsonify, redirect, session
from dotenv import load_dotenv
from groq import Groq

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

load_dotenv()

app = Flask(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is not configured.")

if not GOOGLE_CLIENT_ID:
    raise RuntimeError("GOOGLE_CLIENT_ID is not configured.")

if not GOOGLE_CLIENT_SECRET:
    raise RuntimeError("GOOGLE_CLIENT_SECRET is not configured.")

client = Groq(api_key=GROQ_API_KEY)

GOOGLE_REDIRECT_URI = (
    "https://ai-assistant-backend-fhht.onrender.com/auth/gmail/callback"
)

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly"
]

# Temporary in-memory storage.
# This is suitable for our current testing/single-user setup.
gmail_credentials = None


# ============================================================
# GOOGLE OAUTH FLOW
# ============================================================

def create_google_flow():
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url":
                "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [
                GOOGLE_REDIRECT_URI
            ]
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )

    return flow


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AI Assistant Backend"
    })


# ============================================================
# AI CHAT
# ============================================================

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


# ============================================================
# GMAIL - START AUTHENTICATION
# ============================================================

@app.route("/auth/gmail", methods=["GET"])
def gmail_auth():
    try:
        flow = create_google_flow()

        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="false",
            prompt="consent"
        )

        # Store BOTH OAuth state and PKCE verifier
        session["google_oauth_state"] = state
        session["google_oauth_code_verifier"] = flow.code_verifier

        return redirect(authorization_url)

    except Exception as e:
        print("[Gmail OAuth] Error:", e)

        return jsonify({
            "error": "Unable to start Gmail authentication.",
            "details": str(e)
        }), 500

# ============================================================
# GMAIL - OAUTH CALLBACK
# ============================================================

@app.route("/auth/gmail/callback", methods=["GET"])
def gmail_callback():
    global gmail_credentials

    try:
        state = session.get("google_oauth_state")
        code_verifier = session.get("google_oauth_code_verifier")

        if not state:
            return "OAuth session expired. Please start Gmail authentication again.", 400

        if not code_verifier:
            return "OAuth code verifier missing. Please start Gmail authentication again.", 400

        flow = create_google_flow()

        flow.state = state
        flow.code_verifier = code_verifier

        flow.fetch_token(
            authorization_response=request.url
        )

        credentials = flow.credentials

        gmail_credentials = credentials

        # Clean up temporary OAuth session values
        session.pop("google_oauth_state", None)
        session.pop("google_oauth_code_verifier", None)

        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Gmail Connected</title>
        </head>
        <body>
            <h1>✅ Gmail Connected Successfully</h1>
            <p>Your Gmail account is now connected to the AI Assistant.</p>
            <p>You can close this window and return to the AI Assistant.</p>
        </body>
        </html>
        """

    except Exception as e:
        print("[Gmail OAuth] Callback error:", e)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Gmail Authentication Error</title>
        </head>
        <body>
            <h1>❌ Gmail Authentication Failed</h1>
            <p>{str(e)}</p>
        </body>
        </html>
        """, 500

# ============================================================
# GMAIL - CONNECTION STATUS
# ============================================================

@app.route("/gmail/status", methods=["GET"])
def gmail_status():
    if gmail_credentials:
        return jsonify({
            "connected": True,
            "service": "Gmail"
        })

    return jsonify({
        "connected": False,
        "service": "Gmail"
    })


# ============================================================
# GMAIL - READ EMAILS
# ============================================================

@app.route("/gmail/emails", methods=["GET"])
def gmail_emails():
    if not gmail_credentials:
        return jsonify({
            "error": "Gmail is not connected.",
            "authorization_url":
                "https://ai-assistant-backend-fhht.onrender.com/auth/gmail"
        }), 401

    try:
        service = build(
            "gmail",
            "v1",
            credentials=gmail_credentials
        )

        results = service.users().messages().list(
            userId="me",
            maxResults=5
        ).execute()

        messages = results.get("messages", [])

        emails = []

        for message in messages:
            msg = service.users().messages().get(
                userId="me",
                id=message["id"],
                format="metadata",
                metadataHeaders=[
                    "From",
                    "Subject",
                    "Date"
                ]
            ).execute()

            headers = msg.get("payload", {}).get(
                "headers", []
            )

            email_data = {}

            for header in headers:
                name = header.get("name")
                value = header.get("value")

                if name in ["From", "Subject", "Date"]:
                    email_data[name.lower()] = value

            emails.append(email_data)

        return jsonify({
            "connected": True,
            "count": len(emails),
            "emails": emails
        })

    except Exception as e:
        print("[Gmail] Error:", e)

        return jsonify({
            "error": "Unable to read Gmail.",
            "details": str(e)
        }), 500


# ============================================================
# RUN LOCALLY
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))

    print("=" * 50)
    print("AI Assistant Backend")
    print("=" * 50)
    print(f"Running on http://127.0.0.1:{port}")
    print("=" * 50)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )