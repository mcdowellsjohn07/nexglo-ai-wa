"""NexgloTV Lark Base field schemas — exact manifest implementation.

Source of truth: NexgloTV_Lark_CRM_Field_Manifest.json (owner-provided).
- FIELD_SCHEMAS: non-link fields, exact types/options. Phone/Email/URL are text
  fields with style.type (per Lark field-schema guide).
- LINKS: the 79 cross-table relations -> native Lark link fields, created after
  all tables exist (text->link conversion is blacklisted by the API).
- VALUE_MAPS: bot-internal enum -> manifest option label translation.
"""

from __future__ import annotations


def _text(name: str) -> dict:
    return {"name": name, "type": "text"}


def _phone(name: str) -> dict:
    return {"name": name, "type": "text", "style": {"type": "phone"}}


def _email(name: str) -> dict:
    return {"name": name, "type": "text", "style": {"type": "email"}}


def _url(name: str) -> dict:
    return {"name": name, "type": "text", "style": {"type": "url"}}


def _number(name: str) -> dict:
    return {"name": name, "type": "number", "style": {"type": "plain", "precision": 0}}


def _select(name: str, options: list[str]) -> dict:
    return {"name": name, "type": "select", "multiple": False,
            "options": [{"name": o} for o in options]}


def _datetime(name: str) -> dict:
    return {"name": name, "type": "datetime"}


def _date(name: str) -> dict:
    return {"name": name, "type": "datetime", "style": {"format": "yyyy-MM-dd"}}


def _checkbox(name: str) -> dict:
    return {"name": name, "type": "checkbox"}


LEAD_SOURCE = ["WhatsApp", "Facebook", "Instagram", "TikTok", "Website", "Walk-in",
               "Referral", "Reseller", "Field Sales", "Other"]
REGIONS = ["Western Area", "North West", "Northern", "Eastern", "Southern", "Other"]
LANGUAGES = ["Krio", "English", "Temne", "Mende", "Limba", "Other"]
DEVICE_TYPES = ["Smart TV", "Android TV", "Android Box", "Fire TV Stick",
                "Android Phone", "iPhone or iPad", "Computer", "Other"]
INTERNET_TYPES = ["Wi-Fi", "Fiber", "Mobile Data", "Unknown"]
SETUP_METHODS = ["Self-Setup", "Remote Assistance", "Physical Visit", "Undecided"]
LEAD_STAGES = ["New", "Contacted", "Qualified", "Trial Requested", "Trial Active",
               "Trial Ended", "Package Selected", "Setup Booked", "Payment Pending",
               "Won", "Lost", "On Hold"]
PRIORITIES = ["Hot", "Warm", "Cold"]
TRIAL_OUTCOMES = ["Not Requested", "Requested", "Active", "Expired", "Converted", "Declined"]
LOST_REASONS = ["Price", "No Response", "Device or Internet", "Location", "Competitor", "Other"]
TRIAL_STATUSES = ["Requested", "Approved", "Active", "Expired", "Converted", "Declined", "Revoked"]
DUPLICATE_CHECK = ["Clear", "Needs Review", "Duplicate"]
CUSTOMER_STATUSES = ["Active", "Renewal Due", "Expired", "On Hold", "Cancelled"]
DEVICE_TIERS = ["1 Device", "2 Devices", "3 Devices", "4+ Devices"]
YES_NO = ["Yes", "No"]
SUBSCRIPTION_STATUSES = ["Pending", "Active", "Renewal Due", "Expired", "Suspended", "Cancelled"]
PAYMENT_FOR = ["New Subscription", "Renewal", "Installation", "Device Upgrade",
               "Reseller Deposit", "Other"]
CURRENCIES = ["SLE", "USD"]
PAYMENT_METHODS = ["Orange Money", "Afrimoney", "Cash", "Bank Transfer", "Card", "Other"]
PAYMENT_STATUSES = ["Pending", "Verification Required", "Confirmed", "Partially Paid",
                    "Failed", "Refunded"]
SETUP_TYPES = ["Self-Setup", "Remote Assistance", "Physical Installation"]
BOOKING_STATUSES = ["Requested", "Quote Sent", "Confirmed", "Scheduled", "En Route",
                    "In Progress", "Completed", "Reschedule", "Cancelled"]
DEVICE_STATUSES = ["Active", "Trial", "Replaced", "Disconnected", "Blocked"]
RESELLER_TYPES = ["Individual", "Shop", "Agent", "Distributor"]
RESELLER_STATUSES = ["Applicant", "Pending Approval", "Active", "Suspended", "Inactive"]
OPERATING_MODELS = ["Referral Commission", "Collect and Remit", "Prepaid Wallet", "Hybrid"]
COMMISSION_METHODS = ["Percentage", "Fixed", "No Commission"]
COMMISSION_BASES = ["Subscription Net Revenue", "Subscription Gross Revenue"]
SETTLEMENT_FREQ = ["Per Sale", "Weekly", "Monthly"]
PAYOUT_METHODS = ["Orange Money", "Afrimoney", "Bank Transfer", "Cash"]
SALE_TYPES = ["New", "Renewal", "Upgrade", "Installation"]
COLLECTED_BY = ["NexgloTV", "Reseller", "Customer Direct"]
SALE_STATUSES = ["Pending", "Trial", "Payment Pending", "Confirmed", "Cancelled", "Refunded"]
COMMISSION_STATUSES = ["Pending Payment", "Review", "Approved", "In Payout", "Paid",
                       "Held", "Reversed"]
PAYOUT_STATUSES = ["Draft", "Awaiting Approval", "Approved", "Processing", "Paid",
                   "Partially Paid", "Rejected"]
WALLET_ENTRY_TYPES = ["Deposit Credit", "Package Debit", "Refund Credit",
                      "Manual Adjustment Credit", "Manual Adjustment Debit"]
WALLET_STATUSES = ["Pending", "Confirmed", "Reversed"]
REWARD_TYPES = ["Bonus Viewing Days", "Approved Discount", "Other"]
REWARD_STATUSES = ["Pending", "Qualified", "Approved", "Applied", "Rejected"]
STAFF_ROLES = ["Sales", "Technician", "Support", "Finance", "Manager", "Admin"]
STAFF_STATUSES = ["Active", "On Leave", "Inactive"]
ISSUE_TYPES = ["Login", "App Installation", "Buffering", "Playback", "Subscription",
               "Device", "Billing", "Trial", "Other"]
TICKET_PRIORITIES = ["Low", "Normal", "High", "Urgent"]
TICKET_STATUSES = ["New", "Investigating", "Waiting Customer", "Escalated", "Resolved", "Closed"]
ACTIVITY_TYPES = ["Call", "WhatsApp", "Visit", "Demo", "Follow-up", "Training",
                  "Payment Reminder", "Renewal Reminder", "Other"]
ACTIVITY_STATUSES = ["Planned", "Due", "Completed", "Cancelled"]
ACTIVITY_OUTCOMES = ["Interested", "No Answer", "Need Follow-up", "Converted",
                     "Not Interested", "Resolved", "Other"]
