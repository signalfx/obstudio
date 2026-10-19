"""Command-line chat assistant that recommends smash burger restaurants.

This is the terminal front-end. The actual agent logic (system prompt, tools,
turn loop) lives in `chat_core.py` and is shared with the web app (`app.py`).

Usage:
    python agent.py

Environment:
    OPENAI_API_KEY   (required) your OpenAI API key
    OPENAI_MODEL     (optional) defaults to "gpt-4o-mini"
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from chat_core import build_client, get_model, new_conversation, run_turn


def main() -> None:
    load_dotenv()

    try:
        client = build_client()
    except RuntimeError:
        print(
            "Error: OPENAI_API_KEY is not set. Create a .env file (see .env.example) "
            "or export the variable, then try again.",
            file=sys.stderr,
        )
        sys.exit(1)

    model = get_model()
    messages = new_conversation()

    print("🍔 SmashBot — your smash burger guide. Tell me a city and I'll find you some.")
    print("   (type 'quit' or 'exit' to leave)\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSmashBot: Catch you later! 🍔")
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit", "bye"}:
            print("SmashBot: Catch you later! 🍔")
            break

        messages.append({"role": "user", "content": user_input})

        try:
            reply = run_turn(client, model, messages)
        except Exception as exc:  # noqa: BLE001 - surface any API error to the user
            print(f"SmashBot: Sorry, something went wrong: {exc}\n")
            continue

        print(f"SmashBot: {reply}\n")


if __name__ == "__main__":
    main()
