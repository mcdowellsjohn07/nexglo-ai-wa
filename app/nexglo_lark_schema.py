"""NexgloTV Lark Base (Bitable) field schemas — 18 tables.

Source of truth: NexgloTV_Lark_CRM_Import_18_Tables.xlsx (owner-provided).
Field JSON uses Lark's native +table-create / +field-create format.
"""

from __future__ import annotations


def _text(name: str, desc: str = "") -> dict:
    d = {"name": name, "type": "text"}
    if desc:
        d["description"] = desc
    return d


def _number(name: str, precision: int = 0) -> dict:
    return {"name": name, "type": "number", "style": {"type": "plain", "precision": precision}}


def _select(name: str, options: list[str]) -> dict:
    return {"name": name, "type": "select", "multiple": False,
            "options": [{"name": o} for o in options]}


def _datetime(name: str) -> dict:
    return {"name": name, "type": "datetime"}


def _checkbox(name: str) -> dict:
    return {"name": name, "type": "checkbox"}


def _phone(name: str) -> dict:
    return {"name": name, "type": "phone"}


def _url(name: str) -> dict:
    return {"name": name, "type": "url"}


LEAD_STAGES = [
    "NEW_LEAD", "PRICES_SENT", "PACKAGE_SELECTED", "DEVICE_SELECTED",
    "INSTALL_METHOD", "APP_LINK_SENT", "APP_INSTALLED", "HANDOFF_REQUESTED",
    "SETUP_VERIFIED", "PAYMENT_DUE", "PAYMENT_VERIFICATION", "CONVERTED",
    "TRIAL_REQUESTED", "TRIAL_ACTIVE", "RENEWAL", "LOST", "OPTED_OUT",
]

DEVICE_TIERS = ["1 Device", "2 Devices", "3 Devices", "4+ Devices"]
PAYMENT_METHODS = ["orange_money", "afrimoney", "qmoney", "bank_transfer", "cash"]
PAYMENT_STATUSES = ["pending", "verifying", "confirmed", "rejected"]
YES_NO = ["Yes", "No"]

