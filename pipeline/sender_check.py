#!/usr/bin/env python3
"""Is a job-mail sender one the pipeline trusts to move a tracker row?

Added 2026-11-19 (DECISIONS.md D60). mark_applied.py and mark_outcome.py call
check() for any confirmation or outcome that carries a "sender", and move
nothing when it says no. Items without a sender (his Sent marks on the
dashboard, outcomes he records by hand) are not checked.

A sender is trusted when its address is:
  - on a domain listed in job_mail_terms.json -> receipt_senders (the ATS and
    scheduling domains the forwarding filters copy), or exactly an address
    listed there;
  - LinkedIn's application sender (job_mail_terms.json ->
    linkedin_application_sender), for Easy Apply notices;
  - on indeed.com, for Indeed Apply confirmations (Step 0.5 item 1);
  - on the same registered domain as the tracker row's own job URL, which is
    how a company that runs its own careers site sends a receipt.

Anything else is untrusted, however much it looks like the company
(acme-hiring.example, acme-careers.example). The fleet red team of 2026-11-17
sent a receipt from a look-alike domain, and the daily run promoted that row in
4 of 6 runs with no instruction in the mail at all. A real company that mails
from its own domain while its posting sits on an ATS lands here too; that costs
him one Sent click on the dashboard.

check(sender, row_url) returns (trusted, reason). The sender may be a bare
address or a From header ("Name <addr@host>").
"""
import json
import os
import re
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
TERMS = os.path.join(HERE, "job_mail_terms.json")
EXTRA_DOMAINS = ("indeed.com",)
# Two-label public suffixes, so a row on careers.acme.co.uk trusts acme.co.uk
# and not every sender under co.uk.
TWO_LABEL_SUFFIXES = {"co.uk", "org.uk", "ac.uk", "com.au", "net.au", "co.nz", "co.in",
                      "co.jp", "com.br", "com.mx", "com.sg", "co.za", "co.il", "com.cn"}

_terms_cache = {}


def load_terms(path=TERMS):
    if path not in _terms_cache:
        with open(path, encoding="utf-8") as f:
            _terms_cache[path] = json.load(f)
    return _terms_cache[path]


def address(sender):
    """The lower-cased address in a From header or bare address, or ''."""
    s = (sender or "").strip()
    m = re.search(r"<([^<>@\s]+@[^<>@\s]+)>", s)
    if m:
        return m.group(1).lower()
    m = re.fullmatch(r"[^<>@\s]+@[^<>@\s]+", s)
    return s.lower() if m else ""


def _on(domain, entry):
    return domain == entry or domain.endswith("." + entry)


def registered_domain(host):
    parts = [p for p in (host or "").lower().strip(".").split(".") if p]
    if len(parts) < 2:
        return ""
    n = 3 if ".".join(parts[-2:]) in TWO_LABEL_SUFFIXES and len(parts) >= 3 else 2
    return ".".join(parts[-n:])


def check(sender, row_url="", terms=None):
    addr = address(sender)
    if not addr:
        return False, "no sender address"
    domain = addr.rsplit("@", 1)[1]
    terms = terms if terms is not None else load_terms()
    for entry in terms.get("receipt_senders") or []:
        e = entry.strip().lower()
        if "@" in e:
            if addr == e:
                return True, f"listed sender {e}"
        elif _on(domain, e):
            return True, f"ATS domain {e}"
    linkedin = (terms.get("linkedin_application_sender") or "").strip().lower()
    if linkedin and addr == linkedin:
        return True, "LinkedIn application sender"
    for e in EXTRA_DOMAINS:
        if _on(domain, e):
            return True, f"{e} address"
    site = registered_domain(urlparse(row_url or "").hostname or "")
    if site and _on(domain, site):
        return True, f"the job URL's own domain {site}"
    return False, f"{domain} is not an ATS domain or the job URL's domain"