INSTALLATION_TYPES = ["Physical Visit", "Remote", "Both"]
SERVICE_AVAILABLE = ["Yes", "No", "On Request"]

# Reseller + Installer Unified Program Enums
PARTNER_ROLES = ["Reseller Only", "Reseller + Installer"]
INSTALLER_APPROVAL_STATUSES = ["Not Applied", "Pending", "Approved", "Suspended", "Revoked"]
INSTALLER_AVAILABILITY = ["Available", "Busy", "Unavailable", "Suspended"]
TRANSPORT_ARRANGEMENTS = ["Own", "Public/Hired", "Discuss"]
INSTALL_MODES = ["Paid Physical", "Free Remote", "Self-Install", "Revisit/Support"]
INSTALLER_ASSIGNMENT_STATUSES = ["Unassigned", "Offered", "Accepted", "Declined", "Reassigned", "Cancelled"]
FEE_PAYMENT_STATUSES = ["Unpaid", "Pending Verification", "Verified", "Refunded"]
INSTALLER_EARNING_TYPES = ["INSTALLATION_BASE", "INSTALLATION_ADJUSTMENT", "MONTHLY_BONUS", "BONUS_ADJUSTMENT"]
INSTALLER_EARNING_STATUSES = ["Draft", "Hold", "Earned", "Approved", "Partially Paid", "Paid", "Reversed"]
PERFORMANCE_BANDS = ["None", "Starter", "Bronze", "Silver", "Gold", "Platinum", "Diamond"]
CLOSURE_STATUSES = ["Open", "Under Review", "Locked", "Paid", "Adjusted"]
ACTION_QUEUE_ROLES = ["Customer", "Lead", "Installer", "Reseller", "Staff", "Admin"]
ACTION_DELIVERY_STATES = ["Draft", "Pending Approval", "Queued", "Sent", "Delivered", "Failed", "Cancelled"]
ACTION_PRIORITIES = ["Low", "Medium", "High", "Urgent"]

# Bot state -> manifest Lead Stage
STAGE_TO_MANIFEST = {
    "NEW_LEAD": "New", "PRICES_SENT": "Contacted", "FAQ_ONLY": "Contacted",
    "SUPPORT": "Contacted", "COMPATIBILITY_CHECK": "Contacted", "FOLLOW_UP": "Contacted",
    "REFERRAL": "Contacted", "PACKAGE_SELECTED": "Package Selected",
    "PAYMENT_READINESS": "Package Selected", "DEVICE_SELECTED": "Qualified",
    "DEVICE_MODEL": "Qualified", "RENEWAL": "Qualified",
    "INSTALL_METHOD": "Setup Booked", "AREA_CAPTURED": "Setup Booked",
    "APP_LINK_SENT": "Setup Booked", "APP_INSTALLED": "Setup Booked",
    "HANDOFF_REQUESTED": "Setup Booked", "ESCALATED": "On Hold",
    "HUMAN_OWNED": "On Hold", "OPTED_OUT": "On Hold",
    "SETUP_VERIFIED": "Payment Pending", "PAYMENT_DUE": "Payment Pending",
    "PAYMENT_VERIFICATION": "Payment Pending", "CONVERTED": "Won",
    "TRIAL_REQUESTED": "Trial Requested", "TRIAL_APPROVAL": "Trial Requested",
    "TRIAL_ACTIVE": "Trial Active", "TRIAL_ENDED": "Trial Ended", "LOST": "Lost",
}

DEV_TYPE_TO_MANIFEST = {
    "smart_tv": "Smart TV", "android_tv": "Android TV", "android_tv_box": "Android Box",
    "fire_stick": "Fire TV Stick", "android_phone": "Android Phone",
    "iphone_ipad": "iPhone or iPad", "laptop": "Computer", "tablet": "Other",
    "roku": "Other", "other": "Other",
}
SETUP_TO_MANIFEST = {"self_install": "Self-Setup", "remote_guided": "Remote Assistance",
                     "staff_visit": "Physical Visit", "undecided": "Undecided"}
SETUP_TYPE_TO_MANIFEST = {"self_install": "Self-Setup",
                          "remote_guided": "Remote Assistance",
                          "staff_visit": "Physical Installation"}
PREF_SETUP_TO_MANIFEST = {"self_install": "Self-Setup", "remote_guided": "Remote",
                          "staff_visit": "Physical"}
LANG_TO_MANIFEST = {"EN": "English", "en": "English", "English": "English",
                    "ES": "Other", "es": "Other", "Krio": "Krio",
                    "Temne": "Temne", "Mende": "Mende", "Limba": "Limba",
                    "Other": "Other"}
PAY_METHOD_TO_MANIFEST = {"orange_money": "Orange Money", "orange": "Orange Money",
                          "afrimoney": "Afrimoney", "bank_transfer": "Bank Transfer",
                          "bank": "Bank Transfer", "transfer": "Bank Transfer",
                          "cash": "Cash", "qmoney": "Other", "card": "Card",
                          "reported": "Other", "other": "Other"}

