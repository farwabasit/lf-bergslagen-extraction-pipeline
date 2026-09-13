"""Document Extraction & Verification agent: reads the mortgage documents
the customer attached (purchase agreement, income statement/payslip,
expenses info), extracts the data fields the mortgage agent needs, and
flags the case for manual review by a Customer Advisor if the purchase
agreement contains anything a human should look at. This is the one place
in the mortgage pipeline where an LLM call is appropriate - reading and
classifying free-form document text is genuine NLP, unlike the calculations
downstream, which stay deterministic."""

import json
import re

from .. import audit, config
from ..llm_client import client

EXTRACTION_PROMPT = """You are a document-extraction specialist for a Swedish
bank's mortgage process. You will be given one or more attached documents
(filename + text). Classify each one as one of: "purchase_agreement"
(köpekontrakt/köpeavtal for a property), "income_statement" (payslip/
lönebesked or employer income statement), "expenses" (a summary of the
applicant's monthly living expenses), or "other" (anything that doesn't fit).

For each document, extract the following fields when present (use null for
anything not stated - never invent a value):

purchase_agreement: property_address, purchase_price_sek (number), buyer_name,
  seller_name, closing_date, special_conditions (array of strings - any
  contingency, dispute, non-standard clause, or condition beyond a normal
  sale; empty array if none)

income_statement: employer, monthly_gross_income_sek (number), employment_type
  (e.g. "permanent", "fixed-term", "probationary"), employment_start_date

expenses: monthly_expenses_total_sek (number), categories (object of
  category name -> SEK amount)

Also decide needs_review (true/false) and review_reason (string or null):
set needs_review true if the purchase agreement has any special_conditions,
if employment_type suggests unstable income (probationary/fixed-term with
under 6 months remaining), or if a document's content looks inconsistent,
incomplete, or hard to classify confidently.

Respond with ONLY a JSON object, no markdown, no explanation, in this shape:
{
  "purchase_agreement": {...} or null,
  "income_statement": {...} or null,
  "expenses": {...} or null,
  "unclassified_documents": ["filename", ...],
  "needs_review": true/false,
  "review_reason": "..." or null
}
"""

JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_and_verify(documents: list[dict]) -> dict:
    """documents: list of {"filename": str, "text": str}. Returns the
    extraction result (see EXTRACTION_PROMPT) and logs the full input/output
    to the audit trail - the raw document text isn't logged (data
    minimization; the extracted fields are what matters for the decision
    trail), only filenames and the structured result are."""
    doc_block = "\n\n".join(
        f"--- Document: {d['filename']} ---\n{d['text'][:4000]}" for d in documents
    )

    try:
        response = client.chat.completions.create(
            model=config.OPENROUTER_MODEL,
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": doc_block},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or "{}"
        match = JSON_OBJECT_RE.search(content)
        result = json.loads(match.group(0) if match else content)
    except Exception as exc:
        result = {
            "purchase_agreement": None,
            "income_statement": None,
            "expenses": None,
            "unclassified_documents": [d["filename"] for d in documents],
            "needs_review": True,
            "review_reason": f"Automatic extraction failed ({exc.__class__.__name__}); needs manual handling.",
        }

    audit.record_event(
        agent="document_agent",
        action="extract_and_verify",
        customer_id=None,
        decision="NEEDS_REVIEW" if result.get("needs_review") else "EXTRACTED",
        details={
            "document_filenames": [d["filename"] for d in documents],
            "extraction_result": result,
        },
    )
    return result
