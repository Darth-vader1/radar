import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.models.event import EventStatus

CATEGORY_KEYWORDS = {
    "ai": [
        "artificial intelligence", "ai", "llm", "large language model", "generative ai",
        "genai", "gpt", "gemini", "neural network", "deep learning", "nlp", "computer vision",
        "transformers", "diffusion"
    ],
    "machine-learning": [
        "machine learning", "ml", "kaggle", "scikit", "pytorch", "tensorflow",
        "predictive model", "classification", "regression", "clustering", "xgboost"
    ],
    "data-science": [
        "data science", "data analytics", "data analysis", "big data", "bi", "data mining",
        "pandas", "jupyter", "visualization", "tableau"
    ],
    "web-dev": [
        "web dev", "web development", "full stack", "fullstack", "frontend", "backend",
        "react", "nextjs", "vue", "angular", "fastapi", "django", "node", "typescript"
    ],
    "mobile-dev": [
        "mobile", "android", "ios", "flutter", "react native", "swift", "kotlin", "mobile app"
    ],
    "cloud": [
        "cloud", "devops", "aws", "azure", "google cloud", "gcp", "kubernetes", "docker",
        "serverless", "infrastructure", "terraform"
    ],
    "blockchain": [
        "blockchain", "web3", "crypto", "smart contract", "ethereum", "solidity",
        "defi", "solana", "polygon", "bitcoin", "nft"
    ],
    "cybersecurity": [
        "cybersecurity", "cyber security", "infosec", "ethical hacking", "ctf", "capture the flag",
        "cryptography", "penetration testing", "vulnerability"
    ],
    "robotics": [
        "robotics", "hardware", "iot", "internet of things", "embedded", "arduino", "raspberry pi"
    ],
    "entrepreneurship": [
        "startup", "grant", "venture", "pitch", "founder", "accelerator", "incubator",
        "business plan", "innovation award", "seed funding"
    ],
}


def normalize_event_name(raw_name: str) -> str:
    """Cleans event titles, removing year suffixes, marketing prefixes, and punctuation."""
    if not raw_name:
        return ""
    # Strip emojis and leading/trailing whitespace
    cleaned = raw_name.strip()
    # Remove bracketed tags like [Global], [Virtual], (Online)
    cleaned = re.sub(r"\[.*?\]|\(.*?\)", "", cleaned)
    # Remove common prefixes like "Hackathon: ", "Announcing: "
    cleaned = re.sub(r"^(?:announcing|hackathon|introducing|welcome to)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    # Remove year tags like "2024", "2025", "2026"
    cleaned = re.sub(r"\b202[4-9]\b", "", cleaned)
    # Collapse extra whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.lower()


def compute_event_status(
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    registration_deadline: Optional[datetime],
    registration_opens_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> str:
    """
    Deterministically computes event lifecycle status:
    COMPLETED -> ONGOING -> REGISTRATION_CLOSED -> REGISTRATION_CLOSING_SOON -> UPCOMING -> OPEN_REGISTRATION
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Event completed check
    if end_date:
        e_date = end_date if end_date.tzinfo else end_date.replace(tzinfo=timezone.utc)
        if now > e_date:
            return EventStatus.COMPLETED.value

    # 2. Event ongoing check (between start_date and end_date)
    if start_date and end_date:
        s_date = start_date if start_date.tzinfo else start_date.replace(tzinfo=timezone.utc)
        e_date = end_date if end_date.tzinfo else end_date.replace(tzinfo=timezone.utc)
        if s_date <= now <= e_date:
            return EventStatus.ONGOING.value

    # 3. Registration deadline checks
    if registration_deadline:
        r_deadline = (
            registration_deadline
            if registration_deadline.tzinfo
            else registration_deadline.replace(tzinfo=timezone.utc)
        )
        if now > r_deadline:
            return EventStatus.REGISTRATION_CLOSED.value

        remaining_seconds = (r_deadline - now).total_seconds()
        # Closing within 7 days
        if 0 <= remaining_seconds <= (7 * 86400):
            return EventStatus.REGISTRATION_CLOSING_SOON.value

    # 4. Upcoming registration check
    if registration_opens_at:
        r_opens = (
            registration_opens_at
            if registration_opens_at.tzinfo
            else registration_opens_at.replace(tzinfo=timezone.utc)
        )
        if now < r_opens:
            return EventStatus.UPCOMING.value

    # Default: open for registration
    return EventStatus.OPEN_REGISTRATION.value


def parse_prize_amount(text: str) -> Tuple[bool, Optional[float], Optional[str]]:
    """
    Extracts cash prizes from descriptions without fabricating numbers.
    Supports USD, EUR, GBP, and NGN conversions to USD estimate.
    Returns (has_cash_prizes, prize_amount_usd_est, summary_string).
    """
    if not text:
        return False, None, None

    # Matches: $50,000 or $50k or 50,000 USD or €10,000 or ₦5,000,000
    usd_match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*(k|m|million|thousand)?", text, re.IGNORECASE)
    if usd_match:
        val_str = usd_match.group(1).replace(",", "")
        try:
            val = float(val_str)
            mult = (usd_match.group(2) or "").lower()
            if mult in ("k", "thousand"):
                val *= 1000
            elif mult in ("m", "million"):
                val *= 1000000
            return True, val, f"${val:,.0f} in prizes"
        except ValueError:
            pass

    usd_explicit = re.search(r"([\d,]+)\s*(?:usd|dollars)", text, re.IGNORECASE)
    if usd_explicit:
        try:
            val = float(usd_explicit.group(1).replace(",", ""))
            return True, val, f"${val:,.0f} USD in prizes"
        except ValueError:
            pass

    # Nigerian Naira (approx 1500 NGN = 1 USD for estimation, explicitly converted)
    ngn_match = re.search(r"(?:ngn|₦)\s*([\d,]+(?:\.\d+)?)\s*(k|m|million)?", text, re.IGNORECASE)
    if ngn_match:
        val_str = ngn_match.group(1).replace(",", "")
        try:
            val_ngn = float(val_str)
            mult = (ngn_match.group(2) or "").lower()
            if mult in ("m", "million"):
                val_ngn *= 1000000
            elif mult == "k":
                val_ngn *= 1000
            usd_est = round(val_ngn / 1500, 2)
            return True, usd_est, f"₦{val_ngn:,.0f} NGN (~${usd_est:,.0f} USD)"
        except ValueError:
            pass

    # Generic cash indicator without exact digits
    if re.search(r"\b(cash prizes?|cash awards?|monetary grant|grant funding)\b", text, re.IGNORECASE):
        return True, None, "Cash prizes available"

    return False, None, None


def classify_event_categories(name: str, description: str, tags: Optional[List[str]] = None) -> List[str]:
    """Matches text and existing tags against category taxonomy."""
    content = f"{name} {description}".lower()
    matched = set()

    # Match provided tags
    if tags:
        for tag in tags:
            tag_lower = tag.lower().strip()
            for cat_slug, kw_list in CATEGORY_KEYWORDS.items():
                if any(kw == tag_lower or kw in tag_lower for kw in kw_list):
                    matched.add(cat_slug)

    # Keyword search across content
    for cat_slug, kw_list in CATEGORY_KEYWORDS.items():
        for kw in kw_list:
            # Word boundary regex for short acronyms like 'ai', 'ml', 'ctf'
            if len(kw) <= 3:
                pattern = rf"\b{re.escape(kw)}\b"
            else:
                pattern = re.escape(kw)
            if re.search(pattern, content):
                matched.add(cat_slug)
                break

    if not matched:
        matched.add("other")

    return sorted(list(matched))
