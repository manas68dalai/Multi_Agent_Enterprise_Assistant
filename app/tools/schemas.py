from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

OrderStatus = Literal["processing", "shipped", "delivered", "cancelled", "refunded"]
TicketStatus = Literal["open", "in_progress", "resolved", "closed"]
Priority = Literal["low", "medium", "high", "urgent"]

class GetCustomerInput(BaseModel):
    customer_id: str = Field(description="Customer ID, e.g. 'C1001'")


class SearchCustomersInput(BaseModel):
    name_query: str = Field(min_length=2, description="Part of the customer's name, e.g. 'sharma'")
    limit: int = Field(5, ge=1, description="Max rows to return (the server caps this at 20)")


class GetOrderInput(BaseModel):
    order_id: str = Field(description="Order ID, e.g. 'O5001'")


class SearchOrdersInput(BaseModel):
    customer_id: Optional[str] = Field(None, description="Filter by customer ID, e.g. 'C1001'")
    status: Optional[OrderStatus] = Field(None, description="Filter by order status")
    min_total: Optional[float] = Field(None, ge=0, description="Minimum order total in USD")
    max_total: Optional[float] = Field(None, ge=0, description="Maximum order total in USD")
    date_from: Optional[str] = Field(None, description="Earliest order date, YYYY-MM-DD")
    date_to: Optional[str] = Field(None, description="Latest order date, YYYY-MM-DD")
    limit: int = Field(10, ge=1, description="Max rows to return (the server caps this at 20)")


class SearchTicketsInput(BaseModel):
    customer_id: Optional[str] = Field(None, description="Filter by customer ID")
    status: Optional[TicketStatus] = Field(None, description="Filter by ticket status")
    limit: int = Field(10, ge=1, description="Max rows to return (the server caps this at 20)")


class CreateTicketInput(BaseModel):
    customer_id: str = Field(description="Customer ID the ticket is for, e.g. 'C1001'")
    subject: str = Field(min_length=5, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    priority: Priority = "medium"


class UpdateTicketStatusInput(BaseModel):
    ticket_id: str = Field(description="Ticket ID, e.g. 'T9001'")
    status: TicketStatus


class WeatherInput(BaseModel):
    city: str = Field(min_length=2, description="City name, e.g. 'Berlin'")


class ConvertCurrencyInput(BaseModel):
    amount: float = Field(gt=0)
    from_currency: str = Field(min_length=3, max_length=3, description="ISO code, e.g. 'USD'")
    to_currency: str = Field(min_length=3, max_length=3, description="ISO code, e.g. 'INR'")


class KBSearchInput(BaseModel):
    query: str = Field(min_length=3, description="Natural-language question about company policy")
    doc_type: Optional[Literal["hr", "it", "finance", "general"]] = Field(
        None, description="Optional category filter: hr, it, finance")


# Structured Output schemas
class Customer(BaseModel):
    customer_id: str
    name: str
    email: str
    tier: str
    country: str
    status: str
    signup_date: datetime


class OrderItem(BaseModel):
    sku: str
    name: str
    qty: int
    price: float


class Order(BaseModel):
    order_id: str
    customer_id: str
    items: list[OrderItem]
    total: float
    currency: str = "USD"
    status: OrderStatus
    order_date: datetime


class Ticket(BaseModel):
    ticket_id: str
    customer_id: str
    subject: str
    description: str
    status: TicketStatus
    priority: Priority
    created_at: datetime


class Weather(BaseModel):
    city: str
    country: str
    temperature_c: float
    humidity_pct: float
    wind_kmh: float
    conditions: str


class Conversion(BaseModel):
    amount: float
    from_currency: str
    to_currency: str
    rate: float
    converted: float
    rate_date: str


class KBChunk(BaseModel):
    source: str
    doc_type: str
    page: Optional[int] = None
    score: float
    text: str