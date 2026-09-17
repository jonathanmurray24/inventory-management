"""
Tests for restocking API endpoints (recommendations and restock orders).
"""
import re
from datetime import datetime, timedelta

import pytest


RECOMMENDATIONS_URL = "/api/restock/recommendations"
ORDERS_URL = "/api/restock-orders"
LEAD_TIME_DAYS = {"San Francisco": 5, "London": 10, "Tokyo": 14}


def _recommendations(client, budget, warehouse=None):
    """Helper to fetch recommendations and assert a 200 response."""
    url = f"{RECOMMENDATIONS_URL}?budget={budget}"
    if warehouse:
        url += f"&warehouse={warehouse}"
    response = client.get(url)
    assert response.status_code == 200
    return response.json()


def _order_payload(client, warehouse):
    """Build a valid POST payload from the full-budget recommendations for a warehouse."""
    data = _recommendations(client, 1_000_000, warehouse)
    assert len(data["lines"]) > 0, f"Expected shortfall lines for {warehouse}"
    return {
        "warehouse": warehouse,
        "items": [{"sku": line["sku"], "quantity": line["recommended_qty"]} for line in data["lines"]]
    }


class TestRestockData:
    """Test suite for the data relationship the restocking feature depends on."""

    def test_every_forecast_sku_has_inventory_record(self, client):
        """Test that each demand forecast SKU exists in inventory."""
        forecast_skus = {f["item_sku"] for f in client.get("/api/demand").json()}
        inventory_skus = {i["sku"] for i in client.get("/api/inventory").json()}

        missing = forecast_skus - inventory_skus
        assert not missing, f"Forecast SKUs missing from inventory: {sorted(missing)}"


