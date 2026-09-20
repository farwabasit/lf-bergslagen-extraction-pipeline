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

from datetime import datetime, timedelta, timezone

from . import cs_client, db
from .interaction_history import TOPIC_LABELS
from .knowledge import CUSTOMER_TIER_SPREADS_PERCENT

# Sample marketing offers. Illustrative pricing/terms for the demo, not real
# LF Bergslagen products - a real deployment would source these (and their
# images) from the bank's actual product/campaign management system, not a
# hardcoded catalog. Images are local SVGs (frontend/assets/offers/) so the
# demo has no external network dependency. `segments` are topic_classifier.py
# topic codes this offer is relevant to; "general" makes an offer eligible
# for every verified customer regardless of history, as a safe fallback so
# nobody with sparse history sees nothing.
#
# `product_family` ties an offer to the PRODUCT_FAMILY_KEYWORDS entry (below)
# used to check whether the customer already has that kind of product - see
# _owns_product_family. An offer with no product_family (e.g. loan
# protection, a rider on a mortgage rather than a standalone product) is
# never suppressed this way.
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
        "product_family": "mortgage",
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
        "product_family": "mortgage",
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
        "product_family": None,
    },
    {
        "code": "investment_savings",
        "title": "Investment products — put your savings to work",
        "teaser": "Fund and ISK options to grow your money over time, matched to your risk comfort.",
        "image": "assets/offers/investment.svg",
        "category": "Investment",
        "cta_label": "Explore investing",
        "cta_page": "savings",
        "segments": ["portfolio_inquiry", "general"],
        "product_family": "investment",
    },
    {
        "code": "retail_investment_isk",
        "title": "ISK — Investment Savings Account",
        "teaser": "A flexible, tax-simple way to invest in funds and shares, with no capital gains tax to report.",
        "image": "assets/offers/retail_investment.svg",
        "category": "Investment",
        "cta_label": "Open an ISK",
        "cta_page": "savings",
        "segments": ["portfolio_inquiry", "general"],
        "product_family": "investment",
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
        "product_family": "pension",
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
        "product_family": "car_insurance",
    },
    {
        "code": "car_insurance_new_car",
        "title": "New Car Insurance — covered from day one",
        "teaser": "Just bought or about to buy a car? Get a personalized quote in minutes.",
        "image": "assets/offers/car_insurance_new_car.svg",
        "category": "Insurance",
        "cta_label": "Get a quote",
        "cta_page": "car_insurance",
        "segments": ["car_repair", "general"],
        "product_family": "car_insurance",
    },
]

_BY_CODE = {o["code"]: o for o in OFFERS}

# Same tier names knowledge.CUSTOMER_TIER_SPREADS_PERCENT uses for mortgage
# pricing - single source of truth for what a Contact Rules tier
# restriction is allowed to name.
VALID_TIERS = list(CUSTOMER_TIER_SPREADS_PERCENT.keys())

# Case types (cs-service's CaseType.java) that mean "already applying for a
# mortgage" even before it's an approved product in the customer's
# portfolio - showing a mortgage ad to someone mid-application is the same
# mistake as showing one to someone who already has a mortgage.
OPEN_MORTGAGE_CASE_TYPES = {"MORTGAGE_APPLICATION", "MORTGAGE_REVIEW", "MORTGAGE_OPERATIONS"}


def _owns_product_family(customer_id: str, family: str | None) -> bool:
    """True if the customer's existing portfolio already has a product in
    this family - each portfolio entry in knowledge.MOCK_CUSTOMERS carries
    its own `category`, matched directly against the offer's
    product_family (both use the same keys: "mortgage", "car_insurance",
    "investment", "pension", ...). An offer with no product_family (family
    is None) is never considered owned."""
    if not family:
        return False
    from .knowledge import MOCK_CUSTOMERS

    customer = next((c for c in MOCK_CUSTOMERS if c["customer_id"] == customer_id), None)
    if not customer:
        return False
    return any(product.get("category") == family for product in customer.get("portfolio", []))