FIELD_SCHEMAS: dict[str, list[dict]] = {
    "01_Leads": [
        _text("Lead ID"), _text("Lead Name"), _phone("WhatsApp Number"),
        _phone("Alternate Phone"), _select("Lead Source", LEAD_SOURCE),
        _text("Campaign Code"), _text("Referral ID"), _text("Reseller ID"),
        _text("Sales Agent ID"), _select("Region", REGIONS), _text("Town or Community"),
        _text("Address or Landmark"), _select("Preferred Language", LANGUAGES),
        _select("Device Type", DEVICE_TYPES), _number("Device Count"),
        _select("Internet Type", INTERNET_TYPES), _select("Setup Method", SETUP_METHODS),
        _text("Interested Package ID"), _select("Lead Stage", LEAD_STAGES),
        _select("Priority", PRIORITIES), _text("Trial ID"),
        _select("Trial Outcome", TRIAL_OUTCOMES), _text("Installation ID"),
        _datetime("First Contact At"), _datetime("Last Contact At"),
        _datetime("Next Follow Up"), _select("Lost Reason", LOST_REASONS),
        _text("Lead Notes"), _datetime("Created At"),
    ],
    "02_Free_Trials": [
        _text("Trial ID"), _text("Lead ID"), _phone("WhatsApp Number"),
        _text("Trial Device ID"), _text("Package ID"), _datetime("Requested At"),
        _datetime("Activated At"), _datetime("Expires At"),
        _number("Trial Duration Hours"), _select("Trial Status", TRIAL_STATUSES),
        _text("Trial Account Reference"), _text("Approved By Staff ID"),
        _text("Activated By Staff ID"), _datetime("Access Disabled At"),
        _checkbox("Eligibility Checked"), _select("Duplicate Check", DUPLICATE_CHECK),
        _text("Converted Customer ID"), _text("Conversion Payment ID"),
        _text("Lead Source"), _text("Trial Notes"),
    ],
    "03_Customers": [
        _text("Customer ID"), _text("Customer Name"), _phone("WhatsApp Number"),
        _phone("Alternative Phone"), _text("Original Lead ID"), _text("Trial ID"),
        _text("Reseller ID"), _text("Sales Agent ID"), _datetime("Date Joined"),
        _text("Region"), _text("Town or Community"), _text("Address"),
        _select("Preferred Language", LANGUAGES),
        _select("Customer Status", CUSTOMER_STATUSES),
        _text("Current Subscription ID"), _text("Most Recent Payment ID"),
        _select("Preferred Setup", ["Self-Setup", "Remote", "Physical"]),
        _text("Primary Device Type"), _text("Referral Code"),
        _checkbox("Renewal Reminder Opt-in"), _text("Support Notes"),
        _text("Account Username"), _text("Account Password"), _url("Server URL"),
    ],
    "04_Packages": [
        _text("Package ID"), _text("Package Name"), _number("Duration Months"),
        _select("Device Tier", DEVICE_TIERS), _number("Minimum Devices"),
        _number("Reference Device Count"), _number("Unit Price SLE"),
        _number("Promotion Discount %"), _checkbox("Trial Eligible"),
        _number("Trial Hours"), _select("Available", YES_NO), _text("Price Version"),
        _date("Valid From"), _text("Package Notes"),
    ],
    "05_Subscriptions": [
        _text("Subscription ID"), _text("Customer ID"), _phone("Customer WhatsApp Number"),
        _text("Previous Subscription ID"), _text("Origin Trial ID"),
        _text("Package ID"), _number("Device Count"), _number("Duration Months"),
        _datetime("Activation Date"), _datetime("Standard Expiry"),
        _number("Approved Bonus Days"), _datetime("Final Expiry"),
        _select("Subscription Status", SUBSCRIPTION_STATUSES), _text("Payment ID"),
        _number("Gross Price SLE"), _number("Discount % Snapshot"),
        _number("Amount Paid SLE"), _text("Reseller ID"), _text("Reseller Sale ID"),
        _datetime("Renewal Follow-up At"), _text("Access Activated By"),
        _checkbox("Setup Verified"), _text("Bonus Approval By"),
        _text("Subscription Notes"),
    ],
    "06_Payments": [
        _text("Payment ID"), _datetime("Received At"), _text("Customer ID"),
        _text("Lead ID"), _text("Reseller ID"), _text("Reseller Sale ID"),
        _text("Subscription ID"), _text("Installation ID"),
        _select("Payment For", PAYMENT_FOR), _text("Package ID"),
        _number("Device Count"), _number("Unit Price Snapshot SLE"),
        _number("Gross Subscription SLE"), _number("Discount %"),
        _number("Discount Amount SLE"), _number("Installation Fee SLE"),
        _number("Amount Due SLE"), _number("Amount Received SLE"),
        _number("Balance Due SLE"), _select("Currency", CURRENCIES),
        _select("Payment Method", PAYMENT_METHODS), _text("Payment Reference"),
        _text("Collected By Staff ID"), _text("Confirmed By Staff ID"),
        _select("Payment Status", PAYMENT_STATUSES), _url("Proof URL"),
        _text("Payment Notes"),
    ],
    "07_Installations": [
        _text("Installation ID"), _text("Lead ID"), _text("Customer ID"),
        _text("Trial ID"), _datetime("Requested At"), _datetime("Scheduled At"),
        _select("Setup Type", SETUP_TYPES), _text("Service Zone ID"),
        _text("Address and Landmark"), _url("Map URL"), _text("Device Type"),
        _number("Device Count"), _text("Assigned Technician ID"),
        _number("Visit Fee Quoted SLE"), _number("Visit Fee Paid SLE"),
        _text("Payment ID"), _select("Booking Status", BOOKING_STATUSES),
        _datetime("Visit Started At"), _datetime("Completed At"),
        _checkbox("App Installed"), _checkbox("Account Configured"),
        _checkbox("Playback Tested"), _checkbox("Customer Accepted"),
        _number("Transport Cost SLE"), _text("Issue or Visit Notes"),
        _text("Credited Sales Reseller ID"),
        _text("Assigned Installer Reseller ID"),
        _select("Installer Assignment Status", INSTALLER_ASSIGNMENT_STATUSES),
        _datetime("Assigned At"), _datetime("Accepted At"),
        _select("Install Mode", INSTALL_MODES),
        _number("Quoted Fee SLE"), _number("Approved Fee SLE"),
        _text("Fee Quote Version"), _text("Fee Approved By"),
        _datetime("Fee Approved At"), _text("Installation Fee Payment ID"),
        _number("Fee Received Verified SLE"),
        _select("Fee Payment Status", FEE_PAYMENT_STATUSES),
        _datetime("Customer Confirmed Working At"),
        _text("Completion Verified By"), _datetime("Completion Verified At"),
        _datetime("Qualified At"), _text("Qualified Month YYYY-MM"),
        _number("Commission Rate Snapshot %"),
        _text("Installation Earning ID"), _checkbox("Monthly Count Eligible"),
        _text("Revisit Of ID"), _checkbox("Refund/Dispute Hold"),
        _text("WhatsApp Conversation Ref"), _text("Last Bot Event ID"),
    ],
    "08_Devices": [
        _text("Device ID"), _text("Customer ID"), _text("Subscription ID"),
        _text("Trial ID"), _select("Device Type", DEVICE_TYPES),
        _text("Device Nickname"), _text("Platform or OS"),
        _text("Hardware Identifier Masked"), _text("App Name"), _text("App Version"),
        _datetime("Registered At"), _datetime("Last Checked At"),
        _select("Device Status", DEVICE_STATUSES), _text("Installed By Staff ID"),
        _text("Notes - No Passwords"),
    ],
    "09_Resellers": [
        _text("Reseller ID"), _text("Reseller Code"), _text("Business or Full Name"),
        _text("Primary Contact"), _phone("WhatsApp Number"),
        _phone("Alternative Phone"), _email("Business Email"),
        _select("Reseller Type", RESELLER_TYPES), _text("Territory or Zone"),
        _text("Location Address"), _datetime("Joined At"),
        _select("Status", RESELLER_STATUSES), _checkbox("Onboarding Verified"),
        _url("Agreement URL"), _text("Managed By Staff ID"),
        _select("Operating Model", OPERATING_MODELS),
        _select("Default Commission Method", COMMISSION_METHODS),
        _number("Default Commission Rate %"), _number("Default Fixed Commission SLE"),
        _select("Commission Basis", COMMISSION_BASES),
        _select("Settlement Frequency", SETTLEMENT_FREQ),
        _number("Wallet Opening Credit SLE"), _number("Credit Limit SLE"),
        _select("Preferred Payout Method", PAYOUT_METHODS),
        _text("Payout Account Masked"), _text("Unique Referral Code"),
        _datetime("Last Activity At"), _text("Notes"),
        _select("Partner Role", PARTNER_ROLES),
        _select("Installer Approval Status", INSTALLER_APPROVAL_STATUSES),
        _text("Installer Approved By"), _datetime("Installer Approved At"),
        _select("Installer Availability Status", INSTALLER_AVAILABILITY),
        _text("Installer Coverage Areas"), _text("Installer Device Skills"),
        _text("Installer Experience"), _text("Installer Availability Times"),
        _select("Transport Arrangement", TRANSPORT_ARRANGEMENTS),
        _number("Installation Commission Default %"),
        _checkbox("Monthly Bonus Eligible"),
        _datetime("Policy Acceptance At"), _text("Onboarding Form Reference"),
    ],
    "10_Reseller_Sales": [
        _text("Reseller Sale ID"), _text("Reseller ID"),
        _text("Reseller Code Snapshot"), _text("Lead ID"), _text("Customer ID"),
        _text("Subscription ID"), _text("Package ID"), _text("Payment ID"),
        _datetime("Sale Date"), _select("Sale Type", SALE_TYPES),
        _number("Device Count"), _number("Gross Subscription SLE"),
        _number("Discount SLE"), _number("Net Subscription SLE"),
        _number("Installation Fee SLE"), _select("Collected By", COLLECTED_BY),
        _number("Amount Collected By Reseller SLE"),
        _number("Amount Remitted To NexgloTV SLE"), _number("Remittance Due SLE"),
        _datetime("Remittance Due Date"), _checkbox("Commission Eligible"),
        _text("Commission ID"), _select("Sale Status", SALE_STATUSES),
        _text("Verified By Staff ID"), _text("Reseller Sales Notes"),
    ],
    "11_Commissions": [
        _text("Commission ID"), _text("Reseller ID"), _text("Reseller Sale ID"),
        _text("Payment ID"), _text("Customer ID"), _datetime("Earned On"),
        _number("Eligible Revenue SLE"),
        _select("Commission Method Snapshot", ["Percentage", "Fixed"]),
        _number("Rate % Snapshot"), _number("Fixed Amount Snapshot SLE"),
        _number("Commission Earned SLE"), _number("Adjustment SLE"),
        _number("Payable SLE"), _select("Commission Status", COMMISSION_STATUSES),
        _text("Approved By Staff ID"), _datetime("Approved At"), _text("Payout ID"),
        _datetime("Paid At"), _text("Hold Reason"), _text("Commission Notes"),
    ],
    "12_Reseller_Payouts": [
        _text("Payout ID"), _text("Reseller ID"), _date("Period Start"),
        _date("Period End"), _datetime("Requested At"),
        _number("Commission Total SLE"), _number("Adjustments SLE"),
        _number("Payout Due SLE"), _number("Amount Paid SLE"),
        _number("Payout Balance SLE"), _select("Payout Method", PAYOUT_METHODS),
        _text("Destination Account Masked"), _text("Transaction Reference"),
        _select("Payout Status", PAYOUT_STATUSES), _text("Approved By Staff ID"),
        _datetime("Approved At"), _datetime("Paid At"), _url("Evidence URL"),
        _text("Payout Notes"),
    ],
    "13_Reseller_Wallet": [
        _text("Wallet Entry ID"), _text("Reseller ID"), _datetime("Transaction At"),
        _select("Entry Type", WALLET_ENTRY_TYPES), _number("Credit SLE"),
        _number("Debit SLE"), _text("Reseller Sale ID"), _text("Payment ID"),
        _text("Reference"), _select("Wallet Status", WALLET_STATUSES),
        _text("Approved By Staff ID"), _datetime("Approval At"), _url("Evidence URL"),
        _text("Ledger Notes"),
    ],
    "14_Referrals": [
        _text("Referral ID"), _text("Referrer Customer ID"), _text("Referred Lead ID"),
        _text("Referred Customer ID"), _datetime("Referral Date"),
        _text("Referral Code"), _text("Reseller ID - If Any"),
        _text("Qualified Payment ID"), _select("Reward Type", REWARD_TYPES),
        _number("Reward Value Days"), _number("Reward Value SLE"),
        _select("Reward Status", REWARD_STATUSES), _text("Applied Subscription ID"),
        _text("Approved By Staff ID"), _datetime("Applied At"), _text("Notes"),
    ],
    "15_Staff": [
        _text("Staff ID"), _text("Staff Name"), _text("Lark Member"),
        _phone("Work Phone"), _select("Role", STAFF_ROLES),
        _text("Region or Territory"), _date("Start Date"),
        _select("Staff Status", STAFF_STATUSES), _text("Supervisor Staff ID"),
        _number("Lead Capacity"), _number("Installation Capacity"), _text("Notes"),
    ],
    "16_Support_Tickets": [
        _text("Ticket ID"), _text("Customer ID"), _text("Lead ID"),
        _text("Reseller ID"), _text("Subscription ID"), _datetime("Opened At"),
        _select("Issue Type", ISSUE_TYPES), _select("Priority", TICKET_PRIORITIES),
        _text("Subject"), _text("Description"), _text("Assigned Staff ID"),
        _select("Ticket Status", TICKET_STATUSES), _datetime("First Response At"),
        _datetime("Follow Up At"), _datetime("Resolved At"), _text("Resolution Notes"),
        _checkbox("Customer Confirmed"), _text("Ticket Notes"),
    ],
    "17_Activities": [
        _text("Activity ID"), _text("Lead ID"), _text("Customer ID"),
        _text("Reseller ID"), _text("Staff ID"),
        _select("Activity Type", ACTIVITY_TYPES), _datetime("Activity At"),
        _datetime("Due At"), _select("Status", ACTIVITY_STATUSES),
        _select("Outcome", ACTIVITY_OUTCOMES), _text("Next Action"),
        _text("Related Ticket ID"), _text("Notes"),
    ],
    "18_Service_Zones": [
        _text("Zone ID"), _text("Region"), _text("District or Town"),
        _text("Covered Communities"), _select("Installation Type", INSTALLATION_TYPES),
        _number("Standard Visit Fee SLE"), _number("Transport Fee SLE"),
        _number("Additional Device Fee SLE"), _select("Service Available", SERVICE_AVAILABLE),
        _text("Assigned Technician ID"), _date("Price Effective Date"), _text("Notes"),
    ],
    "20_Installer_Earnings": [
        _text("Earning ID"), _text("Reseller ID"),
        _select("Type", INSTALLER_EARNING_TYPES),
        _text("Installation ID"), _text("Performance Month"),
        _text("Idempotency Key"), _number("Basis Fee SLE"),
        _number("Rate Snapshot %"), _number("Signed Earning SLE"),
        _select("Status", INSTALLER_EARNING_STATUSES),
        _datetime("Qualified At"), _text("Approved By"),
        _datetime("Approved At"), _text("Linked Payout ID"),
        _number("Settled SLE"), _number("Outstanding SLE"),
        _number("Recoverable SLE"), _text("Origin Event ID"),
        _text("Policy Version"), _text("Correction Reason"),
    ],
    "21_Installer_Monthly_Performance": [
        _text("Performance ID"), _text("Reseller ID"),
        _text("Performance Month"), _datetime("Period Start"),
        _datetime("Period End"), _datetime("Installer Role Effective Date"),
        _text("Qualifying Installation IDs"), _number("Qualifying Count"),
        _select("Provisional Band", PERFORMANCE_BANDS),
        _number("Provisional Bonus SLE"),
        _select("Closed Band", PERFORMANCE_BANDS),
        _number("Approved Bonus Amount SLE"),
        _select("Closure Status", CLOSURE_STATUSES),
        _datetime("Locked At"), _text("Locked By"),
        _text("Bonus Earning ID"),
        _select("Payout State", ["Unpaid", "Approved", "Paid", "Adjusted"]),
        _text("Exception Notes"),
    ],
    "22_WhatsApp_Action_Queue": [
        _text("Action ID"), _text("Event Type"),
        _text("Related Table"), _text("Related Record ID"),
        _select("Target Role", ACTION_QUEUE_ROLES),
        _phone("Target WhatsApp ID"), _text("Approved Template Key"),
        _text("Payload Reference"), _select("Priority", ACTION_PRIORITIES),
        _checkbox("Requires Approval"), _text("Approved By"),
        _datetime("Approved At"), _text("Requested By"),
        _datetime("Requested At"), _datetime("Queued At"),
        _number("Attempt Count"), _text("Provider Message ID"),
        _select("Delivery State", ACTION_DELIVERY_STATES),
        _text("Last Error"), _datetime("Last Attempt At"),
        _text("Idempotency Key"),
    ],
}

