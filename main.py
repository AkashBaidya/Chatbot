"""
main.py
-------
CLI entry point for the Acme Corp HR Chatbot.

Usage:
    python main.py

Environment:
    GROQ_API_KEY must be set.
"""

import os
import sys
import textwrap

from dotenv import load_dotenv

load_dotenv()


def print_banner():
    print("\n" + "=" * 60)
    print("  [BOT] HR Assistant")
    print("=" * 60)
    print("  Ask me about company policies, benefits, vacation days,")
    print("  learning budgets, and more.")
    print()
    print("  Commands:")
    print("    'quit' or 'exit' — end the session")
    print("    'reset'          — start a new conversation")
    print("    'docs'           — list loaded knowledge base files")
    print("=" * 60 + "\n")


def print_response(text: str):
    """Print assistant response with word wrapping."""
    print()
    print("Assistant:")
    # Wrap long lines but preserve intentional newlines
    for line in text.split("\n"):
        if line.strip():
            wrapped = textwrap.fill(line, width=72, subsequent_indent="  ")
            print(f"  {wrapped}")
        else:
            print()
    print()


def check_api_key():
    if not os.environ.get("GROQ_API_KEY"):
        print("[ERROR] GROQ_API_KEY environment variable is not set.")
        print("   Set it before running:")
        print("   set GROQ_API_KEY=gsk_...")
        sys.exit(1)


def main():
    check_api_key()

    # ── Load knowledge base ──────────────────────────────────────────────────
    print("Loading knowledge base...")
    try:
        from document_loader import load_knowledge_base

        documents = load_knowledge_base("knowledge_base")
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    if not documents:
        print("[WARNING] No documents found in knowledge_base/. Add .pdf, .txt, or .md files.")
        sys.exit(1)

    print(
        f"[OK] Loaded {len(documents)} document(s): {', '.join(d.filename for d in documents)}"
    )

    # ── Index documents for RAG ───────────────────────────────────────────────
    print("Indexing documents for RAG search...")
    from rag_engine import index_documents

    chunk_count = index_documents(documents)
    print(f"[OK] Indexed {chunk_count} chunks.\n")

    # ── Initialize chatbot ───────────────────────────────────────────────────
    try:
        from chatbot import Chatbot

        bot = Chatbot()
    except ImportError as e:
        print(f"[ERROR] Missing dependency: {e}")
        print("   Run: pip install -r requirements.txt")
        sys.exit(1)

    print_banner()

    # ── REPL loop ────────────────────────────────────────────────────────────
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            break

        if not user_input:
            continue

        command = user_input.lower()

        if command in ("quit", "exit"):
            print("\nGoodbye!\n")
            break

        elif command == "reset":
            bot.reset()
            print("\n[Conversation reset. Starting fresh.]\n")
            continue

        elif command == "docs":
            print("\nLoaded documents:")
            for doc in documents:
                print(f"  • [{doc.format.upper()}] {doc.filename}")
            print()
            continue

        # Normal chat
        try:
            response = bot.chat(user_input)
            print_response(response)
        except Exception as e:
            print(f"\n[ERROR] {e}\n")


if __name__ == "__main__":
    main()
