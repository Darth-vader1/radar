import logging
from dataclasses import dataclass, field
from typing import List

import dns.resolver
from email_validator import EmailNotValidError, validate_email

from app.models.business import VerificationStatus

logger = logging.getLogger("radar.businesses.email_verifier")

# Known disposable / throwaway email provider domains
DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "guerrillamail.com", "10minutemail.com",
    "throwawaymail.com", "yopmail.com", "sharklasers.com", "getairmail.com"
}

# Role-based mailbox prefixes
ROLE_BASED_PREFIXES = {
    "info", "contact", "support", "sales", "hello", "admin", "office",
    "help", "enquiries", "general", "billing", "careers", "jobs"
}


@dataclass
class EmailVerificationResult:
    email: str
    syntax_valid: bool
    domain: str
    status: VerificationStatus
    mx_records_found: bool
    mx_hosts: List[str] = field(default_factory=list)
    disposable_domain: bool = False
    role_based_prefix: bool = False
    confidence_score: float = 0.0
    explanation: str = ""


class EmailVerifierService:
    """
    Validates syntax, checks disposable status, and resolves DNS MX records.
    Never invents emails.
    """

    def __init__(self, dns_timeout: float = 4.0):
        self.dns_timeout = dns_timeout

    def verify_email(self, email_str: str) -> EmailVerificationResult:
        if not email_str or not email_str.strip():
            return EmailVerificationResult(
                email="",
                syntax_valid=False,
                domain="",
                status=VerificationStatus.MISSING,
                mx_records_found=False,
                explanation="Email address was not provided."
            )

        clean_email = email_str.strip().lower()

        # 1. Syntax Validation
        try:
            valid_info = validate_email(clean_email, check_deliverability=False)
            normalized_email = valid_info.normalized
            domain = valid_info.domain.lower()
            local_part = valid_info.local_part.lower()
        except EmailNotValidError as e:
            return EmailVerificationResult(
                email=clean_email,
                syntax_valid=False,
                domain="",
                status=VerificationStatus.INVALID,
                mx_records_found=False,
                confidence_score=0.0,
                explanation=f"Syntax validation failed: {e}"
            )

        # 2. Check disposable domain
        is_disposable = domain in DISPOSABLE_DOMAINS
        if is_disposable:
            return EmailVerificationResult(
                email=normalized_email,
                syntax_valid=True,
                domain=domain,
                status=VerificationStatus.INVALID,
                mx_records_found=False,
                disposable_domain=True,
                confidence_score=0.0,
                explanation="Domain belongs to a known temporary/disposable mailbox provider."
            )

        # 3. Check role-based prefix
        is_role_based = local_part in ROLE_BASED_PREFIXES

        # 4. Check DNS MX records
        mx_hosts: List[str] = []
        has_mx = False
        try:
            resolver = dns.resolver.Resolver()
            resolver.lifetime = self.dns_timeout
            answers = resolver.resolve(domain, "MX")
            for rdata in answers:
                mx_hosts.append(str(rdata.exchange).rstrip("."))
            has_mx = len(mx_hosts) > 0
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.Timeout, Exception) as exc:
            logger.debug("DNS MX lookup failed for %s: %s", domain, exc)
            has_mx = False

        if not has_mx:
            # Check fallback A record
            try:
                resolver = dns.resolver.Resolver()
                resolver.lifetime = self.dns_timeout
                answers = resolver.resolve(domain, "A")
                has_a = len(answers) > 0
            except Exception:
                has_a = False

            if not has_a:
                return EmailVerificationResult(
                    email=normalized_email,
                    syntax_valid=True,
                    domain=domain,
                    status=VerificationStatus.INVALID,
                    mx_records_found=False,
                    confidence_score=0.1,
                    explanation=f"Domain {domain} does not have valid MX or A DNS records."
                )

        # Confidence assessment
        status_val = VerificationStatus.UNVERIFIED
        confidence = 0.50

        if has_mx:
            status_val = VerificationStatus.VERIFIED
            confidence = 0.85 if is_role_based else 0.75
            explanation = f"Valid syntax and active MX mail servers detected ({', '.join(mx_hosts[:2])})."
        else:
            explanation = "Valid syntax and domain active, but no dedicated MX mail servers found."

        return EmailVerificationResult(
            email=normalized_email,
            syntax_valid=True,
            domain=domain,
            status=status_val,
            mx_records_found=has_mx,
            mx_hosts=mx_hosts,
            disposable_domain=is_disposable,
            role_based_prefix=is_role_based,
            confidence_score=confidence,
            explanation=explanation,
        )
