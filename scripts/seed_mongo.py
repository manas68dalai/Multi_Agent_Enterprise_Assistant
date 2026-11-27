import random
from datetime import datetime, timedelta, timezone
from app.core.clients import get_mongo_db

random.seed(42)                    
db = get_mongo_db()
for name in ("customers", "orders", "tickets", "counters"):
    db[name].drop()

now = datetime.now(timezone.utc)
PEOPLE = [("Aarav Sharma", "India"), ("Priya Patel", "India"), ("Liam Johnson", "USA"),
          ("Emma Davis", "USA"), ("Noah Mueller", "Germany"), ("Sofia Rossi", "Italy"),
          ("Yuki Tanaka", "Japan"), ("Olivia Brown", "UK"), ("Mateo Garcia", "Spain"),
          ("Chen Wei", "China"), ("Fatima Khan", "UAE"), ("Lucas Silva", "Brazil")]
PRODUCTS = [("SKU-100", "Laptop Pro 14", 1299.0), ("SKU-101", "Wireless Mouse", 29.99),
            ("SKU-102", "USB-C Dock", 149.0), ("SKU-103", "Monitor 27in", 329.0),
            ("SKU-104", "Mechanical Keyboard", 89.0), ("SKU-105", "Noise-Cancelling Headset", 199.0)]
SUBJECTS = [("Laptop will not boot", "After the latest update the laptop shows a black screen on startup."),
            ("VPN keeps disconnecting", "VPN drops every 10 minutes when working from home."),
            ("Order arrived damaged", "The monitor screen was cracked when the package arrived."),
            ("Cannot reset password", "The password reset email never arrives in my inbox."),
            ("Refund not received", "My refund was approved two weeks ago but has not arrived.")]

customers = []
for i, (name, country) in enumerate(PEOPLE):
    customers.append({
        "customer_id": f"C{1001 + i}", "name": name,
        "email": name.lower().replace(" ", ".") + "@example.com",
        "tier": random.choice(["standard", "standard", "gold", "platinum"]),
        "country": country, "status": "suspended" if i == 9 else "active",
        "signup_date": now - timedelta(days=random.randint(100, 900)),
    })
db.customers.insert_many(customers)

orders = []
for i in range(40):
    items = []
    for sku, pname, price in random.sample(PRODUCTS, random.randint(1, 3)):
        items.append({"sku": sku, "name": pname, "qty": random.randint(1, 2), "price": price})
    orders.append({
        "order_id": f"O{5001 + i}", "customer_id": random.choice(customers)["customer_id"],
        "items": items, "total": round(sum(x["qty"] * x["price"] for x in items), 2),
        "currency": "USD",
        "status": random.choices(["processing", "shipped", "delivered", "cancelled", "refunded"],
                                 weights=[2, 3, 6, 1, 1])[0],
        "order_date": now - timedelta(days=random.randint(1, 120)),
    })
db.orders.insert_many(orders)

tickets = []
for i in range(15):
    subject, desc = random.choice(SUBJECTS)
    tickets.append({
        "ticket_id": f"T{9001 + i}", "customer_id": random.choice(customers)["customer_id"],
        "subject": subject, "description": desc,
        "status": random.choice(["open", "open", "in_progress", "resolved", "closed"]),
        "priority": random.choice(["low", "medium", "medium", "high", "urgent"]),
        "created_at": now - timedelta(days=random.randint(0, 60)),
    })
db.tickets.insert_many(tickets)
db.counters.insert_one({"_id": "ticket", "seq": 9000 + len(tickets)})   # next ticket = T9016

db.customers.create_index("customer_id", unique=True)
db.orders.create_index("order_id", unique=True)
db.orders.create_index([("customer_id", 1), ("status", 1)])
db.tickets.create_index("ticket_id", unique=True)

print(f"Seeded {len(customers)} customers, {len(orders)} orders, {len(tickets)} tickets")