def _has_open_mortgage_case(customer_id: str) -> bool:
    """True if the customer has a mortgage case that's still open (not yet
    RESOLVED) - checked via cs-service's narrow, unauthenticated
    /customer-view read (see CaseController.java), the same one the
    interaction-history panel uses. Fails soft: if cs-service can't be
    reached, this just doesn't suppress the offer rather than erroring."""
    for row in db.get_customer_interactions(customer_id, limit=25):
        if not row["case_id"]:
            continue
        case = cs_client.get_case_for_customer(row["case_id"], customer_id)
        if case and case.get("type") in OPEN_MORTGAGE_CASE_TYPES and case.get("status") != "RESOLVED":
            return True
    return False


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


def _customer_tier(customer_id: str) -> str | None:
    from .knowledge import MOCK_CUSTOMERS

    customer = next((c for c in MOCK_CUSTOMERS if c["customer_id"] == customer_id), None)
    return customer.get("tier") if customer else None


def get_offers_for_customer(customer_id: str, current_topic: str, top_n: int = 3) -> list[dict]:
    """Everything the frontend needs to render up to `top_n` offer cards.
    Also records an impression for each one returned - see the module
    docstring for why that's the training signal the bandit needs."""
    db.resolve_stale_impressions(customer_id)

    context_topics = db.get_customer_topics(customer_id) | {current_topic}

    eligible: list[tuple[dict, str]] = []
    for offer in OFFERS:
        segments = set(offer["segments"])
        matched = segments & context_topics
        if matched:
            eligible.append((offer, next(iter(matched))))
        elif "general" in segments:
            eligible.append((offer, "general"))

    if not eligible:
        eligible = [(o, "general") for o in OFFERS if "general" in o["segments"]]

    # Never pitch a product the customer already has - e.g. "Home Loan —
    # a rate built around you" to someone whose portfolio already lists a
    # mortgage, or who's mid-way through one (see _has_open_mortgage_case).
    # Computed once up front, not per offer, so a mortgage-heavy eligible
    # list doesn't mean repeat lookups for the same answer.
    has_open_mortgage = any(o["product_family"] == "mortgage" for o, _ in eligible) and _has_open_mortgage_case(customer_id)
    eligible = [
        (offer, segment) for offer, segment in eligible
        if not _owns_product_family(customer_id, offer["product_family"])
        and not (offer["product_family"] == "mortgage" and has_open_mortgage)
    ]

    # Marketing-editable targeting (see /api/contact-rules, MARKETING role):
    # an offer with tier restrictions set is only shown to a customer in one
    # of those tiers - e.g. reserving a Private Banking-only investment
    # product from being pitched to a Standard-tier customer.
    tier_restrictions = db.get_offer_tier_restrictions()
    customer_tier = _customer_tier(customer_id)
    eligible = [
        (offer, segment) for offer, segment in eligible
        if not tier_restrictions.get(offer["code"]) or customer_tier in tier_restrictions[offer["code"]]
    ]

    # Marketing-editable cooldown (see /api/contact-rules) - was a hardcoded
    # constant; now the SAME live setting every process reads, so an admin
    # change takes effect immediately without a restart.
    cooldown_seconds = db.get_cooldown_seconds()
    recently_clicked = db.get_recently_clicked_offer_codes(customer_id, cooldown_seconds)
    eligible = [(offer, segment) for offer, segment in eligible if offer["code"] not in recently_clicked]

    scored = sorted(
        ((offer, segment, db.sample_offer_score(segment, offer["code"])) for offer, segment in eligible),
        key=lambda item: item[2],
        reverse=True,
    )

    selected = scored[:top_n]
    for offer, segment, _score in selected:
        db.record_offer_impression(customer_id, segment, offer["code"])

    return [_public_fields(offer) for offer, _segment, _score in selected]


def list_offers_for_admin() -> list[dict]:
    """Every offer plus its current targeting state, for the Contact Rules
    admin panel (MARKETING role) - unlike _public_fields, this is never
    sent to a customer, so it's fine to include product_family/segments."""
    tier_restrictions = db.get_offer_tier_restrictions()
    return [
        {
            "code": offer["code"],
            "title": offer["title"],
            "category": offer["category"],
            "product_family": offer["product_family"],
            "segments": offer["segments"],
            "tiers": tier_restrictions.get(offer["code"], []),  # [] = every tier
        }
        for offer in OFFERS
    ]