TABLE_SCHEMAS: dict[str, list[dict]] = {
    "01_Leads": [
        _text("Lead ID"), _text("Lead Name"), _phone("WhatsApp Number"),
        _phone("Alternate Phone"),
        _select("Lead Source", ["whatsapp_bot", "referral", "reseller", "walk_in", "advert", "other"]),
        _text("Campaign Code"), _text("Referral ID"), _text("Reseller ID"),
        _text("Sales Agent ID"), _text("Region"), _text("Town or Community"),
        _text("Address or Landmark"),
        _select("Preferred Language", ["EN", "Krio", "Other"]),
        _text("Device Type"), _number("Device Count"),
        _select("Internet Type", ["qcell", "africell", "sierratel", "wifi", "mifi", "mobile_data", "unknown"]),
        _select("Setup Method", ["self_install", "remote_guided", "staff_visit"]),
        _text("Interested Package ID"), _select("Lead Stage", LEAD_STAGES),
        _select("Priority", ["hot", "warm", "cold"]),
        _text("Trial ID"), _text("Trial Outcome"), _text("Installation ID"),
        _datetime("First Contact At"), _datetime("Last Contact At"),
        _datetime("Next Follow Up"), _text("Lost Reason"), _text("Lead Notes"),
        _datetime("Created At"),
    ],
    "02_Free_Trials": [
        _text("Trial ID"), _text("Lead ID"), _phone("WhatsApp Number"),
        _text("Trial Device ID"), _text("Package ID"), _datetime("Requested At"),
        _datetime("Activated At"), _datetime("Expires At"),
        _number("Trial Duration Hours"),
        _select("Trial Status", ["requested", "approved", "active", "expired", "converted", "rejected"]),
        _text("Trial Account Reference"), _text("Approved By Staff ID"),
        _text("Activated By Staff ID"), _datetime("Access Disabled At"),
        _checkbox("Eligibility Checked"), _checkbox("Duplicate Check"),
        _text("Converted Customer ID"), _text("Conversion Payment ID"),
        _text("Lead Source"), _text("Trial Notes"),
    ],
    "03_Customers": [
        _text("Customer ID"), _text("Customer Name"), _phone("WhatsApp Number"),
        _phone("Alternative Phone"), _text("Original Lead ID"), _text("Trial ID"),
        _text("Reseller ID"), _text("Sales Agent ID"), _datetime("Date Joined"),
        _text("Region"), _text("Town or Community"), _text("Address"),
        _select("Preferred Language", ["EN", "Krio", "Other"]),
        _select("Customer Status", ["active", "expired", "suspended", "cancelled"]),
        _text("Current Subscription ID"), _text("Most Recent Payment ID"),
        _select("Preferred Setup", ["self_install", "remote_guided", "staff_visit"]),
        _text("Primary Device Type"), _text("Referral Code"),
        _checkbox("Renewal Reminder Opt-in"), _text("Support Notes"),
    ],
    "04_Packages": [
        _text("Package ID"), _text("Package Name"), _number("Duration Months"),
        _select("Device Tier", DEVICE_TIERS), _number("Minimum Devices"),
        _number("Reference Device Count"), _number("Unit Price SLE"),
        _number("Promotion Discount %"), _checkbox("Trial Eligible"),
        _number("Trial Hours"), _select("Available", YES_NO),
        _text("Price Version"), _datetime("Valid From"), _text("Package Notes"),
    ],
    "05_Subscriptions": [
        _text("Subscription ID"), _text("Customer ID"),
        _text("Previous Subscription ID"), _text("Origin Trial ID"),
        _text("Package ID"), _number("Device Count"), _number("Duration Months"),
        _datetime("Activation Date"), _datetime("Standard Expiry"),
        _number("Approved Bonus Days"), _datetime("Final Expiry"),
        _select("Subscription Status", ["pending_setup", "active", "expired", "cancelled"]),
        _text("Payment ID"), _number("Gross Price SLE"),
        _number("Discount % Snapshot"), _number("Amount Paid SLE"),
        _text("Reseller ID"), _text("Reseller Sale ID"),
        _datetime("Renewal Follow-up At"), _text("Access Activated By"),
        _checkbox("Setup Verified"), _text("Bonus Approval By"),
        _text("Subscription Notes"),
    ],
    "06_Payments": [
        _text("Payment ID"), _datetime("Received At"), _text("Customer ID"),
        _text("Lead ID"), _text("Reseller ID"), _text("Reseller Sale ID"),
        _text("Subscription ID"), _text("Installation ID"),
        _select("Payment For", ["subscription", "installation", "hardware", "other"]),
        _text("Package ID"), _number("Device Count"),
        _number("Unit Price Snapshot SLE"), _number("Gross Subscription SLE"),
        _number("Discount %"), _number("Discount Amount SLE"),
        _number("Installation Fee SLE"), _number("Amount Due SLE"),
        _number("Amount Received SLE"), _number("Balance Due SLE"),
        _select("Currency", ["SLE"]), _select("Payment Method", PAYMENT_METHODS),
        _text("Payment Reference"), _text("Collected By Staff ID"),
        _text("Confirmed By Staff ID"), _select("Payment Status", PAYMENT_STATUSES),
        _url("Proof URL"), _text("Payment Notes"),
    ],
    "07_Installations": [
        _text("Installation ID"), _text("Lead ID"), _text("Customer ID"),
        _text("Trial ID"), _datetime("Requested At"), _datetime("Scheduled At"),
        _select("Setup Type", ["self_install", "remote_guided", "staff_visit"]),
        _text("Service Zone ID"), _text("Address and Landmark"), _url("Map URL"),
        _text("Device Type"), _number("Device Count"),
        _text("Assigned Technician ID"), _number("Visit Fee Quoted SLE"),
        _number("Visit Fee Paid SLE"), _text("Payment ID"),
        _select("Booking Status", ["pending_quote", "quote_issued", "booked", "in_progress", "completed", "cancelled"]),
        _datetime("Visit Started At"), _datetime("Completed At"),
        _checkbox("App Installed"), _checkbox("Account Configured"),
        _checkbox("Playback Tested"), _checkbox("Customer Accepted"),
        _number("Transport Cost SLE"), _text("Issue or Visit Notes"),
    ],
    "08_Devices": [
        _text("Device ID"), _text("Customer ID"), _text("Subscription ID"),
        _text("Trial ID"), _text("Device Type"), _text("Device Nickname"),
        _text("Platform or OS"), _text("Hardware Identifier Masked"),
        _text("App Name"), _text("App Version"), _datetime("Registered At"),
        _datetime("Last Checked At"),
        _select("Device Status", ["pending", "active", "inactive", "replaced"]),
        _text("Installed By Staff ID"), _text("Notes - No Passwords"),
    ],
    "09_Resellers": [
        _text("Reseller ID"), _text("Reseller Code"), _text("Business or Full Name"),
        _text("Primary Contact"), _phone("WhatsApp Number"),
        _phone("Alternative Phone"), _text("Business Email"),
        _select("Reseller Type", ["individual", "business", "sub_agent"]),
        _text("Territory or Zone"), _text("Location Address"), _datetime("Joined At"),
        _select("Status", ["pending", "active", "suspended", "terminated"]),
        _checkbox("Onboarding Verified"), _url("Agreement URL"),
        _text("Managed By Staff ID"),
        _select("Operating Model", ["cash_and_carry", "collect_and_remit", "online"]),
        _select("Default Commission Method", ["percentage", "fixed_amount"]),
        _number("Default Commission Rate %"), _number("Default Fixed Commission SLE"),
        _select("Commission Basis", ["net_subscription", "gross_subscription"]),
        _select("Settlement Frequency", ["weekly", "biweekly", "monthly"]),
        _number("Wallet Opening Credit SLE"), _number("Credit Limit SLE"),
        _select("Preferred Payout Method", PAYMENT_METHODS),
        _text("Payout Account Masked"), _text("Unique Referral Code"),
        _datetime("Last Activity At"), _text("Notes"),
    ],
    "10_Reseller_Sales": [
        _text("Reseller Sale ID"), _text("Reseller ID"),
        _text("Reseller Code Snapshot"), _text("Lead ID"), _text("Customer ID"),
        _text("Subscription ID"), _text("Package ID"), _text("Payment ID"),
        _datetime("Sale Date"), _select("Sale Type", ["new", "renewal", "upgrade"]),
        _number("Device Count"), _number("Gross Subscription SLE"),
        _number("Discount SLE"), _number("Net Subscription SLE"),
        _number("Installation Fee SLE"), _text("Collected By"),
        _number("Amount Collected By Reseller SLE"),
        _number("Amount Remitted To NexgloTV SLE"), _number("Remittance Due SLE"),
        _datetime("Remittance Due Date"), _checkbox("Commission Eligible"),
        _text("Commission ID"),
        _select("Sale Status", ["pending_remit", "remitted", "verified", "rejected"]),
        _text("Verified By Staff ID"), _text("Reseller Sales Notes"),
    ],
    "11_Commissions": [
        _text("Commission ID"), _text("Reseller ID"), _text("Reseller Sale ID"),
        _text("Payment ID"), _text("Customer ID"), _datetime("Earned On"),
        _number("Eligible Revenue SLE"), _text("Commission Method Snapshot"),
        _number("Rate % Snapshot"), _number("Fixed Amount Snapshot SLE"),
        _number("Commission Earned SLE"), _number("Adjustment SLE"),
        _number("Payable SLE"),
        _select("Commission Status", ["pending", "approved", "paid", "held", "cancelled"]),
        _text("Approved By Staff ID"), _datetime("Approved At"), _text("Payout ID"),
        _datetime("Paid At"), _text("Hold Reason"), _text("Commission Notes"),
    ],
    "12_Reseller_Payouts": [
        _text("Payout ID"), _text("Reseller ID"), _datetime("Period Start"),
        _datetime("Period End"), _datetime("Requested At"),
        _number("Commission Total SLE"), _number("Adjustments SLE"),
        _number("Payout Due SLE"), _number("Amount Paid SLE"),
        _number("Payout Balance SLE"), _select("Payout Method", PAYMENT_METHODS),
        _text("Destination Account Masked"), _text("Transaction Reference"),
        _select("Payout Status", ["requested", "approved", "paid", "rejected"]),
        _text("Approved By Staff ID"), _datetime("Approved At"), _datetime("Paid At"),
        _url("Evidence URL"), _text("Payout Notes"),
    ],
    "13_Reseller_Wallet": [
        _text("Wallet Entry ID"), _text("Reseller ID"), _datetime("Transaction At"),
        _select("Entry Type", ["opening_credit", "sale_credit", "commission", "remittance_debit", "payout_debit", "adjustment"]),
        _number("Credit SLE"), _number("Debit SLE"), _text("Reseller Sale ID"),
        _text("Payment ID"), _text("Reference"),
        _select("Wallet Status", ["pending", "approved", "void"]),
        _text("Approved By Staff ID"), _datetime("Approval At"), _url("Evidence URL"),
        _text("Ledger Notes"),
    ],
    "14_Referrals": [
        _text("Referral ID"), _text("Referrer Customer ID"),
        _text("Referred Lead ID"), _text("Referred Customer ID"),
        _datetime("Referral Date"), _text("Referral Code"),
        _text("Reseller ID - If Any"), _text("Qualified Payment ID"),
        _select("Reward Type", ["days", "cash", "none"]),
        _number("Reward Value Days"), _number("Reward Value SLE"),
        _select("Reward Status", ["pending", "qualified", "applied", "paid", "rejected"]),
        _text("Applied Subscription ID"), _text("Approved By Staff ID"),
        _datetime("Applied At"), _text("Notes"),
    ],
    "15_Staff": [
        _text("Staff ID"), _text("Staff Name"), _text("Lark Member"),
        _phone("Work Phone"),
        _select("Role", ["setup_agent", "payment_verifier", "technician", "admin", "sales"]),
        _text("Region or Territory"), _datetime("Start Date"),
        _select("Staff Status", ["active", "inactive", "suspended"]),
        _text("Supervisor Staff ID"), _number("Lead Capacity"),
        _number("Installation Capacity"), _text("Notes"),
    ],
    "16_Support_Tickets": [
        _text("Ticket ID"), _text("Customer ID"), _text("Lead ID"),
        _text("Reseller ID"), _text("Subscription ID"), _datetime("Opened At"),
        _select("Issue Type", ["login", "buffering", "channel_missing", "payment", "device", "other"]),
        _select("Priority", ["low", "medium", "high", "urgent"]),
        _text("Subject"), _text("Description"), _text("Assigned Staff ID"),
        _select("Ticket Status", ["open", "in_progress", "waiting_customer", "resolved", "closed"]),
        _datetime("First Response At"), _datetime("Follow Up At"),
        _datetime("Resolved At"), _text("Resolution Notes"),
        _checkbox("Customer Confirmed"), _text("Ticket Notes"),
    ],
    "17_Activities": [
        _text("Activity ID"), _text("Lead ID"), _text("Customer ID"),
        _text("Reseller ID"), _text("Staff ID"),
        _select("Activity Type", ["price_sent", "quote_given", "follow_up", "call", "visit", "note", "handoff"]),
        _datetime("Activity At"), _datetime("Due At"),
        _select("Status", ["pending", "done", "cancelled"]),
        _text("Outcome"), _text("Next Action"), _text("Related Ticket ID"),
        _text("Notes"),
    ],
    "18_Service_Zones": [
        _text("Zone ID"), _text("Region"), _text("District or Town"),
        _text("Covered Communities"),
        _select("Installation Type", ["staff_visit", "remote_only", "both"]),
        _number("Standard Visit Fee SLE"), _number("Transport Fee SLE"),
        _number("Additional Device Fee SLE"), _select("Service Available", YES_NO),
        _text("Assigned Technician ID"), _datetime("Price Effective Date"),
        _text("Notes"),
    ],
}

