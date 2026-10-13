"""Build the deterministic synthetic fixture mailbox and dataset.

Run with ``uv run python scripts/build_eval_fixture.py`` from ``backend``. The
outputs (``tests/fixtures/eval/mailbox.mbox`` and ``dataset.jsonl``) are
committed so CI can run without private data. Item ids are computed with the
app's ``message_uuid`` against the fixed fixture source account id, so gold
labels are stable across imports.
"""

from __future__ import annotations

import hashlib
import mailbox
import uuid
from email.message import EmailMessage
from pathlib import Path

from rosalind.application.eval.dataset import (
    DatasetFilters,
    GoldEvidence,
    QuestionRecord,
    write_dataset,
)
from rosalind.domain.email import message_uuid

FIXTURE_SOURCE_ACCOUNT_ID = uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")


def fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "eval"


def item_id_for(message_id: str) -> str:
    return str(message_uuid(FIXTURE_SOURCE_ACCOUNT_ID, message_id))


MAILBOX = fixture_dir() / "mailbox.mbox"
DATASET = fixture_dir() / "dataset.jsonl"

SELF = "Alex Dupont <alex.dupont@gmail.com>"

_QUOTE_TEXT = (
    "QUOTE #2026-0412\n"
    "Full roof replacement (natural slate), 12 Elm Street\n"
    "Materials $4,650.00\n"
    "Labor $3,750.00\n"
    "Total $8,400.00\n"
)