def record_click(customer_id: str, offer_code: str) -> bool:
    if offer_code not in _BY_CODE:
        return False
    db.record_offer_click(customer_id, offer_code)
    return True


# --- Offer performance (Marketing dashboard) ----------------------------
#
# Built straight from db.OfferEvent - the same raw impression/click log the
# bandit (record_offer_impression/record_offer_click, db.py) already
# writes to for its own learning, read here instead for human reporting:
# which offers are actually landing, which aren't, where they're being
# shown, and how much volume there's been. No new tracking needed.

RANGE_TO_DAYS = {"week": 7, "month": 30, "year": 365}


def _offer_info(code: str) -> dict:
    offer = _BY_CODE.get(code)
    return {
        "code": code,
        "title": offer["title"] if offer else code,
        "category": offer["category"] if offer else "Other",
    }


def build_offer_performance(range_key: str = "month") -> dict:
    """Everything the Marketing dashboard's offer-performance panels need,
    filtered to the last week/month/year (`range_key`, default month):
    top-clicked offers, offers with impressions but zero clicks, which
    offers are shown most within each customer segment (topic_classifier.py
    topic), and total volume split by category."""
    days = RANGE_TO_DAYS.get(range_key, RANGE_TO_DAYS["month"])
    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = db.get_offer_events_since(since)

    impressions_by_offer: dict[str, int] = {}
    clicks_by_offer: dict[str, int] = {}
    impressions_by_segment: dict[str, dict[str, int]] = {}
    impressions_by_category: dict[str, int] = {}

    for event in events:
        code = event["offer_code"]
        if event["event_type"] == "impression":
            impressions_by_offer[code] = impressions_by_offer.get(code, 0) + 1
            by_offer = impressions_by_segment.setdefault(event["segment"], {})
            by_offer[code] = by_offer.get(code, 0) + 1
            category = _offer_info(code)["category"]
            impressions_by_category[category] = impressions_by_category.get(category, 0) + 1
        elif event["event_type"] == "click":
            clicks_by_offer[code] = clicks_by_offer.get(code, 0) + 1

    performance = []
    for code in set(impressions_by_offer) | set(clicks_by_offer):
        impressions = impressions_by_offer.get(code, 0)
        clicks = clicks_by_offer.get(code, 0)
        performance.append({
            **_offer_info(code),
            "impressions": impressions,
            "clicks": clicks,
            "ctr_pct": round(clicks / impressions * 100, 1) if impressions else 0.0,
        })

    top_clicked = sorted(
        (p for p in performance if p["clicks"] > 0), key=lambda p: p["clicks"], reverse=True
    )[:5]
    # Zero interest requires at least one impression - an offer never shown
    # this period isn't "failing to generate interest", it just hasn't run.
    zero_interest = sorted(
        (p for p in performance if p["impressions"] > 0 and p["clicks"] == 0),
        key=lambda p: p["impressions"], reverse=True,
    )

    segment_breakdown = []
    for segment, offers in impressions_by_segment.items():
        top_offers = sorted(offers.items(), key=lambda kv: kv[1], reverse=True)[:3]
        segment_breakdown.append({
            "segment": segment,
            "segment_label": TOPIC_LABELS.get(segment, segment.replace("_", " ").capitalize()),
            "total_impressions": sum(offers.values()),
            "offers": [{**_offer_info(code), "impressions": count} for code, count in top_offers],
        })
    segment_breakdown.sort(key=lambda s: s["total_impressions"], reverse=True)

    category_summary = sorted(
        ({"category": cat, "impressions": count} for cat, count in impressions_by_category.items()),
        key=lambda c: c["impressions"], reverse=True,
    )

    total_impressions = sum(impressions_by_offer.values())
    total_clicks = sum(clicks_by_offer.values())

    return {
        "range": range_key,
        "days": days,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "overall_ctr_pct": round(total_clicks / total_impressions * 100, 1) if total_impressions else 0.0,
        "top_clicked": top_clicked,
        "zero_interest": zero_interest,
        "segment_breakdown": segment_breakdown,
        "category_summary": category_summary,
    }