# The 79 cross-table links: (table, field) -> target table (its primary field)
LINKS: list[dict] = [
    {"table": "01_Leads", "field": "Referral ID", "target": "14_Referrals"},
    {"table": "01_Leads", "field": "Reseller ID", "target": "09_Resellers"},
    {"table": "01_Leads", "field": "Interested Package ID", "target": "04_Packages"},
    {"table": "01_Leads", "field": "Trial ID", "target": "02_Free_Trials"},
    {"table": "01_Leads", "field": "Installation ID", "target": "07_Installations"},
    {"table": "02_Free_Trials", "field": "Lead ID", "target": "01_Leads"},
    {"table": "02_Free_Trials", "field": "Trial Device ID", "target": "08_Devices"},
    {"table": "02_Free_Trials", "field": "Package ID", "target": "04_Packages"},
    {"table": "02_Free_Trials", "field": "Approved By Staff ID", "target": "15_Staff"},
    {"table": "02_Free_Trials", "field": "Activated By Staff ID", "target": "15_Staff"},
    {"table": "02_Free_Trials", "field": "Converted Customer ID", "target": "03_Customers"},
    {"table": "02_Free_Trials", "field": "Conversion Payment ID", "target": "06_Payments"},
    {"table": "03_Customers", "field": "Original Lead ID", "target": "01_Leads"},
    {"table": "03_Customers", "field": "Trial ID", "target": "02_Free_Trials"},
    {"table": "03_Customers", "field": "Reseller ID", "target": "09_Resellers"},
    {"table": "03_Customers", "field": "Current Subscription ID", "target": "05_Subscriptions"},
    {"table": "03_Customers", "field": "Most Recent Payment ID", "target": "06_Payments"},
    {"table": "05_Subscriptions", "field": "Customer ID", "target": "03_Customers"},
    {"table": "05_Subscriptions", "field": "Origin Trial ID", "target": "02_Free_Trials"},
    {"table": "05_Subscriptions", "field": "Package ID", "target": "04_Packages"},
    {"table": "05_Subscriptions", "field": "Payment ID", "target": "06_Payments"},
    {"table": "05_Subscriptions", "field": "Reseller ID", "target": "09_Resellers"},
    {"table": "05_Subscriptions", "field": "Reseller Sale ID", "target": "10_Reseller_Sales"},
    {"table": "06_Payments", "field": "Customer ID", "target": "03_Customers"},
    {"table": "06_Payments", "field": "Lead ID", "target": "01_Leads"},
    {"table": "06_Payments", "field": "Reseller ID", "target": "09_Resellers"},
    {"table": "06_Payments", "field": "Reseller Sale ID", "target": "10_Reseller_Sales"},
    {"table": "06_Payments", "field": "Subscription ID", "target": "05_Subscriptions"},
    {"table": "06_Payments", "field": "Installation ID", "target": "07_Installations"},
    {"table": "06_Payments", "field": "Package ID", "target": "04_Packages"},
    {"table": "06_Payments", "field": "Collected By Staff ID", "target": "15_Staff"},
    {"table": "06_Payments", "field": "Confirmed By Staff ID", "target": "15_Staff"},
    {"table": "07_Installations", "field": "Lead ID", "target": "01_Leads"},
    {"table": "07_Installations", "field": "Customer ID", "target": "03_Customers"},
    {"table": "07_Installations", "field": "Trial ID", "target": "02_Free_Trials"},
    {"table": "07_Installations", "field": "Service Zone ID", "target": "18_Service_Zones"},
    {"table": "07_Installations", "field": "Payment ID", "target": "06_Payments"},
    {"table": "08_Devices", "field": "Customer ID", "target": "03_Customers"},
    {"table": "08_Devices", "field": "Subscription ID", "target": "05_Subscriptions"},
    {"table": "08_Devices", "field": "Trial ID", "target": "02_Free_Trials"},
    {"table": "08_Devices", "field": "Installed By Staff ID", "target": "15_Staff"},
    {"table": "09_Resellers", "field": "Managed By Staff ID", "target": "15_Staff"},
    {"table": "10_Reseller_Sales", "field": "Reseller ID", "target": "09_Resellers"},
    {"table": "10_Reseller_Sales", "field": "Lead ID", "target": "01_Leads"},
    {"table": "10_Reseller_Sales", "field": "Customer ID", "target": "03_Customers"},
    {"table": "10_Reseller_Sales", "field": "Subscription ID", "target": "05_Subscriptions"},
    {"table": "10_Reseller_Sales", "field": "Package ID", "target": "04_Packages"},
    {"table": "10_Reseller_Sales", "field": "Payment ID", "target": "06_Payments"},
    {"table": "10_Reseller_Sales", "field": "Commission ID", "target": "11_Commissions"},
    {"table": "10_Reseller_Sales", "field": "Verified By Staff ID", "target": "15_Staff"},
    {"table": "11_Commissions", "field": "Reseller ID", "target": "09_Resellers"},
    {"table": "11_Commissions", "field": "Reseller Sale ID", "target": "10_Reseller_Sales"},
    {"table": "11_Commissions", "field": "Payment ID", "target": "06_Payments"},
    {"table": "11_Commissions", "field": "Customer ID", "target": "03_Customers"},
    {"table": "11_Commissions", "field": "Approved By Staff ID", "target": "15_Staff"},
    {"table": "11_Commissions", "field": "Payout ID", "target": "12_Reseller_Payouts"},
    {"table": "12_Reseller_Payouts", "field": "Reseller ID", "target": "09_Resellers"},
    {"table": "12_Reseller_Payouts", "field": "Approved By Staff ID", "target": "15_Staff"},
    {"table": "13_Reseller_Wallet", "field": "Reseller ID", "target": "09_Resellers"},
    {"table": "13_Reseller_Wallet", "field": "Reseller Sale ID", "target": "10_Reseller_Sales"},
    {"table": "13_Reseller_Wallet", "field": "Payment ID", "target": "06_Payments"},
    {"table": "13_Reseller_Wallet", "field": "Approved By Staff ID", "target": "15_Staff"},
    {"table": "14_Referrals", "field": "Referrer Customer ID", "target": "03_Customers"},
    {"table": "14_Referrals", "field": "Referred Lead ID", "target": "01_Leads"},
    {"table": "14_Referrals", "field": "Referred Customer ID", "target": "03_Customers"},
    {"table": "14_Referrals", "field": "Reseller ID - If Any", "target": "09_Resellers"},
    {"table": "14_Referrals", "field": "Qualified Payment ID", "target": "06_Payments"},
    {"table": "14_Referrals", "field": "Applied Subscription ID", "target": "05_Subscriptions"},
    {"table": "14_Referrals", "field": "Approved By Staff ID", "target": "15_Staff"},
    {"table": "16_Support_Tickets", "field": "Customer ID", "target": "03_Customers"},
    {"table": "16_Support_Tickets", "field": "Lead ID", "target": "01_Leads"},
    {"table": "16_Support_Tickets", "field": "Reseller ID", "target": "09_Resellers"},
    {"table": "16_Support_Tickets", "field": "Subscription ID", "target": "05_Subscriptions"},
    {"table": "16_Support_Tickets", "field": "Assigned Staff ID", "target": "15_Staff"},
    {"table": "17_Activities", "field": "Lead ID", "target": "01_Leads"},
    {"table": "17_Activities", "field": "Customer ID", "target": "03_Customers"},
    {"table": "17_Activities", "field": "Reseller ID", "target": "09_Resellers"},
    {"table": "17_Activities", "field": "Staff ID", "target": "15_Staff"},
    {"table": "17_Activities", "field": "Related Ticket ID", "target": "16_Support_Tickets"},
]