# Key field per table (used for upsert lookup)
TABLE_KEY_FIELD: dict[str, str] = {
    "01_Leads": "Lead ID",
    "02_Free_Trials": "Trial ID",
    "03_Customers": "Customer ID",
    "04_Packages": "Package ID",
    "05_Subscriptions": "Subscription ID",
    "06_Payments": "Payment ID",
    "07_Installations": "Installation ID",
    "08_Devices": "Device ID",
    "09_Resellers": "Reseller ID",
    "10_Reseller_Sales": "Reseller Sale ID",
    "11_Commissions": "Commission ID",
    "12_Reseller_Payouts": "Payout ID",
    "13_Reseller_Wallet": "Wallet Entry ID",
    "14_Referrals": "Referral ID",
    "15_Staff": "Staff ID",
    "16_Support_Tickets": "Ticket ID",
    "17_Activities": "Activity ID",
    "18_Service_Zones": "Zone ID",
}

# Wa_id lookup fields (for finding a contact's row)
TABLE_WA_FIELD: dict[str, str] = {
    "01_Leads": "WhatsApp Number",
    "02_Free_Trials": "WhatsApp Number",
    "03_Customers": "WhatsApp Number",
    "09_Resellers": "WhatsApp Number",
}

# Tables the WhatsApp bot writes to (read-mostly tables excluded)
BOT_WRITE_TABLES = {
    "01_Leads", "02_Free_Trials", "03_Customers", "05_Subscriptions",
    "06_Payments", "07_Installations", "08_Devices", "14_Referrals",
    "16_Support_Tickets", "17_Activities",
}

