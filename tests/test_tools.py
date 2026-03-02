"""Tests for tools.py — API config loading and Groq tool definitions."""

import json
import pytest
from pathlib import Path

from tools import (
    load_api_config,
    build_groq_tool_definitions,
    get_api_config,
    reload_tool_definitions,
    GROQ_TOOL_DEFINITIONS,
    API_CONFIG_PATH,
)


class TestLoadApiConfig:
    def test_loads_config(self):
        config = load_api_config()
        assert "tools" in config
        assert len(config["tools"]) == 4

    def test_tool_names(self):
        config = load_api_config()
        names = [t["name"] for t in config["tools"]]
        assert "get_vacation_balance" in names
        assert "get_upcoming_holidays" in names
        assert "get_learning_budget" in names
        assert "get_employee_info" in names

    def test_tools_have_required_fields(self):
        config = load_api_config()
        for tool in config["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool
            assert "enabled" in tool
            assert "category" in tool


class TestBuildGroqToolDefinitions:
    def test_builds_all_enabled(self):
        config = load_api_config()
        defs = build_groq_tool_definitions(config)
        assert len(defs) == 4
        for d in defs:
            assert d["type"] == "function"
            assert "name" in d["function"]
            assert "description" in d["function"]
            assert "parameters" in d["function"]

    def test_skips_disabled_tools(self):
        config = {
            "tools": [
                {"name": "enabled_tool", "enabled": True, "description": "test",
                 "parameters": {"type": "object", "properties": {}}},
                {"name": "disabled_tool", "enabled": False, "description": "test",
                 "parameters": {"type": "object", "properties": {}}},
            ]
        }
        defs = build_groq_tool_definitions(config)
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "enabled_tool"

    def test_empty_tools(self):
        defs = build_groq_tool_definitions({"tools": []})
        assert defs == []


class TestModuleLevelDefinitions:
    def test_groq_tool_definitions_loaded(self):
        assert len(GROQ_TOOL_DEFINITIONS) == 4

    def test_reload_returns_definitions(self):
        defs = reload_tool_definitions()
        assert len(defs) == 4


class TestGetApiConfig:
    def test_returns_config(self):
        config = get_api_config()
        assert "tools" in config
