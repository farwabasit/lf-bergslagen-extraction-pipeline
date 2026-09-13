# Whitelisted LF Bergslagen pages. The agent can only fetch one of these topics
# (never an arbitrary URL), which keeps the live-fetch tool safe and scoped.
LF_PAGES = {
    "overview": "https://www.lansforsakringar.se/bergslagen/privat/",
    "guides": "https://www.lansforsakringar.se/bergslagen/privat/tips-guider/",
    "home_insurance": "https://www.lansforsakringar.se/bergslagen/privat/forsakring/hemforsakring/",
    "car_insurance": "https://www.lansforsakringar.se/bergslagen/privat/forsakring/bilforsakring/",
    "accident_health_insurance": "https://www.lansforsakringar.se/bergslagen/privat/forsakring/personforsakring/olycksfall-sjukforsakring/",
    "child_insurance": "https://www.lansforsakringar.se/bergslagen/privat/forsakring/personforsakring/barnforsakring/",
    "home_loan": "https://www.lansforsakringar.se/bergslagen/privat/bank/bolan/",
    "loan_protection_insurance": "https://www.lansforsakringar.se/bergslagen/privat/bank/bolan/bolaneskydd/",
    "life_insurance": "https://www.lansforsakringar.se/bergslagen/privat/forsakring/personforsakring/livforsakring/",
    "become_bank_customer": "https://www.lansforsakringar.se/bergslagen/privat/bank/bli-bankkund/",
    "pension": "https://www.lansforsakringar.se/bergslagen/privat/pension/",
    "savings": "https://www.lansforsakringar.se/bergslagen/privat/bank/spara/",
    "customer_service": "https://www.lansforsakringar.se/privat/kundservice/",
}

# Mock partner network for the demo: local service providers LF Bergslagen
# coordinates with to actually carry out a claim (pick up/repair a car,
# restore water/fire damage, etc.). This is placeholder data for the
# prototype, not a real, live directory - swap for a real partner-lookup
# API/database before production use. Keyed by service category, then a
# list of providers across towns in the Örebro county / Bergslagen area.
SERVICE_PROVIDERS = {
    "car_repair": [
        {"city": "Örebro", "name": "Bergslagens Bilskadecenter", "address": "Verkstadsgatan 4, Örebro", "phone": "019-123 45 67", "hours": "Mon-Fri 07:00-17:00"},
        {"city": "Karlskoga", "name": "Karlskoga Bilverkstad AB", "address": "Industrigatan 12, Karlskoga", "phone": "0586-123 45", "hours": "Mon-Fri 07:30-16:30"},
        {"city": "Kumla", "name": "Kumla Motor & Plåt", "address": "Skjutbanevägen 3, Kumla", "phone": "019-987 65 43", "hours": "Mon-Fri 08:00-17:00"},
        {"city": "Lindesberg", "name": "Lindesbergs Bilcenter", "address": "Kopparvägen 8, Lindesberg", "phone": "0581-234 56", "hours": "Mon-Fri 07:00-16:00"},
        {"city": "Hallsberg", "name": "Hallsbergs Skadeverkstad", "address": "Stationsgatan 15, Hallsberg", "phone": "0582-345 67", "hours": "Mon-Fri 08:00-17:00"},
    ],
    "home_repair": [
        {"city": "Örebro", "name": "Bergslagen Skadeservice", "address": "Byggvägen 2, Örebro", "phone": "019-222 33 44", "hours": "Mon-Fri 07:00-18:00, on-call 24/7 for acute damage"},
        {"city": "Karlskoga", "name": "Karlskoga Sanering & Bygg", "address": "Hantverkargatan 6, Karlskoga", "phone": "0586-333 22 11", "hours": "Mon-Fri 07:00-17:00"},
        {"city": "Nora", "name": "Nora Byggskador AB", "address": "Kyrkogatan 9, Nora", "phone": "0587-111 22 33", "hours": "Mon-Fri 08:00-16:30"},
        {"city": "Askersund", "name": "Askersunds Fastighetsservice", "address": "Sundsvägen 5, Askersund", "phone": "0583-444 55 66", "hours": "Mon-Fri 08:00-17:00"},
    ],
    "health_care": [
        {"city": "Örebro", "name": "Örebro Vårdpartner", "address": "Hälsovägen 1, Örebro", "phone": "019-555 66 77", "hours": "Mon-Fri 08:00-17:00, drop-in mornings"},
        {"city": "Karlskoga", "name": "Karlskoga Hälsocentral Partner", "address": "Vårdgatan 3, Karlskoga", "phone": "0586-666 77 88", "hours": "Mon-Fri 08:00-16:30"},
        {"city": "Kumla", "name": "Kumla Rehab & Vård", "address": "Terapigatan 7, Kumla", "phone": "019-777 88 99", "hours": "Mon-Fri 08:00-17:00"},
    ],
}