# Seed data: the 16 package rows from the owner's import file.
SEED_PACKAGES: list[dict] = [
    {"Package ID": "PKG-01", "Package Name": "1 Month / 1 Device", "Duration Months": 1, "Device Tier": "1 Device", "Minimum Devices": 1, "Reference Device Count": 1, "Unit Price SLE": 180, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-04"},
    {"Package ID": "PKG-02", "Package Name": "1 Month / 2 Devices", "Duration Months": 1, "Device Tier": "2 Devices", "Minimum Devices": 2, "Reference Device Count": 2, "Unit Price SLE": 160, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-04"},
    {"Package ID": "PKG-03", "Package Name": "1 Month / 3 Devices", "Duration Months": 1, "Device Tier": "3 Devices", "Minimum Devices": 3, "Reference Device Count": 3, "Unit Price SLE": 140, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-04"},
    {"Package ID": "PKG-04", "Package Name": "1 Month / 4+ Devices", "Duration Months": 1, "Device Tier": "4+ Devices", "Minimum Devices": 4, "Reference Device Count": 4, "Unit Price SLE": 120, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "PER DEVICE price"},
    {"Package ID": "PKG-05", "Package Name": "3 Months / 1 Device", "Duration Months": 3, "Device Tier": "1 Device", "Minimum Devices": 1, "Reference Device Count": 1, "Unit Price SLE": 500, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-08"},
    {"Package ID": "PKG-06", "Package Name": "3 Months / 2 Devices", "Duration Months": 3, "Device Tier": "2 Devices", "Minimum Devices": 2, "Reference Device Count": 2, "Unit Price SLE": 450, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-08"},
    {"Package ID": "PKG-07", "Package Name": "3 Months / 3 Devices", "Duration Months": 3, "Device Tier": "3 Devices", "Minimum Devices": 3, "Reference Device Count": 3, "Unit Price SLE": 400, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-08"},
    {"Package ID": "PKG-08", "Package Name": "3 Months / 4+ Devices", "Duration Months": 3, "Device Tier": "4+ Devices", "Minimum Devices": 4, "Reference Device Count": 4, "Unit Price SLE": 340, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "PER DEVICE price"},
    {"Package ID": "PKG-09", "Package Name": "6 Months / 1 Device", "Duration Months": 6, "Device Tier": "1 Device", "Minimum Devices": 1, "Reference Device Count": 1, "Unit Price SLE": 950, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-12"},
    {"Package ID": "PKG-10", "Package Name": "6 Months / 2 Devices", "Duration Months": 6, "Device Tier": "2 Devices", "Minimum Devices": 2, "Reference Device Count": 2, "Unit Price SLE": 850, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-12"},
    {"Package ID": "PKG-11", "Package Name": "6 Months / 3 Devices", "Duration Months": 6, "Device Tier": "3 Devices", "Minimum Devices": 3, "Reference Device Count": 3, "Unit Price SLE": 750, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-12"},
    {"Package ID": "PKG-12", "Package Name": "6 Months / 4+ Devices", "Duration Months": 6, "Device Tier": "4+ Devices", "Minimum Devices": 4, "Reference Device Count": 4, "Unit Price SLE": 640, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "PER DEVICE price"},
    {"Package ID": "PKG-13", "Package Name": "12 Months / 1 Device", "Duration Months": 12, "Device Tier": "1 Device", "Minimum Devices": 1, "Reference Device Count": 1, "Unit Price SLE": 1800, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-16"},
    {"Package ID": "PKG-14", "Package Name": "12 Months / 2 Devices", "Duration Months": 12, "Device Tier": "2 Devices", "Minimum Devices": 2, "Reference Device Count": 2, "Unit Price SLE": 1600, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-16"},
    {"Package ID": "PKG-15", "Package Name": "12 Months / 3 Devices", "Duration Months": 12, "Device Tier": "3 Devices", "Minimum Devices": 3, "Reference Device Count": 3, "Unit Price SLE": 1400, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "4+ ties to PKG-16"},
    {"Package ID": "PKG-16", "Package Name": "12 Months / 4+ Devices", "Duration Months": 12, "Device Tier": "4+ Devices", "Minimum Devices": 4, "Reference Device Count": 4, "Unit Price SLE": 1200, "Promotion Discount %": 20, "Trial Eligible": True, "Trial Hours": 24, "Available": "Yes", "Price Version": "v7-lark", "Package Notes": "PER DEVICE price"},
]