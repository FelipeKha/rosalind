# Email RAG Design and Evaluation

## Offline pipeline

We start with the imported mbox file, persisted in object storage, and looks like that:
```
From alice@example.test Sat Mar 01 00:00:00 2025
Message-ID: <msg-001@example.test>
Date: Mon, 03 Mar 2025 09:00:00 +0000
From: alice@example.test
To: felipe@example.test
Subject: Project kickoff
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: quoted-printable
MIME-Version: 1.0

Hi Felipe,

Let's kick off the Atlas project on 12 March. I'll prepare the agenda and sen=
d it on Friday.

Best,
Alice

From felipe@example.test Sat Mar 01 00:00:00 2025
Message-ID: <msg-002@example.test>
Date: Mon, 03 Mar 2025 10:15:00 +0000
From: felipe@example.test
To: alice@example.test
Subject: Re: Project kickoff
In-Reply-To: <msg-001@example.test>
References: <msg-001@example.test>
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 7bit
MIME-Version: 1.0

Hi Alice,

12 March works for me. Please include a discussion of the launch timeline.

Thanks,
Felipe
```

### Split
Iterate through emails in mbox, and for each:
- Store exact message bytes in object storage at `records/<sha[:2]>/<sha>`
- Upsert raw.source_record in database:
```
class SourceRecord:
    id: uuid.UUID
    source_account_id: uuid.UUID    # FK source account id
    resource_type: str              # "gmail.message"
    external_id: str                # external message id, e.g. "<msg-001@example.test>"
    payload: dict | None            # None
    payload_sha256: str             # SHA256 hash of the email
    payload_uri: str | None = None  # records/<sha[:2]>/<sha>
```

### Canonicalize
- Resolve self from `--self-email` provided or account's email, if none found error is raised
- Load import's `raw.source_record` rows
- For each record, download row bytes from object storage using `payload_uri`
- Parse email and persist canonical email (indpempotent, using the hash), and save attachments as blob at `blobs/<sha[:2]>/<sha>`


```
class CanonicalParticipant:
    role: str               # from, to, cc, or bcc
    name: str | None        # Display name
    addr: str               # email address
    addr_normalized: str    # normalized email address
    seq: int                # position within that role

class CanonicalAttachment:
    filename: str | None        # attachment file name
    declared_mime: str | None   # MIME type declared by the message
    detected_mime: str | None   # MIME type detected from the bytes/metadata
    size: int                   # Decoded attachment size in bytes
    sha256: str                 # SHA-256 of the decoded bytes
    disposition: str            # attachment or inline
    storage_key: str            # Object-storage key, e.g. blobs/<sha[:2]>/<sha>
    part_index: int             # MIME part position within the message

class CanonicalObservation:
    source_record_id: uuid.UUID # FK to the raw.source_record row
    observed_at: datetime       # When Rosalind canonicalized/observed that raw record

class CanonicalThread:
    root_message_id: str        # The message ID used as the thread root
    provider_hint: str | None   # Provider thread identifier, if any (e.g. Gmail thread ID); informational only

class CanonicalEmail:
    id: uuid.UUID
    source_account_id: uuid.UUID                    # Owning source account
    message_id: str                                 # Normalized Message-ID, or synthetic fallback
    message_id_synthetic: bool                      # True when the message had no Message-ID
    in_reply_to: str | None                         # Normalized parent message ID
    references: tuple[str, ...]                     # Normalized References chain
    occurred_at: datetime                           # Parsed Date, else observation time
    utc_offset_minutes: int | None                  # Parsed timezone offset
    direction: str                                  # received, sent, self, or unknown
    subject: str | None                             # Decoded subject
    text_plain: str | None                          # Plain-text body
    text_html: str | None                           # HTML body
    content_sha256: str                             # Hash over the body representations
    has_attachments: bool                           # True when at least one non-inline attachment exists
    is_trash_or_spam: bool                          # Derived from Spam/Trash labels
    thread: CanonicalThread                         # Initial root_message_id + optional provider hint
    parser_version: str                             # Parser version used
    canonicalizer_version: str                      # Canonicalization rules version
    parse_warnings: tuple[ParseWarning, ...]        # Non-fatal parse issues
    observation: CanonicalObservation               # Raw-record provenance
    participants: tuple[CanonicalParticipant, ...]  # From/To/Cc/Bcc addresses
    attachments: tuple[CanonicalAttachment, ...]    # Attachment metadata
    tags: tuple[str, ...]                           # Namespaced labels, e.g. gmail:SPAM
```

### Enrich

### Extraction

### Chunking

### Embedding


## Indexing

## Online search