LINK_FIELDS: dict[str, dict[str, str]] = {}
for _l in LINKS:
    LINK_FIELDS.setdefault(_l["table"], {})[_l["field"]] = _l["target"]

TABLE_KEY_FIELD: dict[str, str] = {
    "01_Leads": "Lead ID", "02_Free_Trials": "Trial ID", "03_Customers": "Customer ID",
    "04_Packages": "Package ID", "05_Subscriptions": "Subscription ID",
    "06_Payments": "Payment ID", "07_Installations": "Installation ID",
    "08_Devices": "Device ID", "09_Resellers": "Reseller ID",
    "10_Reseller_Sales": "Reseller Sale ID", "11_Commissions": "Commission ID",
    "12_Reseller_Payouts": "Payout ID", "13_Reseller_Wallet": "Wallet Entry ID",
    "14_Referrals": "Referral ID", "15_Staff": "Staff ID",
    "16_Support_Tickets": "Ticket ID", "17_Activities": "Activity ID",
    "18_Service_Zones": "Zone ID",
    "20_Installer_Earnings": "Earning ID",
    "21_Installer_Monthly_Performance": "Performance ID",
    "22_WhatsApp_Action_Queue": "Action ID",
}

TABLE_WA_FIELD: dict[str, str] = {
    "01_Leads": "WhatsApp Number", "02_Free_Trials": "WhatsApp Number",
    "03_Customers": "WhatsApp Number", "05_Subscriptions": "Customer WhatsApp Number",
    "09_Resellers": "WhatsApp Number",
    "22_WhatsApp_Action_Queue": "Target WhatsApp ID",
}

