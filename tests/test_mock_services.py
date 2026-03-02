"""Tests for mock_services.py — mock HR data services."""

import pytest

from mock_services import (
    call_service,
    get_vacation_balance,
    get_upcoming_holidays,
    get_learning_budget,
    get_employee_info,
    reload_mock_data,
    get_mock_data,
    SERVICE_REGISTRY,
)


@pytest.fixture(autouse=True)
def fresh_data():
    """Ensure mock data is loaded from disk before each test."""
    reload_mock_data()


class TestServiceRegistry:
    def test_has_all_services(self):
        expected = {"get_vacation_balance", "get_upcoming_holidays",
                    "get_learning_budget", "get_employee_info"}
        assert set(SERVICE_REGISTRY.keys()) == expected

    def test_call_service_dispatches(self):
        result = call_service("get_vacation_balance", {"employee_id": "E001"})
        assert "vacation_days_remaining" in result

    def test_call_service_unknown_tool(self):
        result = call_service("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]


class TestVacationBalance:
    def test_valid_employee(self):
        result = get_vacation_balance("E001")
        assert result["employee_name"] == "Alice Mueller"
        assert result["vacation_days_total"] == 25
        assert result["vacation_days_used"] == 14
        assert result["vacation_days_remaining"] == 11
        assert "days_until_year_end" in result

    def test_unknown_employee(self):
        result = get_vacation_balance("EXXXX")
        assert "error" in result

    def test_default_employee(self):
        result = get_vacation_balance(None)
        assert "employee_name" in result


class TestUpcomingHolidays:
    def test_germany(self):
        result = get_upcoming_holidays("DE")
        assert result["country"] == "DE"
        assert "upcoming_holidays" in result
        assert isinstance(result["upcoming_holidays"], list)

    def test_unknown_country_returns_empty(self):
        result = get_upcoming_holidays("XX")
        assert result["upcoming_holidays"] == []


class TestLearningBudget:
    def test_valid_employee(self):
        result = get_learning_budget("E001")
        assert result["employee_name"] == "Alice Mueller"
        assert result["learning_budget_total_eur"] == 1500.0
        assert result["learning_budget_remaining_eur"] >= 0

    def test_unknown_employee(self):
        result = get_learning_budget("EXXXX")
        assert "error" in result


class TestEmployeeInfo:
    def test_valid_employee(self):
        result = get_employee_info("E001")
        assert result["name"] == "Alice Mueller"
        assert result["department"] == "Recruitment"
        assert result["manager"] == "Bob Schmidt"
        assert result["salary_grade"] == "IC4"

    def test_employee_bob(self):
        result = get_employee_info("E002")
        assert result["name"] == "Bob Schmidt"
        assert result["department"] == "Staffing Solutions"

    def test_unknown_employee(self):
        result = get_employee_info("EXXXX")
        assert "error" in result

    def test_name_lookup(self):
        result = get_employee_info("Alice")
        assert result["name"] == "Alice Mueller"


class TestMockData:
    def test_get_mock_data_has_employees(self):
        data = get_mock_data()
        assert "E001" in data["employees"]
        assert "E002" in data["employees"]

    def test_get_mock_data_has_holidays(self):
        data = get_mock_data()
        assert "DE" in data["holidays"]
        assert len(data["holidays"]["DE"]) >= 5