def _minimal_pdf(text: str) -> bytes:
    """A tiny single-page PDF with an extractable text stream."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n{body}\nendobj\n".encode()
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _message(
    message_id: str,
    *,
    sender: str,
    to: str,
    subject: str,
    date: str,
    body: str | None = None,
    cc: str | None = None,
    labels: str | None = None,
    in_reply_to: str | None = None,
    references: tuple[str, ...] = (),
    html: str | None = None,
    attachments: tuple[tuple[str, str, bytes], ...] = (),
) -> EmailMessage:
    message = EmailMessage()
    message["Message-ID"] = f"<{message_id}>"
    message["From"] = sender
    message["To"] = to
    if cc:
        message["Cc"] = cc
    message["Subject"] = subject
    message["Date"] = date
    if labels:
        message["X-Gmail-Labels"] = labels
    if in_reply_to:
        message["In-Reply-To"] = f"<{in_reply_to}>"
    if references:
        message["References"] = " ".join(f"<{ref}>" for ref in references)
    if html and body:
        message.set_content(body)
        message.add_alternative(html, subtype="html")
    elif html:
        message.set_content(html, subtype="html")
    elif body is not None:
        message.set_content(body)
    else:
        message.set_content("")
    for filename, mime, data in attachments:
        maintype, subtype = mime.split("/", 1)
        message.add_attachment(
            data, maintype=maintype, subtype=subtype, filename=filename
        )
    return message


def _special_messages() -> list[EmailMessage]:
    quote_pdf = _minimal_pdf(
        "QUOTE 2026-0412 Total USD 8400.00 Materials 4650.00 Labor 3750.00"
    )
    return [
        _message(
            "msg-001@example.test",
            sender="Mike Turner <mike@turnerroofing.com>",
            to=SELF,
            cc="billing@turnerroofing.com",
            subject="Re: Roof quote - 12 Elm Street",
            date="Tue, 17 Mar 2026 09:32:08 -0400",
            labels="Inbox,Important,Projects",
            in_reply_to="msg-002@example.test",
            references=("msg-002@example.test",),
            body=(
                "Hi Alex,\n\nFollowing our site visit, here is the revised quote: "
                "$8,400 including materials and labor for the full roof replacement "
                "(natural slate). We could start on Monday, April 6. I can stop by "
                "Thursday at 10am to finalize, does that work for you?\n\n"
                "Best regards,\nMike Turner\nTurner Roofing | (415) 555-0142\n\n"
                "On Tue, Mar 10, 2026 at 9:15 AM Alex Dupont "
                "<alex.dupont@gmail.com> wrote:\n> Can you confirm the price? "
                "The first quote was $9,200.\n"
            ),
            html=(
                "<p>Following our site visit, here is the revised quote: "
                "<b>$8,400</b> including materials and labor.</p>"
            ),
            attachments=(("quote-2026-0412.pdf", "application/pdf", quote_pdf),),
        ),
        _message(
            "msg-002@example.test",
            sender="Mike Turner <mike@turnerroofing.com>",
            to=SELF,
            subject="Roof quote - 12 Elm Street",
            date="Tue, 10 Mar 2026 09:15:00 -0400",
            labels="Inbox",
            body=(
                "Hi Alex,\n\nThank you for the call. My first quote for the full "
                "roof replacement at 12 Elm Street is $9,200 for natural slate. "
                "I can provide a revised number after the site visit.\n\n"
                "Mike Turner\n"
            ),
        ),
        _message(
            "msg-003@example.test",
            sender=SELF,
            to="Mike Turner <mike@turnerroofing.com>",
            subject="Re: Roof quote - 12 Elm Street",
            date="Wed, 18 Mar 2026 08:10:00 -0400",
            labels="Sent",
            in_reply_to="msg-001@example.test",
            references=("msg-002@example.test", "msg-001@example.test"),
            body=(
                "Thanks, April 6 works. Please send the paperwork and I will "
                "confirm the deposit.\n\nAlex\n"
            ),
        ),
        _message(
            "msg-004@example.test",
            sender="Northwind Billing <billing@northwind.example.test>",
            to=SELF,
            subject="Invoice INV-2048 from Northwind",
            date="Mon, 02 Mar 2026 11:00:00 +0100",
            labels="Inbox,Finance",
            body=(
                "Dear Alex,\n\nPlease find invoice INV-2048 for the consulting "
                "work performed in February. The total amount is EUR 1,275.40, "
                "due 20 March.\n\nNorthwind Billing\n"
            ),
        ),
        _message(
            "msg-005@example.test",
            sender="Northwind Billing <billing@northwind.example.test>",
            to=SELF,
            subject="Payment received for INV-2048",
            date="Thu, 19 Mar 2026 15:30:00 +0100",
            labels="Inbox,Finance",
            body=(
                "We confirm receipt of EUR 1,275.40 for invoice INV-2048. Thank you.\n"
            ),
        ),
        _message(
            "msg-006@example.test",
            sender="Claire Dubois <claire@atlas.example.test>",
            to=SELF,
            subject="Atlas project kickoff",
            date="Fri, 06 Mar 2026 10:00:00 +0100",
            labels="Inbox,Projects",
            body=(
                "Hi team,\n\nThe Atlas project kickoff is scheduled for 12 March "
                "at 10:00. Agenda to follow.\n\nClaire\n"
            ),
        ),
        _message(
            "msg-007@example.test",
            sender="Alice Martin <alice@atlas.example.test>",
            to=SELF,
            subject="Re: Atlas project kickoff",
            date="Fri, 06 Mar 2026 14:20:00 +0100",
            labels="Inbox,Projects",
            in_reply_to="msg-006@example.test",
            references=("msg-006@example.test",),
            body=(
                "I added the launch timeline to the kickoff agenda, along with "
                "the risk review.\n\nAlice\n"
            ),
        ),
        _message(
            "msg-008@example.test",
            sender=SELF,
            to="Claire Dubois <claire@atlas.example.test>",
            subject="Re: Atlas project kickoff",
            date="Sat, 07 Mar 2026 09:05:00 +0100",
            labels="Sent",
            in_reply_to="msg-007@example.test",
            body="Confirmed, see you on 12 March.\n",
        ),
        _message(
            "msg-009@example.test",
            sender="Claire Dubois <claire@atlas.example.test>",
            to=SELF,
            subject="Follow-up meeting with Claire",
            date="Mon, 16 Mar 2026 09:00:00 +0100",
            labels="Inbox,Projects",
            body=(
                "Bonjour Alex,\n\nLet's meet on 21 March at 14:00 to review the "
                "Atlas milestones.\n\nClaire\n"
            ),
        ),
        _message(
            "msg-010@example.test",
            sender=SELF,
            to="Claire Dubois <claire@atlas.example.test>",
            subject="Re: Follow-up meeting with Claire",
            date="Mon, 16 Mar 2026 09:30:00 +0100",
            labels="Sent",
            in_reply_to="msg-009@example.test",
            body="Je confirme: 21 March 14:00 works for me.\n",
        ),
        _message(
            "msg-011@example.test",
            sender="Pierre Bernard <pierre@atlas.example.test>",
            to=SELF,
            subject="Ownership for the release checklist",
            date="Tue, 10 Mar 2026 16:00:00 +0100",
            labels="Inbox,Projects",
            body=(
                "For the release checklist: I own database validation, and "
                "Alice owns the application smoke tests.\n\nPierre\n"
            ),
        ),
        _message(
            "msg-012@example.test",
            sender="Alice Martin <alice@atlas.example.test>",
            to=SELF,
            subject="Re: Ownership for the release checklist",
            date="Tue, 10 Mar 2026 17:10:00 +0100",
            labels="Inbox,Projects",
            in_reply_to="msg-011@example.test",
            body="Confirmed, I will run the application smoke tests.\n",
        ),
        _message(
            "msg-013@example.test",
            sender="Finance <finance@atlas.example.test>",
            to=SELF,
            subject="Approved travel budget for the conference",
            date="Wed, 11 Mar 2026 08:00:00 +0100",
            labels="Inbox,Finance",
            body=(
                "Your approved travel budget for the conference is 4,200 EUR, "
                "including transport and accommodation.\n"
            ),
        ),
        _message(
            "msg-014@example.test",
            sender="Platform Team <platform@atlas.example.test>",
            to=SELF,
            subject="Migration configuration change",
            date="Thu, 12 Mar 2026 12:00:00 +0100",
            labels="Inbox,Projects",
            body=(
                "Please set the configuration key migration.validation.max_retries "
                "to value 4 before the release.\n"
            ),
        ),
        _message(
            "msg-015@example.test",
            sender="Platform Team <platform@atlas.example.test>",
            to=SELF,
            subject="Deployment schedule",
            date="Fri, 13 Mar 2026 12:00:00 +0100",
            labels="Inbox,Projects",
            html="<html><body><p>The deployment date is 25 March.</p></body></html>",
        ),
        _message(
            "msg-016@example.test",
            sender="Alice Martin <alice@atlas.example.test>",
            to=SELF,
            subject="Fwd: Vendor contract",
            date="Sat, 14 Mar 2026 10:00:00 +0100",
            labels="Inbox",
            body=(
                "FYI, forwarding the vendor contract below.\n\n"
                "---------- Forwarded message ----------\n"
                "From: Legal <legal@vendor.example.test>\n"
                "Subject: Vendor contract\n\n"
                "The contract is valid for twelve months.\n"
            ),
        ),
        _message(
            "msg-017@example.test",
            sender="Claire Dubois <claire@atlas.example.test>",
            to=SELF,
            subject="Meeting notes and action items",
            date="Sun, 15 Mar 2026 18:00:00 +0100",
            labels="Inbox,Projects",
            body=(
                "Here are the meeting notes from today.\n\n"
                "Best regards,\nClaire Dubois\nAtlas Program Office\n"
                "This message and any attachments are confidential and intended "
                "only for the addressee. If you are not the intended recipient, "
                "please delete it.\n"
            ),
        ),
        _message(
            "msg-018@example.test",
            sender="Hotels Lyon <bookings@hotels-lyon.example.test>",
            to=SELF,
            subject="Your hotel reservation in Lyon",
            date="Mon, 16 Mar 2026 20:00:00 +0100",
            labels="Trash",
            body=(
                "Your hotel reservation in Lyon is confirmed for 21 March, "
                "check-in at 15:00, total 210 EUR.\n"
            ),
        ),
        _message(
            "msg-019@example.test",
            sender="Mike Turner <mike@turnerroofing.com>",
            to=SELF,
            subject="Signed quote attached",
            date="Thu, 19 Mar 2026 09:00:00 -0400",
            labels="Inbox,Projects",
            body="Alex, the signed quote is attached for your records.\n",
            attachments=(("quote-2026-0412.pdf", "application/pdf", quote_pdf),),
        ),
    ]


def _filler_messages() -> list[EmailMessage]:
    topics = [
        "quarterly planning notes",
        "the design review",
        "the sprint retrospective",
        "the customer feedback summary",
        "the infrastructure migration",
        "the security audit findings",
        "the onboarding checklist",
        "the marketing draft",
        "the data quality report",
        "the vendor renewal",
    ]
    senders = [
        "news@digest.example.test",
        "orders@shop.example.test",
        "team@atlas.example.test",
        "friends@example.test",
        "notifications@service.example.test",
    ]
    messages: list[EmailMessage] = []
    for index in range(20, 66):
        topic = topics[index % len(topics)]
        sender = senders[index % len(senders)]
        day = (index % 27) + 1
        message = _message(
            f"msg-{index:03d}@example.test",
            sender=f"Sender {index} <{sender}>",
            to=SELF,
            subject=f"Update {index}: {topic}",
            date=f"Mon, {day:02d} Mar 2026 10:{index % 60:02d}:00 +0000",
            labels="Inbox",
            body=(
                f"Hi Alex,\n\nThis is update number {index} about {topic}. "
                f"Please review when you have a moment.\n\nThanks,\nSender {index}\n"
            ),
        )
        messages.append(message)
    return messages


def _build_dataset(quote_sha: str) -> list[QuestionRecord]:
    def gold(message_id: str, evidence: str | None = None) -> list[GoldEvidence]:
        return [GoldEvidence(item_id=item_id_for(message_id), evidence=evidence)]

    def question(
        qid: str,
        qtype: str,
        *,
        query: str | None = None,
        keywords: str | None = None,
        filters: DatasetFilters | None = None,
        message_id: str | None = None,
        evidence: str | None = None,
        answer: str | None = None,
        answerable: bool = True,
        split: str = "dev",
    ) -> QuestionRecord:
        return QuestionRecord(
            id=qid,
            type=qtype,  # type: ignore[arg-type]
            query=query,
            keywords=keywords,
            filters=filters or DatasetFilters(),
            gold=gold(message_id, evidence) if message_id else [],
            answer=answer,
            answerable=answerable,
            split=split,  # type: ignore[arg-type]
            status="reviewed",
        )

    return [
        question(
            "q_001",
            "amount_lookup",
            query="how much did the roofer finally quote?",
            message_id="msg-001@example.test",
            answer="$8,400",
        ),
        question(
            "q_002",
            "exact_token",
            query="what is the invoice number?",
            keywords="INV-2048",
            message_id="msg-004@example.test",
            answer="INV-2048",
        ),
        question(
            "q_003",
            "amount_lookup",
            query="how much was the invoice and when is it due?",
            message_id="msg-004@example.test",
            answer="EUR 1,275.40 due 20 March",
        ),
        question(
            "q_004",
            "thread",
            query="when is the follow-up meeting with Claire?",
            message_id="msg-009@example.test",
            answer="21 March 14:00",
        ),
        question(
            "q_005",
            "factual",
            query="when is the Atlas project kickoff?",
            message_id="msg-006@example.test",
            answer="12 March",
        ),
        question(
            "q_006",
            "factual",
            query="what did Alice add to the kickoff agenda?",
            message_id="msg-007@example.test",
            answer="launch timeline",
        ),
        question(
            "q_007",
            "filter_heavy",
            query="what is the approved travel budget?",
            filters=DatasetFilters(tags=["gmail:Finance"]),
            message_id="msg-013@example.test",
            answer="4,200",
        ),
        question(
            "q_008",
            "exact_token",
            query="what value should migration.validation.max_retries be set to?",
            keywords="migration.validation.max_retries",
            message_id="msg-014@example.test",
            answer="4",
        ),
        question(
            "q_009",
            "factual",
            query="what is the deployment date?",
            message_id="msg-015@example.test",
            answer="25 March",
            split="test",
        ),
        question(
            "q_010",
            "attachment_only",
            query="what is the total on the roofing quote attachment?",
            message_id="msg-001@example.test",
            evidence=f"attachment:{quote_sha}",
            answer="$8,400.00",
        ),
        question(
            "q_011",
            "multi_hop",
            query="who owns database validation and the application smoke tests?",
            message_id="msg-011@example.test",
            answer="Pierre owns database validation; Alice owns smoke tests",
        ),
        question(
            "q_012",
            "unanswerable",
            query="what is the invoice number for the Atlas project?",
            answerable=False,
            split="test",
        ),
        question(
            "q_013",
            "aggregation",
            query="how many emails discuss the Atlas project?",
            message_id="msg-006@example.test",
            answer="several",
        ),
        question(
            "q_014",
            "filter_heavy",
            query="roof quote",
            filters=DatasetFilters(sender=["mike@turnerroofing.com"]),
            message_id="msg-001@example.test",
            answer="$8,400",
        ),
    ]


def main() -> None:
    quote_sha = hashlib.sha256(
        _minimal_pdf(
            "QUOTE 2026-0412 Total USD 8400.00 Materials 4650.00 Labor 3750.00"
        )
    ).hexdigest()

    messages = _special_messages() + _filler_messages()

    MAILBOX.parent.mkdir(parents=True, exist_ok=True)
    if MAILBOX.exists():
        MAILBOX.unlink()
    box = mailbox.mbox(str(MAILBOX))
    try:
        for message in messages:
            box.add(message)
        box.flush()
    finally:
        box.close()

    write_dataset(DATASET, _build_dataset(quote_sha))

    print(f"wrote {len(messages)} messages to {MAILBOX}")
    print(f"wrote dataset to {DATASET}")
    print(f"source_account_id={FIXTURE_SOURCE_ACCOUNT_ID}")
    print(f"quote_attachment_sha256={quote_sha}")


if __name__ == "__main__":
    main()
