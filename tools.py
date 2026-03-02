"""
tools.py
--------
Tool definitions for the chatbot, loaded dynamically from api_config.json.

The api_config.json file uses an MCP-inspired format where each tool is a
configurable resource with metadata (category, enabled flag, production endpoint).
This module converts those definitions into the Groq/OpenAI tool format:

  {
    "type": "function",
    "function": {
      "name": ...,
      "description": ...,
      "parameters": { ... }
    }
  }

Admin panel can toggle tools on/off and reload definitions at runtime.
"""

import json
from pathlib import Path

API_CONFIG_PATH = Path(__file__).parent / "api_config.json"


def load_api_config() -> dict:
    """Load the MCP-inspired API configuration from disk."""
    if not API_CONFIG_PATH.exists():
        return {"tools": []}
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_api_config(config: dict) -> None:
    """Save the API configuration back to disk."""
    with open(API_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_api_config() -> dict:
    """Return the raw API config for the admin panel."""
    return load_api_config()


def build_groq_tool_definitions(config: dict) -> list[dict]:
    """Convert api_config.json tools into Groq/OpenAI tool format.
    Only includes tools where enabled=True."""
    definitions = []
    for tool in config.get("tools", []):
        if not tool.get("enabled", True):
            continue
        definitions.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        })
    return definitions


def reload_tool_definitions() -> list[dict]:
    """Re-read config from disk and rebuild definitions."""
    global GROQ_TOOL_DEFINITIONS
    config = load_api_config()
    GROQ_TOOL_DEFINITIONS = build_groq_tool_definitions(config)
    return GROQ_TOOL_DEFINITIONS


# Initialize at import time
_config = load_api_config()
GROQ_TOOL_DEFINITIONS = build_groq_tool_definitions(_config)
