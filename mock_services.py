"""
mock_services.py
----------------
Simulates external data sources that would be called via API in production.

Design decision: Each "service" is a plain function that returns structured data.
In production, these would make HTTP calls to HR systems, payroll APIs, etc.
We keep them as pure functions so they're easy to swap out.

The chatbot calls these via the tool-use mechanism -- the LLM decides WHEN
to call them based on the user's question, not us hard-coding keywords.

Data source: All mock data is loaded from mock_data.json, which can be edited
through the admin panel. This separates data from logic.
"""

import json
import random
from datetime import date
from pathlib import Path
from typing import Any

MOCK_DATA_PATH = Path(__file__).parent / "mock_data.json"

_mock_data: dict = {}


def _load_mock_data() -> dict:
    """Load mock data from JSON file."""
    if not MOCK_DATA_PATH.exists():
        return {}
    with open(MOCK_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def reload_mock_data():
    """Reload mock data from disk. Called after admin edits."""
    global _mock_data
    _mock_data = _load_mock_data()


def get_mock_data() -> dict:
    """Return current mock data (for admin panel)."""
    return _mock_data


def save_mock_data(data: dict):
    """Write mock data back to disk and refresh in-memory copy."""
    global _mock_data
    with open(MOCK_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _mock_data = data


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_employee_id(employee_id: str | None) -> str:
    """Resolve an employee_id, handling None and name-based lookups."""
    if employee_id is None:
        return _mock_data.get("default_employee_id", "E001")

    # If it's already a valid employee ID, return it
    employees = _mock_data.get("employees", {})
    if employee_id in employees:
        return employee_id

    # Try name-based lookup (case-insensitive, partial match)
    search = employee_id.lower().strip()
    for eid, emp in employees.items():
        name = emp.get("name", "").lower()
        if search == name or search in name.split() or name.startswith(search):
            return eid

    # Return as-is (will trigger "not found" error from the service)
    return employee_id


# ── Service functions ────────────────────────────────────────────────────────


def get_vacation_balance(employee_id: str = None) -> dict[str, Any]:
    """
    Return the current vacation day balance for an employee.
    In production: calls the HR system API.
    """
    employee_id = _resolve_employee_id(employee_id)

    emp = _mock_data.get("employees", {}).get(employee_id)
    if not emp:
        return {"error": f"Employee {employee_id} not found"}

    remaining = emp["vacation_days_total"] - emp["vacation_days_used"]
    today = date.today()
    year_end = date(today.year, 12, 31)
    days_until_year_end = (year_end - today).days

    return {
        "employee_name": emp["name"],
        "employee_id": employee_id,
        "vacation_days_total": emp["vacation_days_total"],
        "vacation_days_used": emp["vacation_days_used"],
        "vacation_days_remaining": remaining,
        "days_until_year_end": days_until_year_end,
        "note": "Unused vacation days expire on December 31st.",
    }


def get_upcoming_holidays(country: str = "DE") -> dict[str, Any]:
    """
    Return a list of upcoming public holidays.
    In production: calls a public holiday API.
    """
    today = date.today()
    all_holidays = _mock_data.get("holidays", {}).get(country, [])
    upcoming = [
        h for h in all_holidays
        if date.fromisoformat(h["date"]) >= today
    ][:5]

    return {
        "country": country,
        "upcoming_holidays": upcoming,
        "source": "mock",
    }


def get_learning_budget(employee_id: str = None) -> dict[str, Any]:
    """
    Return the remaining learning & development budget for an employee.
    In production: calls the finance/HR system.
    """
    employee_id = _resolve_employee_id(employee_id)

    emp = _mock_data.get("employees", {}).get(employee_id)
    if not emp:
        return {"error": f"Employee {employee_id} not found"}

    budget_cfg = _mock_data.get("learning_budget", {})
    total = budget_cfg.get("total_eur", 1500.0)
    spent_min = budget_cfg.get("spent_range_min", 200)
    spent_max = budget_cfg.get("spent_range_max", 900)
    spent = round(random.uniform(spent_min, spent_max), 2)

    return {
        "employee_name": emp["name"],
        "learning_budget_total_eur": total,
        "learning_budget_spent_eur": spent,
        "learning_budget_remaining_eur": round(total - spent, 2),
        "year": date.today().year,
        "note": "Budget resets on January 1st each year.",
    }


def get_employee_info(employee_id: str = None) -> dict[str, Any]:
    """
    Return general employee information.
    In production: calls the HR directory API.
    """
    employee_id = _resolve_employee_id(employee_id)

    emp = _mock_data.get("employees", {}).get(employee_id)
    if not emp:
        return {"error": f"Employee {employee_id} not found"}

    return {
        "employee_id": employee_id,
        "name": emp["name"],
        "department": emp["department"],
        "start_date": emp["start_date"],
        "manager": emp["manager"],
        "salary_grade": emp["salary_grade"],
    }


# ── Tool dispatch registry ───────────────────────────────────────────────────

SERVICE_REGISTRY: dict[str, callable] = {
    "get_vacation_balance": get_vacation_balance,
    "get_upcoming_holidays": get_upcoming_holidays,
    "get_learning_budget": get_learning_budget,
    "get_employee_info": get_employee_info,
}


def call_service(tool_name: str, tool_input: dict) -> Any:
    """Dispatch a tool call to the appropriate mock service function."""
    fn = SERVICE_REGISTRY.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(**tool_input)
    except Exception as e:
        return {"error": str(e)}


# Load data on import
_mock_data = _load_mock_data()
