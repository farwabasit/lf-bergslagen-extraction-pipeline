"""Next Best Action (NBA) engine: decides which marketing offers to show a
just-verified customer, based on their interaction history (topics they've
engaged with over time - see db.get_customer_topics) and the topic of what
they're doing right now.

The "adaptive machine learning" part is a contextual multi-armed bandit
(Thompson Sampling over a Beta-Bernoulli model per (segment, offer) pair -
see db.OfferStat): every time an offer is shown, that's an impression;
if it's clicked, alpha increases; if a customer is shown offers again
without ever clicking that impression, beta increases. Ranking offers by a
random draw from each pair's current Beta(alpha, beta) distribution (rather
than by a flat click-through rate) is what gives the bandit real
exploration - an offer with few impressions so far still gets a fair chance
to be shown and prove itself, instead of never recovering from an unlucky
first showing. This is the standard approach for this exact problem (online
ranking under sparse feedback) - deliberately not a heavier model (e.g. a
trained classifier) that would need far more data than a handful of demo
customers can ever generate to be meaningfully better than the bandit.

Never called for an unverified customer - main.py only invokes this right
after tools.verify_customer_identity (or the fraud/dispute flow's own
identity check) succeeds this turn, via verified_customer.get_and_clear().
"""

from . import db

# Sample marketing offers. Illustrative pricing/terms for the demo, not real
# LF Bergslagen products - a real deployment would source these (and their
# images) from the bank's actual product/campaign management system, not a
# hardcoded catalog. Images are local SVGs (frontend/assets/offers/) so the
# demo has no external network dependency. `segments` are topic_classifier.py
# topic codes this offer is relevant to; "general" makes an offer eligible
# for every verified customer regardless of history, as a safe fallback so
# nobody with sparse history sees nothing.
OFFERS = [
    {
        "code": "home_loan_promo",
        "title": "Home Loan — a rate built around you",
        "teaser": "Personal pricing, free loan protection for 3 months, and a fast digital application.",
        "image": "assets/offers/home_loan.svg",
        "category": "Mortgage",
        "cta_label": "See today's rates",
        "cta_page": "home_loan",
        "segments": ["mortgage_loan_promise", "mortgage_loan_offer", "home_purchase_advisory"],
    },
    {
        "code": "green_mortgage",
        "title": "Green Mortgage — a lower rate for an energy-efficient home",
        "teaser": "If your home meets the energy criteria, you could qualify for a reduced interest rate.",
        "image": "assets/offers/green_mortgage.svg",
        "category": "Mortgage",
        "cta_label": "Check if you qualify",
        "cta_page": "home_loan",
        "segments": ["mortgage_loan_promise", "mortgage_loan_offer", "home_purchase_advisory"],
    },
    {
        "code": "loan_protection",
        "title": "Loan Protection — stay covered if life changes",
        "teaser": "Keep up with mortgage payments if you become unemployed or long-term ill.",
        "image": "assets/offers/loan_protection.svg",
        "category": "Insurance",
        "cta_label": "Learn more",
        "cta_page": "loan_protection_insurance",
        "segments": ["mortgage_loan_promise", "mortgage_loan_offer"],
    },
    {
        "code": "investment_savings",
        "title": "Investment products — put your savings to work",
        "teaser": "Fund and ISK options to grow your money over time, matched to your risk comfort.",
        "image": "assets/offers/investment.svg",
        "category": "Savings",
        "cta_label": "Explore investing",
        "cta_page": "savings",
        "segments": ["portfolio_inquiry", "general"],
    },
    {
        "code": "pension_savings",
        "title": "Pension Savings — start today, thank yourself later",
        "teaser": "A small monthly amount now can make a real difference to your retirement.",
        "image": "assets/offers/pension.svg",
        "category": "Pension",
        "cta_label": "Plan your pension",
        "cta_page": "pension",
        "segments": ["portfolio_inquiry", "general"],
    },
    {
        "code": "car_insurance_bundle",
        "title": "Car Insurance — bundle and save",
        "teaser": "Combine it with your other LF Bergslagen products for a better overall price.",
        "image": "assets/offers/car_insurance.svg",
        "category": "Insurance",
        "cta_label": "Compare cover",
        "cta_page": "car_insurance",
        "segments": ["car_repair", "general"],
    },
]

_BY_CODE = {o["code"]: o for o in OFFERS}


def _public_fields(offer: dict) -> dict:
    from .knowledge import LF_PAGES

    return {
        "code": offer["code"],
        "title": offer["title"],
        "teaser": offer["teaser"],
        "image": offer["image"],
        "category": offer["category"],
        "cta_label": offer["cta_label"],
        "cta_url": LF_PAGES.get(offer["cta_page"], ""),
    }


def get_offers_for_customer(customer_id: str, current_topic: str, top_n: int = 3) -> list[dict]:
    """Everything the frontend needs to render up to `top_n` offer cards.
    Also records an impression for each one returned - see the module
    docstring for why that's the training signal the bandit needs."""
    db.resolve_stale_impressions(customer_id)

    context_topics = db.get_customer_topics(customer_id) | {current_topic}

    # A customer who just applied for (or is applying for) a mortgage/Loan
    # Promise doesn't need another home loan pitched at them right after -
    # that reads as "you just gave me a loan, and now you're offering me a
    # loan?". Complementary products (loan protection insurance, etc.) still
    # make sense here; only the competing Mortgage-category offers are
    # excluded, and only when the CURRENT turn's topic is the mortgage
    # application itself (not just somewhere in older history).
    exclude_categories = {"Mortgage"} if current_topic in (
        "mortgage_loan_promise", "mortgage_loan_offer",
    ) else set()

    eligible: list[tuple[dict, str]] = []
    for offer in OFFERS:
        if offer["category"] in exclude_categories:
            continue
        segments = set(offer["segments"])
        matched = segments & context_topics
        if matched:
            eligible.append((offer, next(iter(matched))))
        elif "general" in segments:
            eligible.append((offer, "general"))

    if not eligible:
        eligible = [
            (o, "general") for o in OFFERS
            if "general" in o["segments"] and o["category"] not in exclude_categories
        ]

    scored = sorted(
        ((offer, segment, db.sample_offer_score(segment, offer["code"])) for offer, segment in eligible),
        key=lambda item: item[2],
        reverse=True,
    )

    selected = scored[:top_n]
    for offer, segment, _score in selected:
        db.record_offer_impression(customer_id, segment, offer["code"])

    return [_public_fields(offer) for offer, _segment, _score in selected]


def record_click(customer_id: str, offer_code: str) -> bool:
    if offer_code not in _BY_CODE:
        return False
    db.record_offer_click(customer_id, offer_code)
    return True