# Bot value -> manifest option label, per table/column. Unmapped columns/values
# pass through verbatim; select writes that match no option are dropped by _to_cell.
VALUE_MAPS: dict[str, dict[str, dict[str, str]]] = {
    "01_Leads": {
        "Lead Source": {"whatsapp": "WhatsApp", "whatsapp_bot": "WhatsApp",
                        "referral": "Referral", "reseller": "Reseller",
                        "walk_in": "Walk-in", "advert": "Other", "other": "Other"},
        "Region": {"western_area": "Western Area", "north_west": "North West",
                   "northern": "Northern", "eastern": "Eastern",
                   "southern": "Southern", "other": "Other"},
        "Preferred Language": LANG_TO_MANIFEST,
        "Device Type": DEV_TYPE_TO_MANIFEST,
        "Internet Type": {"wifi": "Wi-Fi", "mifi": "Wi-Fi", "qcell": "Mobile Data",
                          "africell": "Mobile Data", "sierratel": "Mobile Data",
                          "mobile_data": "Mobile Data", "fiber": "Fiber",
                          "unknown": "Unknown"},
        "Setup Method": SETUP_TO_MANIFEST,
        "Lead Stage": STAGE_TO_MANIFEST,
        "Priority": {"hot": "Hot", "warm": "Warm", "cold": "Cold"},
        "Trial Outcome": {"": "Not Requested", "none": "Not Requested",
                          "pending": "Requested", "requested": "Requested",
                          "approved": "Active", "active": "Active",
                          "expired": "Expired", "converted": "Converted",
                          "rejected": "Declined", "declined": "Declined"},
        "Lost Reason": {"price": "Price", "no_response": "No Response",
                        "device_or_internet": "Device or Internet",
                        "location": "Location", "competitor": "Competitor",
                        "other": "Other"},
    },
    "02_Free_Trials": {
        "Trial Status": {"pending": "Requested", "requested": "Requested",
                         "offered": "Approved", "approved": "Approved",
                         "active": "Active", "expired": "Expired",
                         "converted": "Converted", "rejected": "Declined",
                         "declined": "Declined", "revoked": "Revoked"},
        "Duplicate Check": {"clear": "Clear", "needs_review": "Needs Review",
                            "duplicate": "Duplicate"},
    },
    "03_Customers": {
        "Preferred Language": LANG_TO_MANIFEST,
        "Customer Status": {"active": "Active", "renewal_due": "Renewal Due",
                            "expired": "Expired", "suspended": "On Hold",
                            "on_hold": "On Hold", "cancelled": "Cancelled"},
        "Preferred Setup": PREF_SETUP_TO_MANIFEST,
    },
    "05_Subscriptions": {
        "Subscription Status": {"pending": "Pending", "pending_setup": "Pending",
                                "active": "Active", "renewal_due": "Renewal Due",
                                "expired": "Expired", "suspended": "Suspended",
                                "cancelled": "Cancelled"},
    },
    "06_Payments": {
        "Payment For": {"subscription": "New Subscription", "new_subscription": "New Subscription",
                        "renewal": "Renewal", "installation": "Installation",
                        "hardware": "Device Upgrade", "reseller_deposit": "Reseller Deposit",
                        "other": "Other"},
        "Currency": {"SLE": "SLE", "USD": "USD"},
        "Payment Method": PAY_METHOD_TO_MANIFEST,
        "Payment Status": {"pending": "Pending", "awaiting_payment": "Pending",
                           "verifying": "Verification Required",
                           "confirmed": "Confirmed", "partial": "Partially Paid",
                           "rejected": "Failed", "failed": "Failed",
                           "refunded": "Refunded"},
    },
    "07_Installations": {
        "Setup Type": SETUP_TYPE_TO_MANIFEST,
        "Booking Status": {"pending": "Requested", "pending_quote": "Requested",
                           "quote_issued": "Quote Sent", "booked": "Confirmed",
                           "confirmed": "Confirmed", "scheduled": "Scheduled",
                           "en_route": "En Route", "in_progress": "In Progress",
                           "verified": "Completed", "completed": "Completed",
                           "reschedule": "Reschedule", "cancelled": "Cancelled"},
    },
    "08_Devices": {
        "Device Type": DEV_TYPE_TO_MANIFEST,
        "Device Status": {"pending": "Trial", "trial": "Trial", "active": "Active",
                          "inactive": "Disconnected", "disconnected": "Disconnected",
                          "replaced": "Replaced", "blocked": "Blocked"},
    },
    "09_Resellers": {
        "Reseller Type": {"individual": "Individual", "business": "Shop",
                          "sub_agent": "Agent", "distributor": "Distributor"},
        "Status": {"pending": "Pending Approval", "applicant": "Applicant",
                   "active": "Active", "suspended": "Suspended",
                   "terminated": "Inactive", "inactive": "Inactive"},
        "Operating Model": {"referral_commission": "Referral Commission",
                            "collect_and_remit": "Collect and Remit",
                            "prepaid_wallet": "Prepaid Wallet", "hybrid": "Hybrid",
                            "cash_and_carry": "Hybrid", "online": "Referral Commission",
                            "prepaid": "Prepaid Wallet"},
        "Default Commission Method": {"percentage": "Percentage", "fixed": "Fixed",
                                      "fixed_amount": "Fixed", "none": "No Commission"},
        "Commission Basis": {"net_subscription": "Subscription Net Revenue",
                             "gross_subscription": "Subscription Gross Revenue"},
        "Settlement Frequency": {"per_sale": "Per Sale", "weekly": "Weekly",
                                 "biweekly": "Weekly", "monthly": "Monthly"},
        "Preferred Payout Method": PAY_METHOD_TO_MANIFEST,
    },
    "10_Reseller_Sales": {
        "Sale Type": {"new": "New", "renewal": "Renewal", "upgrade": "Upgrade",
                      "installation": "Installation"},
        "Collected By": {"nexglotv": "NexgloTV", "reseller": "Reseller",
                         "customer_direct": "Customer Direct"},
        "Sale Status": {"pending": "Pending", "trial": "Trial",
                        "payment_pending": "Payment Pending", "confirmed": "Confirmed",
                        "cancelled": "Cancelled", "refunded": "Refunded",
                        "pending_remit": "Payment Pending", "remitted": "Pending",
                        "verified": "Confirmed", "rejected": "Cancelled"},
    },
    "11_Commissions": {
        "Commission Method Snapshot": {"percentage": "Percentage", "fixed": "Fixed",
                                       "fixed_amount": "Fixed"},
        "Commission Status": {"pending": "Pending Payment", "review": "Review",
                              "approved": "Approved", "in_payout": "In Payout",
                              "paid": "Paid", "held": "Held",
                              "reversed": "Reversed", "cancelled": "Reversed"},
    },
    "12_Reseller_Payouts": {
        "Payout Method": PAY_METHOD_TO_MANIFEST,
        "Payout Status": {"draft": "Draft", "requested": "Awaiting Approval",
                          "awaiting_approval": "Awaiting Approval",
                          "approved": "Approved", "processing": "Processing",
                          "paid": "Paid", "partial": "Partially Paid",
                          "rejected": "Rejected"},
    },
    "13_Reseller_Wallet": {
        "Entry Type": {"deposit_credit": "Deposit Credit", "package_debit": "Package Debit",
                       "refund_credit": "Refund Credit",
                       "manual_adjustment_credit": "Manual Adjustment Credit",
                       "manual_adjustment_debit": "Manual Adjustment Debit",
                       "opening_credit": "Deposit Credit", "sale_credit": "Package Debit",
                       "commission": "Deposit Credit", "remittance_debit": "Package Debit",
                       "payout_debit": "Package Debit",
                       "adjustment": "Manual Adjustment Credit"},
        "Wallet Status": {"pending": "Pending", "confirmed": "Confirmed",
                          "reversed": "Reversed", "approved": "Confirmed",
                          "void": "Reversed"},
    },
    "14_Referrals": {
        "Reward Type": {"days": "Bonus Viewing Days", "cash": "Approved Discount",
                        "discount": "Approved Discount", "none": "Other", "other": "Other"},
        "Reward Status": {"pending": "Pending", "qualified": "Qualified",
                          "verified": "Approved", "approved": "Approved",
                          "applied": "Applied", "paid": "Applied",
                          "rejected": "Rejected"},
    },
    "15_Staff": {
        "Role": {"sales": "Sales", "technician": "Technician", "support": "Support",
                 "setup_agent": "Support", "finance": "Finance",
                 "payment_verifier": "Finance", "manager": "Manager", "admin": "Admin"},
        "Staff Status": {"active": "Active", "on_leave": "On Leave",
                         "inactive": "Inactive", "suspended": "Inactive"},
    },
    "16_Support_Tickets": {
        "Issue Type": {"login": "Login", "app_installation": "App Installation",
                       "app_install": "App Installation", "buffering": "Buffering",
                       "playback": "Playback", "channel_missing": "Playback",
                       "subscription": "Subscription", "device": "Device",
                       "billing": "Billing", "payment": "Billing", "trial": "Trial",
                       "other": "Other"},
        "Priority": {"low": "Low", "medium": "Normal", "normal": "Normal",
                     "high": "High", "urgent": "Urgent"},
        "Ticket Status": {"open": "New", "new": "New", "in_progress": "Investigating",
                          "investigating": "Investigating",
                          "waiting_customer": "Waiting Customer",
                          "escalated": "Escalated", "resolved": "Resolved",
                          "closed": "Closed"},
    },
    "17_Activities": {
        "Activity Type": {"call": "Call", "whatsapp": "WhatsApp", "visit": "Visit",
                          "demo": "Demo", "follow_up": "Follow-up",
                          "followup": "Follow-up", "training": "Training",
                          "payment_reminder": "Payment Reminder",
                          "renewal_reminder": "Renewal Reminder",
                          "price_sent": "WhatsApp", "quote_given": "WhatsApp",
                          "handoff": "Other", "note": "Other", "other": "Other"},
        "Status": {"planned": "Planned", "pending": "Planned", "due": "Due",
                   "manual_pending": "Due", "done": "Completed",
                   "completed": "Completed", "cancelled": "Cancelled"},
        "Outcome": {"interested": "Interested", "no_answer": "No Answer",
                    "need_follow_up": "Need Follow-up", "pending": "Need Follow-up",
                    "requested": "Need Follow-up", "setup_credentials": "Need Follow-up",
                    "visit_quote": "Need Follow-up", "trial_request": "Need Follow-up",
                    "compatibility_check": "Need Follow-up", "image": "Need Follow-up",
                    "converted": "Converted", "not_interested": "Not Interested",
                    "resolved": "Resolved", "done": "Resolved", "other": "Other"},
    },
    "18_Service_Zones": {
        "Installation Type": {"staff_visit": "Physical Visit",
                              "physical_visit": "Physical Visit", "remote": "Remote",
                              "remote_only": "Remote", "both": "Both"},
        "Service Available": {"yes": "Yes", "no": "No", "on_request": "On Request",
                              "Yes": "Yes", "No": "No", "On Request": "On Request"},
    },
}

