from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders, restock_orders

app = FastAPI(title="Factory Inventory Management System")

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

# Delivery lead time per destination warehouse, in days (fixed for the demo)
LEAD_TIME_DAYS = {
    'San Francisco': 5,
    'London': 10,
    'Tokyo': 14
}
RESTOCK_CUSTOMER = "Internal Restock"

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

def build_restock_recommendations(budget: float, warehouse: Optional[str] = None) -> dict:
    """Greedy budget allocation: restock forecast items with the largest shortfall first.

    Shortfall is forecasted_demand minus quantity_on_hand. Increasing-trend items are
    prioritised because their shortfall will only grow; within a trend group larger
    shortfalls come first. The budget is spent in that order until it runs out, and the
    item that exhausts it receives a partial quantity.
    """
    # Forecasts are keyed by SKU. Each forecast SKU currently maps to exactly one inventory
    # record, so one inventory row yields at most one candidate line.
    # Round once so the echoed budget, total_cost and remaining_budget always add up exactly
    budget = round(budget, 2)
    forecast_by_sku = {f['item_sku']: f for f in demand_forecasts}

    candidates = []
    for item in apply_filters(inventory_items, warehouse):
        forecast = forecast_by_sku.get(item['sku'])
        if not forecast:
            continue
        shortfall = forecast['forecasted_demand'] - item['quantity_on_hand']
        # Fully stocked items and zero-cost items (would divide by zero below) are skipped
        if shortfall <= 0 or item['unit_cost'] <= 0:
            continue
        candidates.append({
            'sku': item['sku'],
            'name': item['name'],
            'category': item['category'],
            'warehouse': item['warehouse'],
            'quantity_on_hand': item['quantity_on_hand'],
            'forecasted_demand': forecast['forecasted_demand'],
            'shortfall': shortfall,
            'unit_cost': item['unit_cost'],
            'trend': forecast['trend']
        })

    # False sorts before True, so increasing-trend items come first; then largest shortfall
    candidates.sort(key=lambda c: (c['trend'] != 'increasing', -c['shortfall']))
    total_shortfall_cost = round(sum(c['shortfall'] * c['unit_cost'] for c in candidates), 2)

    # Work in integer cents so floor division is not corrupted by float rounding
    remaining_cents = round(budget * 100)
    lines = []
    for c in candidates:
        unit_cents = round(c['unit_cost'] * 100)
        # Partial fill: buy as many units as the remaining budget allows, capped at the shortfall
        qty = min(c['shortfall'], remaining_cents // unit_cents)
        if qty <= 0:
            # Too expensive for what is left; a cheaper item later in the list may still fit
            continue
        remaining_cents -= qty * unit_cents
        lines.append({
            **c,
            'recommended_qty': qty,
            'line_cost': qty * unit_cents / 100,
            'partial': qty < c['shortfall']
        })
        if remaining_cents == 0:
            break

    return {
        'budget': budget,
        'warehouse': warehouse if warehouse and warehouse != 'all' else 'all',
        'lead_time_days': LEAD_TIME_DAYS.get(warehouse),
        'lines': lines,
        'total_cost': round(budget - remaining_cents / 100, 2),
        'remaining_budget': remaining_cents / 100,
        'total_shortfall_cost': total_shortfall_cost,
        'items_with_shortfall': len(candidates)
    }

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

# API endpoints
class RestockLine(BaseModel):
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    forecasted_demand: int
    shortfall: int
    unit_cost: float
    recommended_qty: int
    line_cost: float
    trend: str
    partial: bool

class RestockRecommendations(BaseModel):
    budget: float
    warehouse: str
    lead_time_days: Optional[int] = None
    lines: List[RestockLine]
    total_cost: float
    remaining_budget: float
    total_shortfall_cost: float
    items_with_shortfall: int

class RestockOrderItemRequest(BaseModel):
    sku: str
    quantity: int = Field(..., gt=0)

class CreateRestockOrderRequest(BaseModel):
    warehouse: str
    items: List[RestockOrderItemRequest] = Field(..., min_length=1)

class RestockOrderItem(BaseModel):
    sku: str
    name: str
    quantity: int
    # Named unit_price (not unit_cost) to match Order.items so the Orders view renders both alike
    unit_price: float
    line_cost: float

class RestockOrder(BaseModel):
    id: str
    order_number: str
    customer: str
    warehouse: str
    items: List[RestockOrderItem]
    status: str
    order_date: str
    lead_time_days: int
    expected_delivery: str
    total_value: float

@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/restock/recommendations", response_model=RestockRecommendations)
def get_restock_recommendations(
    budget: float = Query(..., ge=0),
    warehouse: Optional[str] = None
):
    """Recommend forecast items to restock within a budget (ge=0 turns negative budgets into 422)"""
    # Mirror the POST handler: an unknown warehouse is a client error, not an empty result
    if warehouse and warehouse != 'all' and warehouse not in LEAD_TIME_DAYS:
        raise HTTPException(status_code=400, detail=f"Unknown warehouse: {warehouse}")
    return build_restock_recommendations(budget, warehouse)

@app.get("/api/restock-orders", response_model=List[RestockOrder])
def get_restock_orders(warehouse: Optional[str] = None):
    """List restock orders submitted during this server run"""
    return apply_filters(restock_orders, warehouse)

@app.post("/api/restock-orders", response_model=RestockOrder, status_code=201)
def create_restock_order(request: CreateRestockOrderRequest):
    """Submit a restock order; lead time is fixed per destination warehouse"""
    lead_time = LEAD_TIME_DAYS.get(request.warehouse)
    if lead_time is None:
        raise HTTPException(status_code=400, detail=f"Unknown warehouse: {request.warehouse}")

    items = []
    for line in request.items:
        # Match on SKU and warehouse so the price comes from the destination's own inventory
        # record; the client never supplies prices.
        inventory_item = next(
            (i for i in inventory_items if i['sku'] == line.sku and i['warehouse'] == request.warehouse),
            None
        )
        if not inventory_item:
            raise HTTPException(status_code=400, detail=f"SKU {line.sku} not found in {request.warehouse}")
        unit_price = inventory_item['unit_cost']
        items.append(RestockOrderItem(
            sku=line.sku,
            name=inventory_item['name'],
            quantity=line.quantity,
            unit_price=unit_price,
            line_cost=round(line.quantity * unit_price, 2)
        ))

    now = datetime.now().replace(microsecond=0)
    sequence = len(restock_orders) + 1
    order = RestockOrder(
        id=str(sequence),
        order_number=f"RST-{now.year}-{sequence:04d}",
        customer=RESTOCK_CUSTOMER,
        warehouse=request.warehouse,
        items=items,
        status="Submitted",
        order_date=now.isoformat(),
        lead_time_days=lead_time,
        expected_delivery=(now + timedelta(days=lead_time)).isoformat(),
        total_value=round(sum(i.line_cost for i in items), 2)
    )
    # Stored as a plain dict so apply_filters can treat it like the JSON-loaded orders.
    # Deliberately NOT added to `orders`, so dashboard totals and status filters are unaffected.
    restock_orders.append(order.model_dump())
    return order

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        has_po = any(po["backlog_item_id"] == item["id"] for po in purchase_orders)
        item_dict["has_purchase_order"] = has_po
        result.append(item_dict)
    return result

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
