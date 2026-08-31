import os
from flask import Flask, request, jsonify, redirect, session
from dotenv import load_dotenv
from groq import Groq
from slack_sdk import WebClient 
import psycopg2

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
DATABASE_URL = os.getenv("DATABASE_URL")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv(
    "TWILIO_WHATSAPP_FROM",
    "whatsapp:+14155238886"
)

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is not configured.")

if not GOOGLE_CLIENT_ID:
    raise RuntimeError("GOOGLE_CLIENT_ID is not configured.")

if not GOOGLE_CLIENT_SECRET:
    raise RuntimeError("GOOGLE_CLIENT_SECRET is not configured.")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured.")

client = Groq(api_key=GROQ_API_KEY)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")

if not SLACK_BOT_TOKEN:
    raise RuntimeError("SLACK_BOT_TOKEN is not configured.")

slack_client = WebClient(token=SLACK_BOT_TOKEN)

GOOGLE_REDIRECT_URI = (
    "https://ai-assistant-backend-fhht.onrender.com/auth/gmail/callback"
)

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly"
]

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gmail_credentials (
            id INTEGER PRIMARY KEY,
            credentials TEXT NOT NULL
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()

    print("[Database] PostgreSQL initialized successfully.")


def save_gmail_credentials(credentials):
    credentials_json = credentials.to_json()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO gmail_credentials (id, credentials)
        VALUES (1, %s)
        ON CONFLICT (id)
        DO UPDATE SET credentials = EXCLUDED.credentials
    """, (credentials_json,))

    conn.commit()
    cursor.close()
    conn.close()

    print("[Gmail] Credentials saved to PostgreSQL.")


def get_gmail_credentials():
    import json
    from google.oauth2.credentials import Credentials

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT credentials
        FROM gmail_credentials
        WHERE id = 1
    """)

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    if not row:
        return None

    return Credentials.from_authorized_user_info(
        json.loads(row[0])
    )


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
        text = message.lower()

        # ====================================================
        # SLACK - SEND
        # ====================================================

        if "send slack" in text:

            import re

            channel_match = re.search(
                r"#([a-zA-Z0-9_-]+)",
                message
            )

            if channel_match:
                channel = channel_match.group(1)
            else:
                channel = "new-channel"

            if ":" not in message:
                return jsonify({
                    "reply": (
                        "Please provide the Slack message. "
                        "Example: Send Slack message to "
                        "#new-channel: Hello team"
                    ),
                    "slack_connected": True
                })

            slack_message = message.split(":", 1)[1].strip()

            if not slack_message:
                return jsonify({
                    "reply": "Please provide a message to send to Slack.",
                    "slack_connected": True
                })

            # Find channel ID
            channels = slack_client.conversations_list(
                types="public_channel"
            )

            channel_id = None

            for ch in channels.get("channels", []):
                if ch.get("name") == channel:
                    channel_id = ch.get("id")
                    break

            if not channel_id:
                return jsonify({
                    "reply": f"Slack channel #{channel} was not found.",
                    "slack_connected": True
                })

            # Send message
            slack_client.chat_postMessage(
                channel=channel_id,
                text=slack_message
            )

            return jsonify({
                "reply": (
                    f"Message sent successfully to #{channel}."
                ),
                "slack_connected": True,
                "channel": channel
            })

        # ====================================================
        # SLACK - READ
        # ====================================================

        slack_read_request = (
            "slack" in text
            or "#" in text
        ) and (
            "read" in text
            or "latest messages" in text
            or "messages" in text
            or "recent messages" in text
        )

        if slack_read_request:

            import re

            channel_match = re.search(
                r"#([a-zA-Z0-9_-]+)",
                message
            )

            if channel_match:
                channel = channel_match.group(1)
            else:
                channel = "new-channel"

            # Find channel ID
            channels = slack_client.conversations_list(
                types="public_channel"
            )

            channel_id = None

            for ch in channels.get("channels", []):
                if ch.get("name") == channel:
                    channel_id = ch.get("id")
                    break

            if not channel_id:
                return jsonify({
                    "reply": f"Slack channel #{channel} was not found.",
                    "slack_connected": True
                })

            # Get recent messages
            result = slack_client.conversations_history(
                channel=channel_id,
                limit=5
            )

            messages = result.get("messages", [])

            if not messages:
                return jsonify({
                    "reply": f"No messages found in #{channel}.",
                    "slack_connected": True,
                    "channel": channel,
                    "message_count": 0
                })

            slack_context = "\n".join(
                [
                    f"[{msg.get('user', 'Unknown')}]: "
                    f"{msg.get('text', '')}"
                    for msg in messages
                ]
            )

            # Let Groq summarize/respond naturally
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a smart AI personal assistant. "
                            "The user has connected Slack. "
                            "Use ONLY the provided Slack messages. "
                            "Do not invent messages or details."
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            f"User request:\n{message}\n\n"
                            f"Recent Slack messages from "
                            f"#{channel}:\n{slack_context}"
                        )
                    }
                ]
            )

            reply = response.choices[0].message.content

            return jsonify({
                "reply": reply,
                "slack_connected": True,
                "channel": channel,
                "message_count": len(messages)
            })

                # ====================================================
        # WHATSAPP - SEND
        # ====================================================

        if "send whatsapp" in text:

            import re

            phone_match = re.search(
                r"\+91\d{10}",
                message
            )

            if not phone_match:
                return jsonify({
                    "reply": (
                        "Please provide the WhatsApp number "
                        "with country code. "
                        "Example: Send WhatsApp to "
                        "+919611748091: Hello"
                    ),
                    "whatsapp_connected": True
                })

            phone_number = phone_match.group(0)

            if ":" not in message:
                return jsonify({
                    "reply": (
                        "Please provide the message. "
                        "Example: Send WhatsApp to "
                        "+919611748091: Hello"
                    ),
                    "whatsapp_connected": True
                })

            whatsapp_message = message.split(":", 1)[1].strip()

            if not whatsapp_message:
                return jsonify({
                    "reply": "Please provide a message to send.",
                    "whatsapp_connected": True
                })

            from twilio.rest import Client

            twilio_client = Client(
                TWILIO_ACCOUNT_SID,
                TWILIO_AUTH_TOKEN
            )

            to_number = f"whatsapp:{phone_number}"

            result = twilio_client.messages.create(
                body=whatsapp_message,
                from_=TWILIO_WHATSAPP_FROM,
                to=to_number
            )

            return jsonify({
                "reply": "WhatsApp message sent successfully.",
                "whatsapp_connected": True,
                "sid": result.sid
            })

        # ====================================================
        # CHECK WHETHER USER IS ASKING ABOUT GMAIL
        # ====================================================

        gmail_keywords = [
            "email",
            "emails",
            "gmail",
            "inbox",
            "mail",
            "unread"
        ]

        is_gmail_request = any(
            keyword in text
            for keyword in gmail_keywords
        )

        # ====================================================
        # NORMAL AI CHAT
        # ====================================================

        if not is_gmail_request:

            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a smart AI personal assistant."
                        )
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

        # ====================================================
        # GMAIL REQUEST
        # ====================================================

        credentials = get_gmail_credentials()

        if not credentials:

            return jsonify({
                "reply": (
                    "Your Gmail account is not currently connected. "
                    "Please connect Gmail first."
                ),
                "gmail_connected": False,
                "authorization_url": (
                    "https://ai-assistant-backend-fhht.onrender.com/"
                    "auth/gmail"
                )
            })

        # ====================================================
        # FETCH EMAILS
        # ====================================================

        service = build(
            "gmail",
            "v1",
            credentials=credentials
        )

        results = service.users().messages().list(
            userId="me",
            maxResults=5
        ).execute()

        messages = results.get("messages", [])

        emails = []

        for message_item in messages:

            msg = service.users().messages().get(
                userId="me",
                id=message_item["id"],
                format="metadata",
                metadataHeaders=[
                    "From",
                    "Subject",
                    "Date"
                ]
            ).execute()

            headers = (
                msg.get(
                    "payload",
                    {}
                ).get(
                    "headers",
                    []
                )
            )

            email_data = {}

            for header in headers:

                name = header.get("name")
                value = header.get("value")

                if name in [
                    "From",
                    "Subject",
                    "Date"
                ]:
                    email_data[name.lower()] = value

            emails.append(email_data)

        # ====================================================
        # GIVE EMAIL DATA TO GROQ
        # ====================================================

        email_context = "\n\n".join(
            [
                f"Email {i + 1}:\n"
                f"From: {email.get('from', 'Unknown')}\n"
                f"Subject: {email.get('subject', 'No subject')}\n"
                f"Date: {email.get('date', 'Unknown')}"
                for i, email in enumerate(emails)
            ]
        )

        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a smart AI personal assistant. "
                        "The user has connected Gmail. "
                        "Use the provided email information to answer "
                        "the user's question accurately. "
                        "Do not invent email details."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"User request:\n{message}\n\n"
                        f"Latest Gmail emails:\n{email_context}"
                    )
                }
            ]
        )

        reply = response.choices[0].message.content

        return jsonify({
            "reply": reply,
            "gmail_connected": True,
            "email_count": len(emails)
        })

    except Exception as e:

        print("[Backend] Chat error:", e)

        return jsonify({
            "error": "Unable to process your request.",
            "details": str(e)
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

        save_gmail_credentials(credentials)

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
    credentials = get_gmail_credentials()

    if credentials:
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
    credentials = get_gmail_credentials()
    if not credentials:
        return jsonify({
            "error": "Gmail is not connected.",
            "authorization_url":
                "https://ai-assistant-backend-fhht.onrender.com/auth/gmail"
        }), 401

    try:
        service = build(
            "gmail",
            "v1",
            credentials=credentials
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
# DATABASE INITIALIZATION
# ============================================================

try:
    init_database()
except Exception as e:
    print("[Database] Initialization error:", e)


@app.route("/slack/status", methods=["GET"])
def slack_status():
    try:
        response = slack_client.auth_test()

        return jsonify({
            "connected": response.get("ok", False),
            "service": "Slack",
            "bot": response.get("user"),
            "team": response.get("team")
        })

    except Exception as e:
        print("[Slack] Status error:", e)

        return jsonify({
            "connected": False,
            "service": "Slack",
            "error": str(e)
        }), 500

@app.route("/slack/messages", methods=["GET"])
def slack_messages():
    channel = request.args.get("channel", "new-channel")
    limit = int(request.args.get("limit", 5))

    try:
        channel_name = channel.lstrip("#")

        channels = slack_client.conversations_list(
            types="public_channel"
        )

        channel_id = None

        for ch in channels.get("channels", []):
            if ch.get("name") == channel_name:
                channel_id = ch.get("id")
                break

        if not channel_id:
            return jsonify({
                "error": f"Channel #{channel_name} not found."
            }), 404

        result = slack_client.conversations_history(
            channel=channel_id,
            limit=limit
        )

        messages = []

        for msg in result.get("messages", []):
            messages.append({
                "user": msg.get("user", "Unknown"),
                "text": msg.get("text", ""),
                "timestamp": msg.get("ts")
            })

        return jsonify({
            "connected": True,
            "channel": f"#{channel_name}",
            "count": len(messages),
            "messages": messages
        })

    except Exception as e:
        print("[Slack] Read error:", e)

        return jsonify({
            "error": "Unable to read Slack messages.",
            "details": str(e)
        }), 500


@app.route("/slack/send", methods=["POST"])
def slack_send():
    data = request.get_json(silent=True) or {}

    channel = str(data.get("channel", "")).strip()
    message = str(data.get("message", "")).strip()

    if not channel:
        return jsonify({
            "error": "Channel is required."
        }), 400

    if not message:
        return jsonify({
            "error": "Message is required."
        }), 400

    try:
        channel_name = channel.lstrip("#")

        channels = slack_client.conversations_list(
            types="public_channel"
        )

        channel_id = None

        for ch in channels.get("channels", []):
            if ch.get("name") == channel_name:
                channel_id = ch.get("id")
                break

        if not channel_id:
            return jsonify({
                "error": f"Channel #{channel_name} not found."
            }), 404

        slack_client.chat_postMessage(
            channel=channel_id,
            text=message
        )

        return jsonify({
            "success": True,
            "channel": f"#{channel_name}",
            "message": message
        })

    except Exception as e:
        print("[Slack] Send error:", e)

        return jsonify({
            "error": "Unable to send Slack message.",
            "details": str(e)
        }), 500

# ============================================================
# WHATSAPP - SEND
# ============================================================

@app.route("/whatsapp/send", methods=["POST"])
def whatsapp_send():
    data = request.get_json(silent=True) or {}

    to_number = str(data.get("to", "")).strip()
    message = str(data.get("message", "")).strip()

    if not to_number:
        return jsonify({
            "error": "WhatsApp recipient number is required."
        }), 400

    if not message:
        return jsonify({
            "error": "WhatsApp message is required."
        }), 400

    try:
        from twilio.rest import Client

        twilio_client = Client(
            TWILIO_ACCOUNT_SID,
            TWILIO_AUTH_TOKEN
        )

        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"

        result = twilio_client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_FROM,
            to=to_number
        )

        return jsonify({
            "reply": "WhatsApp message sent successfully.",
            "success": True,
            "sid": result.sid,
            "to": to_number
        })

    except Exception as e:
        print("[Backend] WhatsApp send error:", e)

        return jsonify({
            "error": "Unable to send WhatsApp message.",
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