_SELECT_OPTIONS: dict[str, dict[str, set[str]]] = {}
for _tbl, _flds in FIELD_SCHEMAS.items():
    for _f in _flds:
        if _f.get("type") == "select":
            _SELECT_OPTIONS.setdefault(_tbl, {})[_f["name"]] = {
                o["name"] for o in _f.get("options", [])
            }


def package_id_for(months: int, device_count: int) -> str:
    """Return the canonical PKG-01..PKG-16 code for a (months, device_count) pair."""
    m_offset = {1: 0, 3: 4, 6: 8, 12: 12}.get(int(months or 0))
    if m_offset is None or int(device_count or 0) <= 0:
        return ""
    tier = min(int(device_count), 4)
    return f"PKG-{m_offset + tier:02d}"


def map_value(table: str, column: str, value):
    """Translate a bot value to the manifest option label when a map exists."""
    if value is None:
        return None
    col_map = VALUE_MAPS.get(table, {}).get(column)
    s = str(value)
    mapped = col_map.get(s, col_map.get(s.lower(), value)) if col_map else value
    allowed = _SELECT_OPTIONS.get(table, {}).get(column)
    if allowed is not None:
        ms = str(mapped)
        if ms in allowed:
            return ms
        for opt in allowed:
            if opt.lower() == ms.lower():
                return opt
        if "Other" in allowed:
            return "Other"
        return None
    return mapped


