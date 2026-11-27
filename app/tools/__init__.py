from app.tools.mongo_tools import (
    get_customer_by_id, search_customers, get_order_by_id, search_orders,
    search_tickets, create_ticket, update_ticket_status,
)
from app.tools.api_tools import get_weather, convert_currency
from app.tools.knowledge_tools import search_knowledge_base

RESEARCH_TOOLS = [search_knowledge_base, get_weather, convert_currency]
DATA_TOOLS = [get_customer_by_id, search_customers, get_order_by_id, search_orders, search_tickets]
TASK_TOOLS = [create_ticket, update_ticket_status]
ALL_TOOLS = RESEARCH_TOOLS + DATA_TOOLS + TASK_TOOLS