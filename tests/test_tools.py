
import json

from app.tools import (
    get_customer_by_id,
    search_customers,
    search_orders,
    get_order_by_id,
    search_tickets,
    create_ticket,
    get_weather,
    convert_currency,
    search_knowledge_base,
    RESEARCH_TOOLS,
    DATA_TOOLS,
    TASK_TOOLS,
)

from app.core.llm import get_llm

def show(title, result):
    print(f"\n--- {title}\n{json.dumps(result, indent=1, default=str)[:500]}")

show("customer", get_customer_by_id.invoke({"customer_id": "c1001"}))
show("customer NOT FOUND", get_customer_by_id.invoke({"customer_id": "C9999"}))
show("name search", search_customers.invoke({"name_query": "sharma"}))
show("orders shipped > $500", search_orders.invoke({"status": "shipped", "min_total": 500, "limit": 3}))
show("bad date", search_orders.invoke({"date_from": "not-a-date"}))
show("open tickets", search_tickets.invoke({"status": "open", "limit": 2}))
show("create ticket", create_ticket.invoke({"customer_id": "C1002", "subject": "Test ticket from tool test", "description": "Checking that ticket creation works end to end.",}))
show("weather", get_weather.invoke({"city": "Berlin"}))
show("currency", convert_currency.invoke({"amount": 250, "from_currency": "usd","to_currency": "inr",}))
show("bad currency", convert_currency.invoke({"amount": 10, "from_currency": "USD", "to_currency": "XXX",}))

def kb_scores(q):
    r = search_knowledge_base.invoke({"query": q})

    return (
        r["error"]
        if not r["ok"]
        else [(c["source"], c["score"]) for c in r["data"]]
    )

show("kb", kb_scores("How many sick days do employees get?"))
show("kb unrelated (should say not found)", kb_scores("best pizza recipe with mushrooms"))

CASES = [
    ("Look up customer C1002", "get_customer_by_id", DATA_TOOLS),
    ("Find the customer named Sharma", "search_customers", DATA_TOOLS),
    ("What is the status of order O5001?", "get_order_by_id", DATA_TOOLS),
    ("Show shipped orders for C1003 over $500", "search_orders", DATA_TOOLS),
    ("List open tickets for C1004", "search_tickets", DATA_TOOLS),
    ("What's the weather in Berlin right now?", "get_weather", RESEARCH_TOOLS),
    ("Convert 250 USD to INR", "convert_currency", RESEARCH_TOOLS),
    ("How many sick days do employees get?", "search_knowledge_base", RESEARCH_TOOLS),
    ("Create a high priority ticket for C1001: laptop will not boot after update",
     "create_ticket", TASK_TOOLS),
    ("Close ticket T9001", "update_ticket_status", TASK_TOOLS),
]

# PART 4: RUN LLM TOOL-SELECTION TESTS

llm = get_llm()
passed = 0
print("\n\n=== LLM tool-selection test ===")
for prompt, expected, tools in CASES:
    resp = llm.bind_tools(tools).invoke(prompt)
    calls = resp.tool_calls
    ok_ = bool(calls) and calls[0]["name"] == expected
    passed += ok_
    print(
        f"{'PASS' if ok_ else 'FAIL'} | {prompt}\n"
        f"       -> {[(c['name'], c['args']) for c in calls]}"
    )

# PART 5: FINAL SUMMARY

accuracy = passed / len(CASES) if CASES else 0

print("\n===================================")
print("       TEST EXECUTION SUMMARY")
print("===================================")

print(f"Total test cases : {len(CASES)}")
print(f"Passed           : {passed}")
print(f"Failed           : {len(CASES) - passed}")
print(f"Accuracy         : {accuracy:.0%}")

print("===================================")
