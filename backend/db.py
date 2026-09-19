"""Centralized, shared storage for customer interaction history and Next
Best Action (offer impression/click) data - see nba_engine.py.

This is deliberately NOT the same store as sessions.py (in-memory chat
transcripts, resets on restart) or metrics.py/audit.py (anonymized JSONL
files, local to whoever's machine runs the app). Those work fine for their
own purposes, but the NBA engine needs something that (a) survives a
restart and (b) is shared across everyone running this app - two people
running it on their own laptops should see the SAME customer history and
the SAME learned offer performance, not two separate copies.

Configured via the DATABASE_URL env var (see config.py) - point it at a
shared, hosted Postgres instance (a free Neon/Supabase/Railway project all
work fine with plain SQLAlchemy) so this is genuinely centralized. Falls
back to a local SQLite file if unset, so the app still runs standalone
without any setup - see the README note this module's docstring is paired
with for the recommended hosted option and why.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    func,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


class CustomerInteraction(Base):
    """One row per /api/chat turn where the customer was identity-verified
    - the "previous interactions" and "latest interaction" history the NBA
    engine reads to decide which offers are relevant to this customer."""

    __tablename__ = "customer_interactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String(32), nullable=False, index=True)
    session_id = Column(String(64), nullable=True)
    topic = Column(String(64), nullable=False)
    case_id = Column(String(32), nullable=True)
    ts = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class OfferStat(Base):
    """Thompson-sampling (Beta-Bernoulli) parameters for one (segment,
    offer) pair - the "adaptive ML model" the NBA engine samples from to
    rank offers, and updates as impressions resolve/clicks arrive. Global
    across customers rather than per-customer: at the data volume a handful
    of demo customers can generate, per-customer bandit state would never
    accumulate enough signal to mean anything, whereas segment-level state
    reflects everyone's behaviour in that context - the standard scoping
    choice for a cold-start recommender."""

    __tablename__ = "offer_stats"

    segment = Column(String(64), primary_key=True)
    offer_code = Column(String(64), primary_key=True)
    alpha = Column(Float, nullable=False, default=1.0)
    beta = Column(Float, nullable=False, default=1.0)


class ContactRuleSettings(Base):
    """Marketing-editable Contact Rules that used to be hardcoded constants
    in nba_engine.py - a singleton row (id=1) so every process reads the
    SAME live settings from the shared database instead of whatever value
    was baked in at import time on whichever machine happens to be running.
    See /api/contact-rules in main.py (MARKETING role only)."""

    __tablename__ = "contact_rule_settings"

    id = Column(Integer, primary_key=True)
    offer_click_cooldown_seconds = Column(Integer, nullable=False, default=120)


class OfferTierRestriction(Base):
    """Presence of a (offer_code, tier) row means that offer IS eligible
    for that customer tier. An offer with NO rows at all is eligible for
    every tier (the default, unrestricted, backward-compatible state) -
    see nba_engine.get_offers_for_customer."""

    __tablename__ = "offer_tier_restrictions"

    offer_code = Column(String(64), primary_key=True)
    tier = Column(String(32), primary_key=True)


class OfferEvent(Base):
    """An impression or a click, per customer per offer - the raw feedback
    log the bandit's alpha/beta updates are derived from, and itself useful
    for reporting (e.g. "which offers actually get clicked")."""

    __tablename__ = "offer_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String(32), nullable=False, index=True)
    offer_code = Column(String(64), nullable=False)
    segment = Column(String(64), nullable=False)
    event_type = Column(String(16), nullable=False)  # "impression" | "click"
    resolved = Column(Boolean, nullable=False, default=False)  # impressions only
    ts = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def _local_sqlite_url() -> str:
    return "sqlite:///" + str(Path(__file__).resolve().parent / "nba.db")


def _make_engine(database_url: str):
    connect_args = {}
    if database_url.startswith(("postgresql://", "postgresql+")):
        # Keep a bad/unreachable hosted DB from blocking the whole API startup.
        connect_args["connect_timeout"] = 3
    return create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)


_engine = _make_engine(config.DATABASE_URL)
_SessionLocal = sessionmaker(bind=_engine)


def init_db() -> None:
    global _engine, _SessionLocal
    try:
        Base.metadata.create_all(_engine)
    except SQLAlchemyError:
        if config.DATABASE_URL.startswith("sqlite:///"):
            raise
        fallback_url = _local_sqlite_url()
        _engine = _make_engine(fallback_url)
        _SessionLocal.configure(bind=_engine)
        Base.metadata.create_all(_engine)


def _session() -> Session:
    return _SessionLocal()


def record_interaction(
    customer_id: str, session_id: str | None, topic: str, case_id: str | None
) -> None:
    with _session() as db:
        db.add(CustomerInteraction(
            customer_id=customer_id, session_id=session_id, topic=topic, case_id=case_id,
        ))
        db.commit()


def get_customer_topics(customer_id: str, lookback_days: int = 180) -> set[str]:
    """Every topic this customer has engaged with recently - the "previous
    interactions" half of the NBA eligibility check."""
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    with _session() as db:
        rows = (
            db.query(CustomerInteraction.topic)
            .filter(CustomerInteraction.customer_id == customer_id, CustomerInteraction.ts >= since)
            .distinct()
            .all()
        )
        return {r[0] for r in rows}


