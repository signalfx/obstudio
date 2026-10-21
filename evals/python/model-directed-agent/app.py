"""Flask web app for SmashBot, with Buttercup the pony as mascot.

Serves a single-page chat UI and exposes a JSON `/chat` endpoint. Conversation
history is kept per browser session in an in-memory store keyed by a session id
cookie. The agent logic is shared with the CLI via `chat_core.py`.

Usage:
    python app.py
    # then open http://127.0.0.1:5000

Environment:
    OPENAI_API_KEY   (required) your OpenAI API key
    OPENAI_MODEL     (optional) defaults to "gpt-4o-mini"
    FLASK_SECRET     (optional) session-signing secret; a random one is used if unset
"""

from __future__ import annotations

import atexit
import os
import secrets
import uuid

from dotenv import load_dotenv

load_dotenv()

# Configure OpenTelemetry before the Flask app is created/instrumented.
from otel_setup import configure_opentelemetry  # noqa: E402

_install_logging_bridge, _shutdown_opentelemetry = configure_opentelemetry()
# Normal-exit fallback; a real deployment should also wire this to the server's
# graceful-shutdown hook.
atexit.register(_shutdown_opentelemetry)

from flask import Flask, jsonify, render_template, request, session  # noqa: E402
from opentelemetry.instrumentation.flask import FlaskInstrumentor  # noqa: E402

from chat_core import build_client, get_model, new_conversation, run_turn  # noqa: E402

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET") or secrets.token_hex(16)

# Accessing app.logger establishes Flask's default console handler; install the
# OTel logging bridge after it exists so the existing stderr sink is preserved.
_ = app.logger
_install_logging_bridge()
FlaskInstrumentor().instrument_app(app)

# In-memory conversation store: {session_id: messages}. Fine for a single-process
# dev server; swap for a real store (Redis, DB) if you scale beyond that.
_CONVERSATIONS: dict[str, list] = {}


def _get_messages() -> list:
    """Return the message history for the current browser session, creating one if needed."""
    sid = session.get("sid")
    if not sid:
        sid = uuid.uuid4().hex
        session["sid"] = sid
    if sid not in _CONVERSATIONS:
        _CONVERSATIONS[sid] = new_conversation()
    return _CONVERSATIONS[sid]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or not isinstance(data.get("message"), str):
        return jsonify({"error": "Please enter a message."}), 400
    user_input = data["message"].strip()
    if not user_input:
        return jsonify({"error": "Please enter a message."}), 400

    try:
        client = build_client()
    except RuntimeError:
        return (
            jsonify(
                {
                    "error": "The server is missing OPENAI_API_KEY. "
                    "Set it in a .env file and restart."
                }
            ),
            500,
        )

    messages = _get_messages()
    previous_length = len(messages)
    messages.append({"role": "user", "content": user_input})

    try:
        reply = run_turn(client, get_model(), messages)
    except Exception:  # noqa: BLE001 - return a bounded failure response
        # A failed turn may have appended assistant tool requests and results.
        del messages[previous_length:]
        return jsonify({"error": "The assistant is temporarily unavailable."}), 502

    return jsonify({"reply": reply})


@app.route("/reset", methods=["POST"])
def reset():
    """Clear the current session's conversation history."""
    sid = session.get("sid")
    if sid and sid in _CONVERSATIONS:
        _CONVERSATIONS[sid] = new_conversation()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