def map_record(table: str, record: dict) -> dict:
    """Apply VALUE_MAPS to every mapped column of a record dict."""
    out = {}
    for col, val in record.items():
        mv = map_value(table, col, val)
        if mv is not None:
            out[col] = mv
    return out


# Seed packages: prices from the owner's v6 workbook (PKG-01..16), manifest options.
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

SEED_STAFF: list[dict] = [
    {"Staff ID": "STAFF-01", "Staff Name": "NexgloTV Admin Desk", "Role": "Admin", "Region or Territory": "All Regions", "Staff Status": "Active", "Lead Capacity": 100, "Installation Capacity": 20, "Notes": "Primary admin and bot supervisor"},
    {"Staff ID": "STAFF-02", "Staff Name": "NexgloTV Sales Desk", "Role": "Sales", "Region or Territory": "Western Area", "Staff Status": "Active", "Supervisor Staff ID": "STAFF-01", "Lead Capacity": 80, "Installation Capacity": 0, "Notes": "Lead follow-up & trial approvals"},
    {"Staff ID": "STAFF-03", "Staff Name": "NexgloTV Field Technician", "Role": "Technician", "Region or Territory": "Freetown & Western Area", "Staff Status": "Active", "Supervisor Staff ID": "STAFF-01", "Lead Capacity": 20, "Installation Capacity": 15, "Notes": "Physical installation & on-site setup"},
    {"Staff ID": "STAFF-04", "Staff Name": "NexgloTV Support Desk", "Role": "Support", "Region or Territory": "All Regions", "Staff Status": "Active", "Supervisor Staff ID": "STAFF-01", "Lead Capacity": 50, "Installation Capacity": 10, "Notes": "Remote setup, credentials & troubleshooting"},
    {"Staff ID": "STAFF-05", "Staff Name": "NexgloTV Finance Desk", "Role": "Finance", "Region or Territory": "All Regions", "Staff Status": "Active", "Supervisor Staff ID": "STAFF-01", "Lead Capacity": 50, "Installation Capacity": 0, "Notes": "Payment verification & reseller payouts"},
]

SEED_SERVICE_ZONES: list[dict] = [
    {"Zone ID": "ZONE-01", "Region": "Western Area", "District or Town": "Freetown Central", "Covered Communities": "Central, Pademba Rd, Siaka Stevens St, Circular Rd, Brookfields", "Installation Type": "Both", "Standard Visit Fee SLE": 100, "Transport Fee SLE": 0, "Additional Device Fee SLE": 50, "Service Available": "Yes", "Assigned Technician ID": "STAFF-03", "Notes": "Standard central Freetown coverage"},
    {"Zone ID": "ZONE-02", "Region": "Western Area", "District or Town": "Freetown West End", "Covered Communities": "Lumley, Aberdeen, Murray Town, Wilkinson Rd, Spur Rd, Juba, Goderich", "Installation Type": "Both", "Standard Visit Fee SLE": 120, "Transport Fee SLE": 30, "Additional Device Fee SLE": 50, "Service Available": "Yes", "Assigned Technician ID": "STAFF-03", "Notes": "West End home/office visit zone"},
    {"Zone ID": "ZONE-03", "Region": "Western Area", "District or Town": "Freetown Hill & Mountain", "Covered Communities": "Hill Station, Wilberforce, Regent, Gloucester, Leicester, IMATT", "Installation Type": "Both", "Standard Visit Fee SLE": 150, "Transport Fee SLE": 50, "Additional Device Fee SLE": 50, "Service Available": "Yes", "Assigned Technician ID": "STAFF-03", "Notes": "Hilltop communities"},
    {"Zone ID": "ZONE-04", "Region": "Western Area", "District or Town": "Freetown East End", "Covered Communities": "Cline Town, Kissy, Wellington, Calaba Town, Allen Town", "Installation Type": "Both", "Standard Visit Fee SLE": 150, "Transport Fee SLE": 50, "Additional Device Fee SLE": 50, "Service Available": "Yes", "Assigned Technician ID": "STAFF-03", "Notes": "East End coverage"},
    {"Zone ID": "ZONE-05", "Region": "Western Area", "District or Town": "Western Area Rural", "Covered Communities": "Jui, Grafton, Hastings, Waterloo, Tokeh, Lakka", "Installation Type": "Both", "Standard Visit Fee SLE": 200, "Transport Fee SLE": 80, "Additional Device Fee SLE": 50, "Service Available": "On Request", "Assigned Technician ID": "STAFF-03", "Notes": "Scheduled visit or remote setup"},
    {"Zone ID": "ZONE-06", "Region": "Provinces", "District or Town": "Bo / Kenema / Makeni / Kono", "Covered Communities": "Bo, Kenema, Makeni, Koidu, Port Loko, Lungi", "Installation Type": "Remote", "Standard Visit Fee SLE": 0, "Transport Fee SLE": 0, "Additional Device Fee SLE": 0, "Service Available": "Yes", "Assigned Technician ID": "STAFF-04", "Notes": "Remote WhatsApp guided setup"},
]