# Mock customer directory for the fraud/dispute/portfolio demo flow: identity
# verification, transaction history, and product holdings. This is test data
# only, invented for the prototype - a real deployment would verify identity
# and look up transactions/products against LF Bergslagen's actual core
# systems, never against values hardcoded in source code.
MOCK_CUSTOMERS = [
    {
        "customer_id": "CUST-1001",
        "name": "Anna Andersson",
        "personnummer": "19850312-1234",
        "dob": "1985-03-12",
        "tier": "Standard",
        "portfolio": [
            "Home insurance (Villaförsäkring)",
            "Car insurance (Bilförsäkring) - Volvo XC60",
            "Savings account (Sparkonto)",
        ],
        "liabilities": [
            {"type": "Car loan", "lender": "LF Bergslagen", "monthlyPayment": 2500, "balance": 85000},
        ],
        "transactions": [
            {"id": "TXN-1001-01", "date": "2026-09-11", "merchant": "ICA Supermarket, Örebro", "amount": "-345.00 SEK"},
            {"id": "TXN-1001-02", "date": "2026-09-10", "merchant": "Circle K", "amount": "-620.50 SEK"},
            {"id": "TXN-1001-03", "date": "2026-09-09", "merchant": "Spotify", "amount": "-119.00 SEK"},
            {"id": "TXN-1001-04", "date": "2026-09-08", "merchant": "H&M", "amount": "-899.00 SEK"},
            {"id": "TXN-1001-05", "date": "2026-09-07", "merchant": "Systembolaget", "amount": "-450.00 SEK"},
            {"id": "TXN-1001-06", "date": "2026-09-05", "merchant": "Apotek Hjärtat", "amount": "-215.00 SEK"},
            {"id": "TXN-1001-07", "date": "2026-09-04", "merchant": "SL Reskassa", "amount": "-500.00 SEK"},
            {"id": "TXN-1001-08", "date": "2026-09-02", "merchant": "Max Burgers", "amount": "-129.00 SEK"},
            {"id": "TXN-1001-09", "date": "2026-08-31", "merchant": "Amazon.se", "amount": "-1249.00 SEK"},
            {"id": "TXN-1001-10", "date": "2026-08-29", "merchant": "Unknown merchant - overseas POS", "amount": "-3899.00 SEK"},
        ],
    },
    {
        "customer_id": "CUST-1002",
        "name": "Erik Svensson",
        "personnummer": "19900615-5678",
        "dob": "1990-06-15",
        "tier": "Premium",
        "portfolio": [
            "Home contents insurance (Hemförsäkring)",
            "Accident & health insurance",
            "Pension savings (Pensionssparande)",
        ],
        "liabilities": [
            {"type": "Student loan (CSN)", "lender": "CSN", "monthlyPayment": 1300, "balance": 210000},
            {"type": "Credit card", "lender": "LF Bergslagen", "monthlyPayment": 800, "balance": 18000},
        ],
        "transactions": [
            {"id": "TXN-1002-01", "date": "2026-09-11", "merchant": "Coop, Karlskoga", "amount": "-410.00 SEK"},
            {"id": "TXN-1002-02", "date": "2026-09-10", "merchant": "Preem", "amount": "-580.00 SEK"},
            {"id": "TXN-1002-03", "date": "2026-09-09", "merchant": "Netflix", "amount": "-139.00 SEK"},
            {"id": "TXN-1002-04", "date": "2026-09-08", "merchant": "Elgiganten", "amount": "-2499.00 SEK"},
            {"id": "TXN-1002-05", "date": "2026-09-06", "merchant": "Apoteket", "amount": "-180.00 SEK"},
            {"id": "TXN-1002-06", "date": "2026-09-05", "merchant": "SJ Biljetter", "amount": "-890.00 SEK"},
            {"id": "TXN-1002-07", "date": "2026-09-03", "merchant": "Pressbyrån", "amount": "-65.00 SEK"},
            {"id": "TXN-1002-08", "date": "2026-09-02", "merchant": "Clas Ohlson", "amount": "-349.00 SEK"},
            {"id": "TXN-1002-09", "date": "2026-08-30", "merchant": "Zalando", "amount": "-1099.00 SEK"},
            {"id": "TXN-1002-10", "date": "2026-08-28", "merchant": "Unknown merchant - foreign currency charge", "amount": "-2750.00 SEK"},
        ],
    },
]

# --- Mortgage agent mock market/policy data -------------------------------
# All illustrative demo values, not real LF Bergslagen rates or policy.
# Real deployment would source these from the bank's actual pricing engine
# and credit policy system, not hardcoded constants.

# Reference mortgage rate before any customer-tier spread is applied
# (illustrative "3-month reference rate + base margin" style figure).
MARKET_BASE_RATE_PERCENT = 3.19

# Added on top of the base rate depending on customer relationship tier.
CUSTOMER_TIER_SPREADS_PERCENT = {
    "Standard": 1.45,
    "Premium": 1.15,
    "Private Banking": 0.85,
}

# Deterministic retail credit decision policy for the demo credit agent.
# Mirrors real-world levers (DTI, LTV, minimum income) without claiming to
# be an actual BASEL/ECB-approved credit strategy.
CREDIT_POLICY = {
    "max_dti_percent": 45,       # debt-to-income: total monthly debt / gross monthly income
    "manual_review_dti_percent": 55,  # between max_dti and this: manual review, not auto-decline
    "max_ltv_percent": 85,       # loan-to-value, matching Sweden's statutory mortgage cap (amorteringskrav)
    "min_monthly_income_sek": 15000,
    "policy_version": "retail-mortgage-demo-v1",
}
