from pathlib import Path
import requests

ROOT = Path("data/docs")

DOCS = {
"hr/leave_policy.md": """# Nimbus Corp Leave Policy

## Annual leave
Full-time employees receive 24 days of paid annual leave per calendar year.
Up to 8 unused days may be carried over and expire on 31 March of the next year.

## Sick leave
Employees receive 12 days of paid sick leave per year. A medical certificate
is required for absences longer than 3 consecutive days.

## Parental leave
Primary caregivers receive 20 weeks of paid parental leave. Secondary caregivers
receive 6 weeks. Leave must be taken within 12 months of the birth or adoption.

## Approval process
Requests longer than 5 consecutive days must be submitted at least 3 weeks in
advance through the HR portal and approved by the line manager.
""",
"hr/remote_work_policy.txt": """Nimbus Corp Remote Work Policy

Hybrid model: employees work from the office 3 days a week (Tuesday to Thursday).
Fully remote arrangements require written approval from a VP.

Core working hours are 10:00 to 16:00 in the employee's local time zone.

Home office stipend: a one-time $500 payment for equipment, plus $50 per month
towards internet costs.

Working from abroad is allowed for up to 20 days per calendar year. Employees
must notify both HR and IT before travelling.
""",
"it/security_policy.md": """# Nimbus Corp Information Security Policy

## Passwords and access
Passwords must be at least 14 characters long. Multi-factor authentication (MFA)
is mandatory for all company systems. Use of the approved password manager is required.

## Devices
All company laptops use full-disk encryption. A lost or stolen device must be
reported to security@nimbus.example within 1 hour.

## Incident reporting
Severity 1 incidents must be reported to the on-call security engineer within
15 minutes. Severity 2 incidents must be reported within 4 hours.

## Software installation
Only software from the approved catalogue may be installed. New software requests
go through the IT service desk and take up to 5 business days.
""",
"finance/expense_policy.md": """# Nimbus Corp Travel and Expense Policy

## Limits
- Meals: up to $50 per day domestic and $75 per day international.
- Hotels: up to $200 per night.
- Flights: economy class for flights under 6 hours. Business class is allowed for
  flights over 6 hours with VP approval.

## Claims
Receipts are required for any expense above $25. Claims must be submitted within
30 days and are reimbursed within 10 business days. Any single expense over $1,000
requires director approval.
""",
}

for rel, text in DOCS.items():
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    print("wrote", p)