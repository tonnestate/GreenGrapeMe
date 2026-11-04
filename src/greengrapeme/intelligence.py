"""Sourced signal scoring and reply prechecks, adapted from OpenOutbound.

Donor: xyluxx/openoutbound, Apache-2.0, revision
bc158cac6548ab54699442d159cc2130570b9a78.
Sources: src/modules/signals/scoring.ts, src/modules/inbox/prechecks.ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
import re


@dataclass(frozen=True)
class Signal:
    kind: str
    evidence_url: str
    observed_at: datetime
    strength: float = 1.0
    claim: str = ""

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.evidence_url.strip() or not self.claim.strip():
            raise ValueError("signal requires kind, evidence URL and source-grounded claim")
        if self.observed_at.tzinfo is None:
            raise ValueError("signal timestamp must have a time zone")
        if not isfinite(self.strength) or not 0 <= self.strength <= 1:
            raise ValueError("signal strength must be finite and between 0 and 1")


# Explicit starting policy, not a validated conversion probability.
DEFINITIONS: dict[str, tuple[int, int]] = {
    "job_change": (80, 60),
    "engagement_with_us": (70, 14),
    "new_exec_hire": (60, 45),
    "hiring_relevant_roles": (55, 30),
    "expansion_new_location": (50, 60),
    "funding_round": (45, 60),
    "tech_adopted": (40, 60),
    "website_change": (25, 21),
    "news_mention": (20, 14),
    "public_procurement": (50, 30),  # GreenGrapeMe-specific
}


def score_signals(signals: list[Signal], now: datetime) -> tuple[int, dict[str, int]]:
    """Decay, select strongest per category, combine by noisy-OR.

    The caller must independently review the source's authenticity.
    """
    if now.tzinfo is None:
        raise ValueError("current time must have a time zone")
    top: dict[str, int] = {}
    for signal in signals:
        if signal.kind not in DEFINITIONS:
            continue
        weight, half_life = DEFINITIONS[signal.kind]
        # An observation dated in the future is not yet evidence of
        # current buying intent. Do not give it full freshness weight.
        if signal.observed_at > now:
            continue
        age_days = (now - signal.observed_at).total_seconds() / 86400
        score = max(0, min(100, round(weight * round(signal.strength, 2) * 0.5 ** (age_days / half_life))))
        if score > top.get(signal.kind, 0):
            top[signal.kind] = score
    remaining = 1.0
    for score in top.values():
        remaining *= 1 - score / 100
    return round(100 * (1 - remaining)), top


_QUOTE_START = re.compile(r"(?im)^(?:on .{1,200} wrote:|am .{1,200} schrieb.{0,80}:|[-]{2,}\s*(?:original message|ursprüngliche nachricht))\s*$")
_STOP = re.compile(
    r"(?i)\b(?:unsubscribe me|please unsubscribe|bitte abmelden|bitte austragen|"
    r"nicht mehr kontaktieren|bitte nicht mehr kontaktieren|"
    r"do not contact me|don't contact me|stop emailing me|"
    r"stop contacting me|stop sending me (?:emails?|e-mails?|messages?)|"
    r"remove me from (?:the |your )?(?:list|mailing list)|"
    r"no more (?:emails?|e-mails?|marketing messages?)|"
    r"keine weiteren (?:e-mails?|mails?|nachrichten)|"
    r"ich (?:will|möchte) keine weiteren (?:e-mails?|mails?|nachrichten)|"
    r"(?:schreiben sie mir|kontaktieren sie mich) nicht mehr|"
    r"keine werbung mehr)\b"
)
_STOP_NEGATION = re.compile(
    r"(?i)\b(?:don't|do not|not|never)\s+(?:please\s+)?"
    r"(?:unsubscribe(?:\s+me)?|remove(?:\s+me)?(?:\s+from\s+(?:the\s+|your\s+)?(?:list|mailing\s+list))?|"
    r"take\s+me\s+off(?:\s+(?:the\s+)?(?:list|mailing\s+list))?|"
    r"stop\s+(?:contacting\s+me|emailing\s+me|sending\s+me\s+(?:emails?|e-mails?|messages?)))\b"
)
_PRIVACY = re.compile(r"(?i)\b(?:delete my data|right to erasure|data subject access|gdpr request|dsgvo auskunft|löschen sie meine daten|woher haben sie meine daten)\b")
_BOUNCE = re.compile(r"(?i)(?:mail delivery failed|undeliverable|unzustellbar|delivery status notification \(failure\))")
_AUTO = re.compile(r"(?i)^(?:automatic reply|out of office|abwesenheit|automatische antwort)")
_INJECTION = re.compile(r"(?i)(?:ignore (?:all |previous |your )?instructions|system prompt|developer message|\[INST\]|<\|im_start\|>|reveal (?:your |the )?(?:api keys|passwords|secrets))")


def triage_reply(body: str, *, subject: str = "", sender: str = "", headers: dict[str, str] | None = None) -> str:
    """Conservative, deterministic category precheck; never performs actions."""
    if not isinstance(body, str) or not isinstance(subject, str):
        raise TypeError("reply content must be text")
    if _BOUNCE.search(subject) or re.search(r"(?i)(?:mailer-daemon|postmaster)@", sender):
        return "BOUNCE"
    m = _QUOTE_START.search(body)
    own = body[:m.start()] if m else body
    own = "\n".join(l for l in own.splitlines() if not l.lstrip().startswith(">"))[:12000]
    if _PRIVACY.search(own):
        return "PRIVACY_REVIEW"
    automated = _AUTO.search(subject) or any(
        k.lower() == "auto-submitted" and v.lower() != "no" for k, v in (headers or {}).items()
    )
    if automated:
        return "AUTOMATED"
    normalized = own.lower().strip().strip(". !\n")
    # A negative instruction such as "don't unsubscribe me" must not
    # suppress a second, unambiguous request in the same message:
    # "Don't unsubscribe me from updates. Stop contacting me."  Strip
    # only the local negated clause rather than vetoing the entire mail.
    actionable = _STOP_NEGATION.sub("", own)
    if normalized in {"stop", "abmelden", "austragen", "unsubscribe", "opt out"} or (
        _STOP.search(actionable)
    ):
        return "OPT_OUT"
    # An injection attempt never outranks a genuine stop request:
    # opt-out is a safety-critical, non-sending state transition.
    if _INJECTION.search(own):
        return "SECURITY_REVIEW"
    if re.search(r"(?i)\b(?:anwalt|abmahnung|legal action|security questionnaire|dpa request)\b", own):
        return "HUMAN_REVIEW"
    return "NEEDS_CLASSIFICATION"
