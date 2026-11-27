import re
from datetime import datetime, timezone
from langchain_core.tools import tool
from pymongo import ReturnDocument

from app.core.clients import get_mongo_db
from app.tools.base import ok, fail, safe
from app.tools.schemas import (
    GetCustomerInput, SearchCustomersInput, GetOrderInput, SearchOrdersInput,
    SearchTicketsInput, CreateTicketInput, UpdateTicketStatusInput,
    Customer, Order, Ticket,
)

NO_ID = {"_id": 0}


def _norm(x: str) -> str:
    return x.strip().upper()


def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(s.strip()) 


@tool("get_customer_by_id", args_schema=GetCustomerInput)
@safe
def get_customer_by_id(customer_id: str) -> dict:
    """Get one customer's profile (name, email, tier, country, status) by customer ID like 'C1001'."""
    doc = get_mongo_db().customers.find_one({"customer_id": _norm(customer_id)}, NO_ID)
    if not doc:
        return fail(f"No customer with ID {customer_id}. Try search_customers with a name.")
    return ok(Customer(**doc).model_dump(mode="json"))


@tool("search_customers", args_schema=SearchCustomersInput)
@safe
def search_customers(name_query: str, limit: int = 5) -> dict:
    """Find customers by (partial) name. Use this when you don't have a customer ID."""
    pattern = re.escape(name_query.strip())       
    docs = list(get_mongo_db().customers
                .find({"name": {"$regex": pattern, "$options": "i"}}, NO_ID).limit(limit))
    return ok({"count": len(docs), "customers": [Customer(**d).model_dump(mode="json") for d in docs]})


@tool("get_order_by_id", args_schema=GetOrderInput)
@safe
def get_order_by_id(order_id: str) -> dict:
    """Get one order (items, total, status, date) by order ID like 'O5001'."""
    doc = get_mongo_db().orders.find_one({"order_id": _norm(order_id)}, NO_ID)
    if not doc:
        return fail(f"No order with ID {order_id}.")
    return ok(Order(**doc).model_dump(mode="json"))


@tool("search_orders", args_schema=SearchOrdersInput)
@safe
def search_orders(customer_id: str | None = None, status: str | None = None,
                  min_total: float | None = None, max_total: float | None = None,
                  date_from: str | None = None, date_to: str | None = None,
                  limit: int = 10) -> dict:
    """Search orders by customer, status, total range (USD) and/or date range. Newest first."""
    q: dict = {}
    if customer_id:
        q["customer_id"] = _norm(customer_id)
    if status:
        q["status"] = status
    total = {}
    if min_total is not None:
        total["$gte"] = min_total
    if max_total is not None:
        total["$lte"] = max_total
    if total:
        q["total"] = total
    dates = {}
    if date_from:
        dates["$gte"] = _parse_date(date_from)
    if date_to:
        dates["$lte"] = _parse_date(date_to)
    if dates:
        q["order_date"] = dates

    docs = list(get_mongo_db().orders.find(q, NO_ID).sort("order_date", -1).limit(limit))
    return ok({"count": len(docs), "orders": [Order(**d).model_dump(mode="json") for d in docs]})


@tool("search_tickets", args_schema=SearchTicketsInput)
@safe
def search_tickets(customer_id: str | None = None, status: str | None = None, limit: int = 10) -> dict:
    """Search support tickets by customer ID and/or status. Newest first."""
    q: dict = {}
    if customer_id:
        q["customer_id"] = _norm(customer_id)
    if status:
        q["status"] = status
    docs = list(get_mongo_db().tickets.find(q, NO_ID).sort("created_at", -1).limit(limit))
    return ok({"count": len(docs), "tickets": [Ticket(**d).model_dump(mode="json") for d in docs]})


@tool("create_ticket", args_schema=CreateTicketInput)
@safe
def create_ticket(customer_id: str, subject: str, description: str, priority: str = "medium") -> dict:
    """Create a new support ticket for an existing customer. Returns the new ticket with its ID."""
    db = get_mongo_db()
    cid = _norm(customer_id)
    if not db.customers.find_one({"customer_id": cid}, {"_id": 1}):
        return fail(f"Cannot create ticket: customer {customer_id} does not exist.")

    seq = db.counters.find_one_and_update(
        {"_id": "ticket"}, {"$inc": {"seq": 1}}, upsert=True,
        return_document=ReturnDocument.AFTER)["seq"]

    doc = {"ticket_id": f"T{seq}", "customer_id": cid, "subject": subject,
           "description": description, "status": "open", "priority": priority,
           "created_at": datetime.now(timezone.utc)}
    db.tickets.insert_one(dict(doc))
    return ok(Ticket(**doc).model_dump(mode="json"))


@tool("update_ticket_status", args_schema=UpdateTicketStatusInput)
@safe
def update_ticket_status(ticket_id: str, status: str) -> dict:
    """Change the status of an existing ticket (open, in_progress, resolved, closed)."""
    doc = get_mongo_db().tickets.find_one_and_update(
        {"ticket_id": _norm(ticket_id)}, {"$set": {"status": status}},
        projection=NO_ID, return_document=ReturnDocument.AFTER)
    if not doc:
        return fail(f"No ticket with ID {ticket_id}.")
    return ok(Ticket(**doc).model_dump(mode="json"))