def get_customer_interactions(customer_id: str, limit: int = 25) -> list[dict]:
    """Most recent interactions for one customer - the raw material for the
    chat widget's interaction-history panel (see interaction_history.py),
    which turns this into a customer-friendly mini-portfolio view."""
    with _session() as db:
        rows = (
            db.query(CustomerInteraction)
            .filter(CustomerInteraction.customer_id == customer_id)
            .order_by(CustomerInteraction.ts.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "topic": r.topic,
                "case_id": r.case_id,
                "session_id": r.session_id,
                "ts": r.ts,
            }
            for r in rows
        ]


def get_recently_clicked_offer_codes(customer_id: str, within_seconds: int = 120) -> set[str]:
    """Offer codes this customer clicked within the last `within_seconds` -
    used to suppress re-showing the exact same offer right after they just
    clicked it (e.g. they open a new chat a minute later). A short, fixed
    cooldown rather than a permanent "never show again": the click is a
    positive signal (already counted via alpha in offer_stats), not a
    request to stop seeing it forever."""
    since = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
    with _session() as db:
        rows = (
            db.query(OfferEvent.offer_code)
            .filter(
                OfferEvent.customer_id == customer_id,
                OfferEvent.event_type == "click",
                OfferEvent.ts >= since,
            )
            .distinct()
            .all()
        )
        return {r[0] for r in rows}


def get_or_create_offer_stat(db: Session, segment: str, offer_code: str) -> OfferStat:
    stat = db.get(OfferStat, {"segment": segment, "offer_code": offer_code})
    if stat is None:
        stat = OfferStat(segment=segment, offer_code=offer_code, alpha=1.0, beta=1.0)
        db.add(stat)
        db.flush()
    return stat


def resolve_stale_impressions(customer_id: str) -> None:
    """An offer impression that's still unresolved by the time this
    customer is shown offers again (i.e. they didn't click it in between)
    counts as a "not clicked" signal - increment that (segment, offer)
    pair's beta and mark it resolved so it's never counted twice."""
    with _session() as db:
        stale = (
            db.query(OfferEvent)
            .filter(
                OfferEvent.customer_id == customer_id,
                OfferEvent.event_type == "impression",
                OfferEvent.resolved.is_(False),
            )
            .all()
        )
        for event in stale:
            stat = get_or_create_offer_stat(db, event.segment, event.offer_code)
            stat.beta += 1.0
            event.resolved = True
        db.commit()


def record_offer_impression(customer_id: str, segment: str, offer_code: str) -> None:
    with _session() as db:
        db.add(OfferEvent(
            customer_id=customer_id, offer_code=offer_code, segment=segment,
            event_type="impression", resolved=False,
        ))
        db.commit()


def record_offer_click(customer_id: str, offer_code: str) -> str | None:
    """Marks the most recent unresolved impression of this offer for this
    customer as a click (alpha += 1), so the bandit gets a strong positive
    signal. Returns the segment it was shown under, if found."""
    with _session() as db:
        impression = (
            db.query(OfferEvent)
            .filter(
                OfferEvent.customer_id == customer_id,
                OfferEvent.offer_code == offer_code,
                OfferEvent.event_type == "impression",
                OfferEvent.resolved.is_(False),
            )
            .order_by(OfferEvent.ts.desc())
            .first()
        )
        segment = impression.segment if impression else "general"

        if impression:
            impression.resolved = True
            stat = get_or_create_offer_stat(db, segment, offer_code)
            stat.alpha += 1.0

        db.add(OfferEvent(
            customer_id=customer_id, offer_code=offer_code, segment=segment,
            event_type="click", resolved=True,
        ))
        db.commit()
        return segment


def sample_offer_score(segment: str, offer_code: str) -> float:
    """One Thompson-sampling draw for this (segment, offer) pair - the
    "adaptive" part of the model: pairs with more clicks relative to
    impressions get a higher expected score and win more often over time,
    while still leaving room for less-proven offers to occasionally surface
    (exploration), rather than freezing onto whatever looked best early on."""
    import random

    with _session() as db:
        stat = get_or_create_offer_stat(db, segment, offer_code)
        db.commit()
        return random.betavariate(stat.alpha, stat.beta)


# --- Contact Rules (Marketing role, see /api/contact-rules in main.py) ----

DEFAULT_OFFER_CLICK_COOLDOWN_SECONDS = 120


def get_cooldown_seconds() -> int:
    with _session() as db:
        row = db.get(ContactRuleSettings, 1)
        if row is None:
            row = ContactRuleSettings(id=1, offer_click_cooldown_seconds=DEFAULT_OFFER_CLICK_COOLDOWN_SECONDS)
            db.add(row)
            db.commit()
        return row.offer_click_cooldown_seconds


def set_cooldown_seconds(seconds: int) -> None:
    with _session() as db:
        row = db.get(ContactRuleSettings, 1)
        if row is None:
            row = ContactRuleSettings(id=1, offer_click_cooldown_seconds=seconds)
            db.add(row)
        else:
            row.offer_click_cooldown_seconds = seconds
        db.commit()


def get_offer_tier_restrictions() -> dict[str, list[str]]:
    """offer_code -> list of tiers it's eligible for. An offer with no key
    here has no restriction (eligible for every tier) - see
    OfferTierRestriction's docstring."""
    with _session() as db:
        rows = db.query(OfferTierRestriction).all()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row.offer_code, []).append(row.tier)
        return result


def set_offer_tier_restrictions(offer_code: str, tiers: list[str]) -> None:
    """Replaces the full set of eligible tiers for one offer. An empty
    list removes the restriction entirely (eligible for every tier again)."""
    with _session() as db:
        db.query(OfferTierRestriction).filter(OfferTierRestriction.offer_code == offer_code).delete()
        for tier in tiers:
            db.add(OfferTierRestriction(offer_code=offer_code, tier=tier))
        db.commit()
