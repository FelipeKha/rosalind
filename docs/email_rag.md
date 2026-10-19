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

### Enrich

### Extraction

### Chunking

### Embedding


## Indexing

## Online search