class TestRestockRecommendationEndpoints:
    """Test suite for the budget-driven recommendation endpoint."""

    def test_zero_budget_returns_no_lines(self, client):
        """Test that a zero budget yields no lines but still reports the shortfall."""
        data = _recommendations(client, 0)

        assert data["lines"] == []
        assert data["total_cost"] == 0
        assert data["remaining_budget"] == 0
        assert data["total_shortfall_cost"] > 0
        assert data["items_with_shortfall"] > 0
        assert data["warehouse"] == "all"
        assert data["lead_time_days"] is None

    def test_recommendation_line_structure(self, client):
        """Test that recommendation lines have the expected fields and types."""
        data = _recommendations(client, 5000)
        assert len(data["lines"]) > 0

        line = data["lines"][0]
        for field in ["sku", "name", "category", "warehouse", "quantity_on_hand",
                      "forecasted_demand", "shortfall", "unit_cost", "recommended_qty",
                      "line_cost", "trend", "partial"]:
            assert field in line, f"Missing field {field}"
        assert isinstance(line["recommended_qty"], int)
        assert isinstance(line["partial"], bool)
        assert line["recommended_qty"] > 0
        assert line["shortfall"] == line["forecasted_demand"] - line["quantity_on_hand"]

    def test_small_budget_yields_single_partial_line(self, client):
        """Test that a budget below the first item's cost produces one partial line."""
        data = _recommendations(client, 100)

        assert len(data["lines"]) == 1
        line = data["lines"][0]
        assert line["partial"] is True
        assert line["line_cost"] <= 100
        expected_qty = int(100 * 100 // round(line["unit_cost"] * 100))
        assert line["recommended_qty"] == expected_qty

    def test_large_budget_covers_all_shortfalls(self, client):
        """Test that an ample budget fully restocks every item with a shortfall."""
        data = _recommendations(client, 1_000_000)

        assert len(data["lines"]) == data["items_with_shortfall"]
        for line in data["lines"]:
            assert line["recommended_qty"] == line["shortfall"]
            assert line["partial"] is False
        assert abs(data["total_cost"] - data["total_shortfall_cost"]) < 0.01

    def test_lines_sorted_increasing_first_then_shortfall_desc(self, client):
        """Test that increasing-trend items come first, each group by shortfall descending."""
        data = _recommendations(client, 1_000_000)
        lines = data["lines"]
        assert len(lines) > 1

        sort_keys = [(line["trend"] != "increasing", -line["shortfall"]) for line in lines]
        assert sort_keys == sorted(sort_keys), "Lines are not in priority order"

    def test_remaining_plus_total_equals_budget(self, client):
        """Test that allocated and remaining amounts add back up to the budget."""
        budget = 12500
        data = _recommendations(client, budget)

        assert abs(data["total_cost"] + data["remaining_budget"] - budget) < 0.01
        line_sum = sum(line["line_cost"] for line in data["lines"])
        assert abs(line_sum - data["total_cost"]) < 0.01

    def test_warehouse_filter_limits_lines_and_sets_lead_time(self, client):
        """Test that filtering by warehouse restricts lines and reports its lead time."""
        data = _recommendations(client, 1_000_000, "London")

        assert len(data["lines"]) > 0
        for line in data["lines"]:
            assert line["warehouse"] == "London"
        assert data["warehouse"] == "London"
        assert data["lead_time_days"] == LEAD_TIME_DAYS["London"]

    def test_fully_stocked_items_excluded(self, client):
        """Test that items whose stock already meets the forecast are not recommended."""
        data = _recommendations(client, 1_000_000)
        skus = {line["sku"] for line in data["lines"]}

        # MTR-304 has decreasing demand below stock; PSU-501 has 420 on hand vs 252 forecast
        assert "MTR-304" not in skus
        assert "PSU-501" not in skus

    def test_negative_budget_returns_422(self, client):
        """Test that a negative budget is rejected by validation."""
        response = client.get(f"{RECOMMENDATIONS_URL}?budget=-5")
        assert response.status_code == 422

    def test_unknown_warehouse_returns_400(self, client):
        """Test that an unknown warehouse filter is rejected rather than returning empty results."""
        response = client.get(f"{RECOMMENDATIONS_URL}?budget=1000&warehouse=Paris")
        assert response.status_code == 400
        assert "warehouse" in response.json()["detail"].lower()

    def test_all_warehouse_value_is_accepted(self, client):
        """Test that warehouse=all behaves the same as no warehouse filter."""
        data = _recommendations(client, 1_000_000, "all")
        unfiltered = _recommendations(client, 1_000_000)
        assert data["warehouse"] == "all"
        assert len(data["lines"]) == len(unfiltered["lines"])

    def test_budget_is_rounded_to_cents(self, client):
        """Test that sub-cent budgets are rounded so totals add back up exactly."""
        data = _recommendations(client, 100.005)
        assert data["budget"] in (100.0, 100.01)
        assert abs(data["total_cost"] + data["remaining_budget"] - data["budget"]) < 0.001

    def test_missing_budget_returns_422(self, client):
        """Test that budget is a required query parameter."""
        response = client.get(RECOMMENDATIONS_URL)
        assert response.status_code == 422


class TestRestockOrderEndpoints:
    """Test suite for creating and listing restock orders."""

    def test_list_orders_empty_initially(self, client):
        """Test that no restock orders exist at the start of a test."""
        response = client.get(ORDERS_URL)
        assert response.status_code == 200
        assert response.json() == []

    def test_create_order_success(self, client):
        """Test creating a restock order from recommendations."""
        payload = _order_payload(client, "San Francisco")
        response = client.post(ORDERS_URL, json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["customer"] == "Internal Restock"
        assert order["warehouse"] == "San Francisco"
        assert re.fullmatch(r"RST-\d{4}-\d{4}", order["order_number"])
        assert len(order["items"]) == len(payload["items"])

        for item in order["items"]:
            assert "sku" in item
            assert "name" in item
            assert "unit_price" in item
            assert abs(item["line_cost"] - item["quantity"] * item["unit_price"]) < 0.01

        calculated_total = sum(item["quantity"] * item["unit_price"] for item in order["items"])
        assert abs(order["total_value"] - calculated_total) < 0.01

    @pytest.mark.parametrize("warehouse", ["San Francisco", "London", "Tokyo"])
    def test_lead_time_by_warehouse(self, client, warehouse):
        """Test that lead time is assigned per destination warehouse."""
        first_sku = client.get(f"/api/inventory?warehouse={warehouse}").json()[0]["sku"]
        response = client.post(ORDERS_URL, json={
            "warehouse": warehouse,
            "items": [{"sku": first_sku, "quantity": 1}]
        })
        assert response.status_code == 201
        assert response.json()["lead_time_days"] == LEAD_TIME_DAYS[warehouse]

    def test_expected_delivery_equals_order_date_plus_lead_time(self, client):
        """Test that expected delivery is derived from order date and lead time."""
        response = client.post(ORDERS_URL, json=_order_payload(client, "Tokyo"))
        order = response.json()

        order_date = datetime.fromisoformat(order["order_date"])
        expected = datetime.fromisoformat(order["expected_delivery"])
        assert expected - order_date == timedelta(days=order["lead_time_days"])

    def test_order_numbers_increment(self, client):
        """Test that consecutive orders get sequential order numbers."""
        payload = _order_payload(client, "London")
        first = client.post(ORDERS_URL, json=payload).json()
        second = client.post(ORDERS_URL, json=payload).json()

        assert first["order_number"].endswith("-0001")
        assert second["order_number"].endswith("-0002")
        assert first["id"] != second["id"]

    def test_unit_price_comes_from_inventory(self, client):
        """Test that line prices are taken from the inventory record, not the client."""
        inventory = {i["sku"]: i for i in client.get("/api/inventory?warehouse=Tokyo").json()}
        response = client.post(ORDERS_URL, json={
            "warehouse": "Tokyo",
            "items": [{"sku": "GSK-203", "quantity": 10}]
        })
        assert response.status_code == 201

        item = response.json()["items"][0]
        assert item["unit_price"] == inventory["GSK-203"]["unit_cost"]
        assert item["name"] == inventory["GSK-203"]["name"]

    def test_empty_items_returns_422(self, client):
        """Test that an order with no items fails validation."""
        response = client.post(ORDERS_URL, json={"warehouse": "Tokyo", "items": []})
        assert response.status_code == 422

    def test_zero_quantity_returns_422(self, client):
        """Test that a non-positive quantity fails validation."""
        response = client.post(ORDERS_URL, json={
            "warehouse": "Tokyo",
            "items": [{"sku": "GSK-203", "quantity": 0}]
        })
        assert response.status_code == 422

    def test_unknown_warehouse_returns_400(self, client):
        """Test that an unknown destination warehouse is rejected."""
        response = client.post(ORDERS_URL, json={
            "warehouse": "Paris",
            "items": [{"sku": "GSK-203", "quantity": 1}]
        })
        assert response.status_code == 400
        assert "warehouse" in response.json()["detail"].lower()

    def test_unknown_sku_returns_400(self, client):
        """Test that a SKU not stocked at the destination warehouse is rejected."""
        # WDG-001 is stocked in San Francisco, not Tokyo
        response = client.post(ORDERS_URL, json={
            "warehouse": "Tokyo",
            "items": [{"sku": "WDG-001", "quantity": 1}]
        })
        assert response.status_code == 400
        assert "WDG-001" in response.json()["detail"]

    def test_list_orders_after_create_and_warehouse_filter(self, client):
        """Test that created orders are listed and the warehouse filter applies."""
        client.post(ORDERS_URL, json=_order_payload(client, "San Francisco"))

        assert len(client.get(ORDERS_URL).json()) == 1
        assert len(client.get(f"{ORDERS_URL}?warehouse=San Francisco").json()) == 1
        assert client.get(f"{ORDERS_URL}?warehouse=Tokyo").json() == []
        assert len(client.get(f"{ORDERS_URL}?warehouse=all").json()) == 1

    def test_restock_orders_not_in_customer_orders(self, client):
        """Test that submitting a restock order does not alter the customer orders list."""
        before = len(client.get("/api/orders").json())
        client.post(ORDERS_URL, json=_order_payload(client, "London"))
        after = len(client.get("/api/orders").json())

        assert before == after
