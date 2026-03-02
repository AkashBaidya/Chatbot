"""
chatbot.py
----------
Core chatbot logic — powered by Groq's API.

Groq uses the OpenAI-compatible SDK, so the response format differs from Anthropic:
  - System prompt goes inside the messages list as {"role": "system", ...}
  - Tool calls live at response.choices[0].message.tool_calls
  - Tool results go back as {"role": "tool", "tool_call_id": ..., "content": ...}
  - Stop reason is finish_reason == "tool_calls" (not "tool_use")
"""

import json
import re

from groq import Groq, BadRequestError

import tools
import rag_engine
from mock_services import call_service

# Recommended Groq models with tool-use support:
#   llama-3.3-70b-versatile   <- best quality (default)
#   llama-3.1-8b-instant      <- fastest
#   mixtral-8x7b-32768        <- large context window
MODEL = "llama-3.3-70b-versatile"
MAX_TOKENS = 1024


def build_system_prompt(context_text: str, employee_id: str | None = None, employee_name: str | None = None) -> str:
    employee_context = ""
    if employee_id and employee_name:
        employee_context = f"""

CURRENT USER:
- Employee ID: {employee_id}
- Name: {employee_name}
When the user asks about their own data (vacation, budget, info), always pass
employee_id="{employee_id}" to the relevant tool. Do NOT ask the user for their ID.
Address the user by their first name ({employee_name.split()[0]})."""
    elif not employee_id:
        employee_context = """

NOTE: No employee is currently logged in. If the user asks about personal data
(vacation days, budget, etc.), let them know they need to log in first using
the employee login on the left sidebar."""

    return f"""You are a helpful HR assistant chatbot for Trenkwalder employees.

You have access to two types of information:

1. STATIC KNOWLEDGE BASE - Relevant excerpts retrieved from company documents.
   Answer questions from these directly. Always cite the source filename shown
   in the [Source: ...] brackets.

2. DYNAMIC DATA - Real-time employee data fetched via tools.
   When a user asks about personal data or anything time-sensitive, use the
   appropriate tool. Never guess numbers.
{employee_context}

Guidelines:
- Be concise and friendly.
- If a question isn't covered by the excerpts or tools, say so clearly.
- Cite documents by filename (e.g. "According to benefits_guide.txt...").
- Present tool results clearly (e.g. "You have X days remaining").

--- RELEVANT KNOWLEDGE BASE EXCERPTS ---
{context_text}
--- END EXCERPTS ---"""


class Chatbot:
    """Stateful chatbot using Groq API with tool-use support."""

    def __init__(self):
        self.client = Groq()  # reads GROQ_API_KEY from environment
        self.history: list[dict] = []

    def _get_system_prompt(self, user_query: str, employee_id: str | None = None) -> str:
        """Retrieve relevant chunks and build system prompt per query."""
        chunks = rag_engine.retrieve(user_query)
        context_text = rag_engine.format_retrieved_context(chunks)

        if employee_id:
            from mock_services import get_mock_data
            data = get_mock_data()
            emp = data.get("employees", {}).get(employee_id)
            name = emp["name"] if emp else None
            return build_system_prompt(context_text, employee_id, name)
        return build_system_prompt(context_text)

    def _parse_failed_tool_call(self, error: BadRequestError) -> dict | None:
        """Try to extract tool name + args from a Groq tool_use_failed error.

        Groq sometimes returns errors with formats like:
          '<function=get_vacation_balance{"employee_id":"E001"}</function>'
          '<function=get_vacation_balance,{"employee_id":"E001"}</function>'
        We parse this and execute the call manually.
        """
        try:
            body = error.body
            if not isinstance(body, dict):
                return None
            err_obj = body.get("error", {})
            if err_obj.get("code") != "tool_use_failed":
                return None
            failed = err_obj.get("failed_generation", "")
            # Match both with and without comma separator
            m = re.match(r'<function=(\w+),?\s*(\{.*?\})\s*</function>', failed)
            if not m:
                return None
            fn_name = m.group(1)
            fn_args = json.loads(m.group(2))
            return {"name": fn_name, "arguments": fn_args}
        except Exception:
            return None

    def chat(self, user_message: str, employee_id: str | None = None) -> str:
        """Send a message, run the tool-use loop, return final text."""
        self.history.append({"role": "user", "content": user_message})

        system_prompt = self._get_system_prompt(user_message, employee_id)
        retries_left = 2
        recovered_results = {}  # tool_name -> result from recovery

        while True:
            messages = [
                {"role": "system", "content": system_prompt},
                *self.history,
            ]

            try:
                response = self.client.chat.completions.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    tools=tools.GROQ_TOOL_DEFINITIONS,
                    tool_choice="auto",
                    messages=messages,
                )
            except BadRequestError as e:
                parsed = self._parse_failed_tool_call(e)
                if parsed:
                    fn_name = parsed["name"]
                    fn_args = parsed["arguments"]
                    print(f"  [tool] Recovering failed generation: {fn_name}({json.dumps(fn_args)})")
                    result = call_service(fn_name, fn_args)
                    recovered_results[fn_name] = result

                    if retries_left > 0:
                        retries_left -= 1
                        # Retry without tool history (clean retry)
                        continue

                # If we have recovered results, generate a response without tools
                if recovered_results:
                    summary = json.dumps(recovered_results, indent=2)
                    self.history.append({"role": "user", "content":
                        f"[System: tool results are below. Summarize them for the user.]\n{summary}"})
                    fallback = self.client.chat.completions.create(
                        model=MODEL,
                        max_tokens=MAX_TOKENS,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            *self.history,
                        ],
                    )
                    reply = fallback.choices[0].message.content or ""
                    # Clean up the synthetic message
                    self.history.pop()
                    self.history.append({"role": "assistant", "content": reply})
                    return reply
                raise

            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            # Build assistant message with only the fields Groq accepts.
            # The SDK response includes extra fields (e.g. 'annotations')
            # that cause 400 errors if sent back.
            assistant_msg = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                assistant_msg["tool_calls"] = [
                    tc.model_dump() for tc in message.tool_calls
                ]
            self.history.append(assistant_msg)

            if finish_reason == "stop":
                return message.content or ""

            elif finish_reason == "tool_calls":
                for tool_call in (message.tool_calls or []):
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments or "{}")

                    print(f"  [tool] Calling {fn_name}({json.dumps(fn_args) if fn_args else ''})")

                    result = call_service(fn_name, fn_args)

                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    })

            else:
                return f"[Stopped: finish_reason={finish_reason}]"

    def reset(self):
        """Clear conversation history."""
        self.history = []
