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

### Reconcile
Assigns every canonical message to a conversation thread using a JWZ-style algorithm.

### Extraction
### Enrich
Turns canonical email bodies into clean, segmented, language-annotated text for later chunking and retrieval.

```
class EmailSegment:
    seq: int                                    # Position within the message, starting at 0
    kind: SegmentKind                           # new, quoted, forwarded, signature, or reserved disclaimer
    start_offset: int                           # Code-point offsets into EmailText.clean_text
    end_offset: int                             # Code-point offsets into EmailText.clean_text
    quote_depth: int = 0                        # Nesting depth for quoted content
    attribution_raw: str | None = None          # Raw attribution line, e.g. “On Tue … wrote:”
    quoted_author: str | None = None            # Parsed attribution, currently deferred
    quoted_at: str | None = None                # Parsed attribution, currently deferred
    language: str | None = None                 # ISO 639-1 code, or null below the length/confidence threshold
    language_confidence: float | None = None    # Detector confidence
    # Set by the (deferred) 4C coverage pass; included in ``segments_digest`` so
    # a later coverage change invalidates the chunk source digest.
    covered_by_email_id: str | None = None      # Set by the deferred 4C quote-coverage pass

class EmailText:
    clean_text: str                     # normalized text the enrich stage derived from plain or HTML body content
    clean_method: CleanMethod           # plain or html — which representation was used
    segments: tuple[EmailSegment, ...]  # Lossless tiling of clean_text into EmailSegment spans
```

### Attachments
Extracts text from non-inline attachment blobs so attachments can later become searchable chunks.

```
class AttachmentText:
    blob_sha256: str                # Content hash of the attachment blob; the identity of the extracted result
    status: AttachmentStatus        # done, empty, needs_ocr, unsupported, too_large, encrypted, failed
    text: str | None = None         # Extracted and cleaned text, when successful
    method: str | None = None       # Extractor used: pdf, docx, xlsx, pptx, or text
    page_count: int | None = None   # Page count where the extractor can determine it
    language: str | None = None     # Reserved language field; currently typically null
    error: str | None = None        # Failure/limitation reason
    truncated: bool = False         # True when output was cut at the character cap
    text_sha256: str | None = None  # SHA-256 of text; set only for status = done
```

### Chunking
Turns derived text into the retrieval unit: search.chunk rows.

The chunk stage uses a deterministic token-budget algorithm:
1. BgeM3TokenCounter counts tokens using the tokenizers library and the pinned tokenizer at backend/assets/bge-m3/tokenizer.json.
2. chunk_text builds splittable units:
- a paragraph that fits within max_tokens becomes one unit,
- an over-budget paragraph is split into sentences,
- an over-budget sentence is split at tokenizer boundaries.
3. Greedy grouping packs units into chunks up to target_tokens = 400.
4. Tail merging merges an undersized final chunk into the previous one if it fits within max_tokens.
5. Overlap adds trailing whole units from the previous chunk, up to overlap_tokens = 50, without exceeding the max.
6. Prefix budgeting happens in _chunk_source:
budget = max_tokens - prefix_tokens - 1
target = min(target_tokens, budget)
Here:
max_tokens       = 480
prefix tokens    = 42
text budget      = 480 - 42 - 1 = 437
chunk target     = min(400, 437) = 400

```
class ChunkDraft:
    id: uuid.UUID
    email_id: uuid.UUID                         # Canonical message this chunk belongs to
    attachment_id: uuid.UUID | None             # Attachment ID for attachment chunks; otherwise null
    thread_id: uuid.UUID | None                 # Conversation thread, copied for filtering
    kind: ChunkKind                             # email_body, email_quote, or attachment
    seq: int                                    # Position within that source, starting at 0
    text_for_display: str                       # Chunk text without the contextual prefix
    text_for_index: str                         # Contextual prefix + newline + chunk text
    text_sha256: str                            # SHA-256 of text_for_index; used for embedding reuse
    language: str | None                        # Dominant segment language, or attachment text language
    index_version: str                          # Chunker + prefix + tokenizer + params version
    source_account_id: uuid.UUID                # Account scope
    source_account_num: int                     # Integer account surrogate for search pushdown
    sent_at: datetime                           # Message occurred_at
    sender_handle: str                          # First from address, normalized
    recipient_handles: tuple[str, ...]          # To/Cc/Bcc addresses
    participant_handles: tuple[str, ...]        # Sorted union of all participant addresses
    direction: str                              # received, sent, self, or unknown
    has_attachment: bool                        # Message-level attachment flag
    is_trash_or_spam: bool                      # Message-level trash/spam flag
    tags: tuple[str, ...]                       # Namespaced provider tags
    meta: dict = field(default_factory=dict)    # JSONB flags such as header_only, truncated, or partial

class ChunkBuildRow:
    chunk_kind: str                             # email_body, email_quote, or attachment
    attachment_id: uuid.UUID | None             # Set only for attachment chunks
    index_version: str                          # Version that produced this build
    source_digest: str | None                   # Input digest used to decide staleness
    built_at: datetime                          # When the inputs were read
    chunk_count: int                            # Number of chunks produced for this source
    status: str                                 # done, empty, or failed
    error: str | None                           # Failure reason, if any
```

### Embedding
Turns indexed chunks into vectors for semantic retrieval.
- Only embed email_body chunks
- Embeds text_for_index, which includes the contextual prefix.
- FlagEmbedding embeds with BAAI/bge-m3.

Embeddings are persisted in chunk document at emb_bge_m3_v1.

## Indexing
2. What each index stage persists
Split
- raw.source_record: one row per message.
- payload_uri points to the content-addressed message object.
- payload is null for byte-backed email records.
- Identity: (source_account_id, resource_type, external_id, payload_sha256).
Canonicalize
- core.email_message: one canonical message per (source_account, message_id).
- core.email_message_observation: provenance back to the raw record.
- core.email_participant, core.email_attachment, core.email_tag.
- Attachment bytes are stored once by content hash.
- Message IDs are deterministic uuid5(source_account_id, message_id).
Reconcile
- core.email_thread: conversation roots.
- core.email_message.thread_id and thread_changed_at.
- Threads are reconciled account-wide and may be merged, renamed, or deleted.
Enrich
- derived.email_text: one row per message, keyed by email_id.
- derived.email_segment: lossless text spans with kinds, offsets, and language.
- Rows carry stage_version, input_sha256, and segments_digest.
Attachments
- derived.attachment_text: one row per attachment blob, keyed by blob_sha256.
- Deduplicates extraction across messages and emails.
- Terminal statuses (needs_ocr, unsupported, etc.) prevent repeated work.
Chunk
- search.chunk: the retrieval unit.
- One row per (email_id, chunk_kind, attachment_id, seq).
- Stores:
- text_for_display and prefixed text_for_index
- text_sha256
- language, account, sender, recipients, participants
- direction, date, tags, attachment/trash flags, thread
- search.chunk_build: one bookkeeping row per chunk source, used by the work finder.
- Chunk IDs are deterministic uuid5(email_id, kind, attachment_id, seq).
Embed
- Vectors are columns on search.chunk, e.g. emb_bge_m3_v1 and its companion text hash.
- search.embedding_failure: failed texts that should not be retried blindly.
- search.embedding_run: disclosure/run ledger with embedded/failed counts and model/service metadata.

5. Physical database indexes
The schema is optimized for the actual retrieval paths.
Chunk lookup and filtering
- Unique (email_id, chunk_kind, attachment_id, seq) makes chunk replacement idempotent.
- chunk_scope_time_idx on (source_account_num, sent_at) for scoped time filters.
- chunk_sender_idx, chunk_thread_idx, chunk_email_idx.
- GIN indexes on recipient_handles, participant_handles, and tags.
- Partial chunk_list_idx for listing one representative body chunk per message.
Lexical retrieval
- ParadeDB pg_search BM25 index chunk_bm25_idx over text_for_index.
- Scope and filter fields are included as fast fields where beneficial: account, time, attachment/trash flags, sender, direction, language.
- Recipient/participant/tag/thread filters may be applied as heap filters over the candidate stream.
Semantic retrieval
- HNSW index chunk_emb_bge_m3_v1_hnsw over the halfvec embedding column.
- The semantic universe only includes fresh, non-null vectors whose companion hash matches text_sha256.
- Exact scan remains available and is used when configured or when the ANN index is not appropriate.
6. Why this strategy
- Correctness: raw evidence and canonical data are never overwritten by indexing.
- Rebuildability: derived and search layers can be regenerated.
- Idempotency: repeated imports/indexing do not create duplicates.
- Performance: chunks are denormalized specifically for search, avoiding joins at query time.
- Auditability: every canonical message retains a link to its raw source.
- Account scoping: source_account_id/source_account_num are carried into chunks for fast, safe filtering.
- Evolvability: version stamping lets a parser, segmentation, chunker, or embedding model change invalidate only the affected rows.

## Online search
Two online search strategies:
- RANKED — there is a query or keywords: retrieve, fuse, rerank, assemble.
- LIST — filters only: keyset-ordered message listing, no retrieval or reranking.

### Request
SearchRequest behavior:
- Requires at least one of query, keywords, or a filter.
- No query/keywords → LIST strategy.
- Query/keywords present → RANKED strategy.
- If both query and keywords are set:
- query drives the semantic branch,
- keywords drives the lexical branch.
- sort=None becomes:
- relevance for ranked searches,
- date_desc for filter-only listings.
- limit is validated by the adapter (1..25) and further clamped to the configured result window during Prepare.
- cursor is tied to the plan fingerprint and index version; changing the query, filters, budgets, fusion, or versions invalidates it.

SearchRequestFilters semantics:
- Lists are OR within a field.
- Different fields are AND.
- An empty frozenset means “no constraint”.
- Person references are not resolved in the filter object; "me", UUIDs, and addresses are expanded during Prepare.
- thread_of takes a message ID, never a thread ID, because thread IDs are unstable across reconciliation.
- date_from/date_before are calendar dates resolved using the effective timezone into UTC boundaries.
- Tags are canonicalized during Prepare; a tag cannot appear in both tags and exclude_tags.
- source_accounts intersects with the authenticated scope; it can never expand access.
- include_trash_spam=False excludes trash/spam chunks by default.


```
class SearchRequestFilters:
    sender: frozenset[str]                  # Sender references: address, "me", or entity UUID
    recipient: frozenset[str]               # To/Cc/Bcc references
    participant: frozenset[str]             # Any-role participant references
    direction: Direction | None = None      # received, sent, self, or unknown
    date_from: date | None = None           # Inclusive local calendar date
    date_before: date | None = None         # Exclusive local calendar date
    tags: frozenset[str]                    # Tags that must match
    exclude_tags: frozenset[str]            # Tags to exclude
    has_attachment: bool | None = None      # Require or exclude attachments
    thread_of: uuid.UUID | None = None      # Message UUID; Prepare resolves it to that message’s current thread
    language: frozenset[str]                # ISO language codes
    source_accounts: frozenset[uuid.UUID]   # Can only narrow the authorized account scope
    include_trash_spam: bool = False        # Defaults to False

class SearchRequest:
    query: str | None               # Natural-language query; used for semantic embedding and as lexical fallback
    keywords: str | None            # Keyword text for lexical search; overrides query for the lexical branch
    filters: SearchRequestFilters   # Raw, unresolved filters
    sort: SortOrder | None          # relevance, date_desc, or date_asc; None lets Prepare choose
    group_by: GroupBy               # message or thread
    view: ResultView                # metadata or snippet
    limit: int                      # Requested result count
    cursor: str | None              # Opaque signed pagination token
    mode: SearchMode                # hybrid, lexical, or semantic
```



### Prepare
SearchService.prepare turns an authenticated request into an immutable SearchPlan.
#### 1. Authenticate and scope
- The account comes from the auth context, never from tool arguments.
- The requested source accounts can only narrow the authorized scope.

#### 2. Validate
- Requires at least one of query, keywords, or a filter.
- Validates dates, list sizes, and mode/query combinations.

#### 3. Decode cursor
- Cursors are signed and bound to the account, index version, and plan fingerprint.

#### 4. Normalize query text
- query → normalized semantic text.
- keywords → structured terms and quoted phrases.
- Text is capped at max_query_chars.

#### 5. Choose strategy and mode
- Query present → RANKED.
- No query → LIST.
- Ranked mode can be lexical, semantic, or hybrid.
- If semantic is unavailable but lexical is possible, degrade to lexical with a warning.

#### 6. Resolve in parallel
- Thread filter (thread_of → current thread ID)
- Known tags/languages and data coverage
- Entity/handle references (me, person UUID, address)
- Query embedding, when semantic/hybrid mode needs it

#### 7. Build filters
- Senders, recipients, participants
- Direction, tags, excluded tags, languages
- Attachment flag, thread, date bounds, trash/spam inclusion
- Person lookups expand to concrete handle sets.

#### 8. Short-circuit early
- Empty scope
- No matching handles
- Thread not found
- Date range outside imported data

#### 9. Build the plan
- Contains scope, filters, query, strategy, mode, presentation, budgets, versions, fusion config, and warnings.
- Gets a stable fingerprint used by cursors and audit.
- The plan is frozen; later stages do not re-read the raw request.

```
class RequestContext:
    request_id: uuid.UUID   # Unique ID for this search call
    audit_id: uuid.UUID     # Audit record opened for the call
    client_id: str          # Caller/client identity

class Scope:
    account_id: uuid.UUID                       # Authenticated Rosalind account
    source_account_ids: frozenset[uuid.UUID]    # Authorized provider accounts

class ResolvedFilters:
    senders: frozenset[str]         # Normalized sender addresses
    recipients: frozenset[str]      # To/Cc/Bcc addresses
    participants: frozenset[str]    # Any-role participant addresses
    direction: Direction | None     # received, sent, self, unknown
    tags_any: frozenset[str]        # Tags that must match
    tags_exclude: frozenset[str]    # Tags to exclude
    has_attachment: bool | None     # Attachment requirement
    thread_of: uuid.UUID | None     # Message ID the caller asked about
    thread_id: uuid.UUID | None     # That message’s current resolved thread
    languages: frozenset[str]       # ISO language codes
    sent_from: datetime | None      # Inclusive UTC lower bound
    sent_before: datetime | None    # Exclusive UTC upper bound
    timezone_used: str              # IANA timezone used to resolve local dates
    include_trash_spam: bool        # Whether trash/spam chunks are included

class ResolvedEntity:
    requested: str                  # What the caller wrote: "me", entity UUID, or address
    entity_id: uuid.UUID | None     # Resolved canonical person, if any
    handles: frozenset[str]         # Normalized addresses this entity expands to

class LexicalQuery:
    terms: tuple[str, ...]      # Bare search terms
    phrases: tuple[str, ...]    # Quoted phrases

class QueryVector:
    values: tuple[float, ...]   # Raw embedding values; excluded from repr
    model: str                  # Embedding model ID
    model_version: str          # Model version/revision
    digest: str                 # SHA-256 hex of the values

class PreparedQuery:
    semantic_text: str | None       # Normalized natural-language query
    lexical: LexicalQuery | None    # Keyword terms/phrases
    vector: QueryVector | None      # Embedded query

class Presentation:
    sort: SortOrder     # relevance, date_desc, date_asc
    group_by: GroupBy   # message or thread
    view: ResultView    # metadata or snippet
    limit: int          # Requested result count

class Budgets:
    lexical_k: int      # Lexical candidates to retrieve
    semantic_k: int     # Semantic candidates to retrieve
    fused_k: int        # Candidates kept after fusion
    rerank_k: int       # Candidates sent to the reranker
    window_k: int       # Final ranked window available across pages

class IndexVersions:
    index_version: str              # Chunker/prefix/tokenizer/params version
    embedding_model: str | None     # Embedding model ID, if semantic search is available
    embedding_version: str | None   # Model revision/name
    reranker: str | None            # Reranker version; None disables reranking

class FusionConfig:
    strategy: FusionStrategy        # rrf (default) or convex
    rrf_k: int                      # RRF constant, default 60
    lexical_weight: float           # Weight for lexical ranks/scores, default 1
    semantic_weight: float          # Weight for semantic ranks/scores, default 1
    convex_alpha: float | None      # Semantic weight for convex fusion in [0, 1]; CONVEX only
    max_chunks_per_item: int        # Per-message cap before fused_k truncation, default 2

class ListPosition:
    occurred_at: datetime       # Message timestamp
    email_id: uuid.UUID         # Canonical message ID

class Cursor:
    fingerprint: str                        # Binds the cursor to one plan
    window_offset: int | None               # Ranked pagination offset inside the assembled window
    list_position: ListPosition | None      # Keyset position for list searches

class PlanWarning:
    code: WarningCode           # Machine-readable warning code: unknown_tag, unseen_handle, unknown_language, mode_degraded, query_truncated, limit_clamped, rerank_skipped or retrieval_degraded
    message: str                # Human-readable explanation
    field_name: str | None      # Field that caused it
    suggestion: str | None      # Optional remediation

class PlanHints:
    estimated_matching_chunks: int | None   # Estimated filter selectivity

class PrepareTimings:
    validate_ms: float          # Request validation
    resolve_ms: float           # Entity/thread/metadata resolution
    embed_ms: float | None      # Query embedding time, if performed
    total_ms: float             # Total Prepare time

class SearchPlan:
    context: RequestContext                         # Request ID, audit ID, client ID
    scope: Scope                                    # Authorized account and source accounts
    filters: ResolvedFilters                        # Fully normalized filters
    resolved_entities: tuple[ResolvedEntity, ...]   # How person references were expanded
    query: PreparedQuery                            # Semantic text, lexical terms/phrases, query vector
    strategy: SearchStrategy                        # ranked or list
    mode_requested: SearchMode                      # What the caller asked for - hybrid, lexical or semantic
    mode_effective: SearchMode                      # What will actually run
    presentation: Presentation                      # Sort, grouping, view, result limit
    budgets: Budgets                                # Candidate counts per stage
    versions: IndexVersions                         # Index, embedding, and reranker versions
    fusion: FusionConfig = FusionConfig()           # RRF/convex settings and per-message cap
    cursor: Cursor | None = None                    # Decoded pagination position
    warnings: tuple[PlanWarning, ...] = ()          # Non-fatal degradations or corrections
    hints: PlanHints = PlanHints()                  # Optional future optimization hints
    timings: PrepareTimings | None = None           # Prepare-stage timing breakdown
```

### Step 2 — Retrieve
Retrieval runs the branches required by the plan, in parallel when hybrid.
#### 2.1 Lexical retrieval
Finds chunks by keyword relevance using ParadeDB BM25 over search.chunk.text_for_index

- BM25 over search.chunk.text_for_index using ParadeDB pg_search.
- Returns up to lexical_k chunks.
- Carries each hit’s 1-based rank and unmodified BM25 score.
- Scope/date/flag filters are pushed into the BM25 index where possible.
- Recipient, participant, tag, and thread filters may be applied as heap filters over the candidate stream.

Input
It uses plan.query.lexical, a LexicalQuery containing:
- terms — bare keyword terms
- phrases — quoted phrases
It also uses the plan’s:
- mandatory Scope
- ResolvedFilters
- budgets.lexical_k

Query rendering
ParadeDbLexicalQueryRenderer converts the structured query into pg_search syntax:
- operator characters in terms are escaped so values like C++, 2026-0412, and (quote are literal;
- phrases are quoted and escaped;
- terms and phrases are space-joined.
Examples:
LexicalQuery(terms=("roof", "quote"))
→ roof quote

LexicalQuery(terms=("invoice",), phrases=("12 Elm St",))
→ invoice "12 Elm St"

LexicalQuery(terms=("C++", "(quote", "2026-0412"))
→ C\+\+ \(quote 2026\-0412
With the default pg_search parser, the space-joined parts are treated as a disjunction, so a chunk matching any term/phrase is a candidate.

SQL query shape
The adapter runs:
SELECT chunk.id,
       chunk.email_id,
       paradedb.score(id) AS score
FROM search.chunk
WHERE text_for_index @@@ :q
  AND chunk.source_account_num IN (...)
  AND <resolved filters...>
ORDER BY paradedb.score(id) DESC, chunk.id ASC
LIMIT :lexical_k_plus_one
Key points:
- @@@ is the ParadeDB BM25 match operator.
- paradedb.score(id) is the BM25 score.
- Scope is mandatory and resolved from source-account UUIDs to source_account_num integers.
- Ordering is deterministic: score descending, then chunk ID ascending.
- It fetches lexical_k + 1 rows to distinguish “exactly k matches” from “there may be more”.
- The application receives up to lexical_k LexicalHits with 1-based ranks and unmodified BM25 scores.

Filters
The lexical retriever shares its filter predicates with semantic retrieval through filter_conditions in backend/src/rosalind/adapters/outbound/search/filters.py.
Applied filters include:
- sender → sender_handle IN (...)
- recipients → recipient_handles && ...
- participants → participant_handles && ...
- tags → tags && ...
- excluded tags → NOT (tags && ...)
- direction
- language
- attachment flag
- thread ID
- sent_at range
- trash/spam exclusion unless include_trash_spam
Lists are OR within a field; different fields are AND.

```
class LexicalHit:
    chunk_id: uuid.UUID                 # Identity of the matched search.chunk row
    email_id: uuid.UUID                 # Canonical message the chunk belongs to
    rank: int                           # 1-based position in deterministic score order (score DESC, chunk_id ASC)
    score: float                        # Raw BM25 score from ParadeDB, unmodified

class LexicalResult:
    hits: tuple[LexicalHit, ...]        # Up to lexical_k ranked chunks
    exhausted: bool                     # Fewer than lexical_k chunks matched in total
    filter_path: FilterPath             # How filters were applied - pushdown or overfetch
    warnings: tuple[str, ...]           # Optional retrieval warnings
    elapsed_ms: float                   # Time spent in lexical retrieval
```

filter_path
- "pushdown" — all active filters are evaluated inside the BM25 index scan.
- "overfetch" — at least one filter is applied as a heap filter over the BM25 candidate stream: recipients, participants, tags, excluded tags, or thread ID.
This is informational; both paths return correct results.

#### 2.2 Semantic retrieval
Finds chunks whose embedding is closest to the embedded query using pgvector over search.chunk.emb_bge_m3_v1.

Uses BAAI/bge-m3

- Embeds the normalized query and searches search.chunk.emb_bge_m3_v1.
- Uses pgvector exact search or HNSW ANN.
- Only considers fresh, non-null embeddings whose companion hash matches text_sha256.
- Returns up to semantic_k chunks with cosine distance and rank.
- Reports whether the result is complete and whether an ANN scan limit was hit.
A hybrid search runs both branches concurrently. If semantic retrieval fails, the pipeline degrades to lexical with a warning instead of failing the request.

Input
It uses:
- plan.query.vector — the embedded query
- plan.versions.embedding_model / embedding_version
- mandatory plan.scope
- plan.filters
- plan.budgets.semantic_k
The embedding space is resolved by model/version, e.g. bge_m3_v1:
- 1024 dimensions
- halfvec
- cosine distance
The query vector is validated before retrieval:
- dimension matches the space
- all values are finite
- the vector is not all zeros, because cosine distance is undefined

Candidate universe
Semantic retrieval uses the same scope and filters as lexical retrieval, plus two embedding-specific conditions:
source_account_num IN (...)
AND <resolved filters>
AND emb_bge_m3_v1 IS NOT NULL
AND emb_bge_m3_v1_text_sha256 = text_sha256
This means:
- the query is confined to authorized source accounts;
- filters are identical across lexical and semantic branches;
- stale vectors are never returned — a chunk whose text changed must be re-embedded first.
Semantic candidates are therefore a strict subset of lexical candidates.

Two retrieval paths
Exact
The exact path:
1. Materializes the filtered candidate rows in a MATERIALIZED CTE.
2. Computes exact cosine distance for every candidate.
3. Sorts by distance ASC, chunk_id ASC.
4. Takes the top semantic_k.
This path is always:
complete = True
scan_limit_hit = False
The materialization prevents the planner from turning the outer distance ordering back into an approximate HNSW scan.
ANN iterative
The ANN path uses the HNSW index over emb_bge_m3_v1 and:
1. Applies per-transaction settings:
- hnsw.iterative_scan
- hnsw.ef_search, at least semantic_k
- optional hnsw.max_scan_tuples
- optional hnsw.scan_mem_multiplier
- optional statement_timeout
2. Orders by cosine distance ascending, with chunk_id as a deterministic tie-break.
3. Takes the top semantic_k.
The query vector is bound as HALFVEC, which is required for the planner to use the halfvec_cosine_ops operator and HNSW index.
Path selection
SemanticRetrievalConfig.exact_threshold decides:
- None → always ANN.
- A hint is available → exact if estimated_matching_chunks <= threshold, else ANN.
- Otherwise → run a bounded count:
- if matching chunks <= threshold → exact
- else → ANN
This avoids an expensive exact scan on large result sets while using exact search when the filtered universe is small.

```
class SemanticHit:
    chunk_id: uuid.UUID     # Identity of the matched search.chunk row
    email_id: uuid.UUID     # Canonical message the chunk belongs to
    rank: int               # 1-based position in deterministic distance order (distance ASC, chunk_id ASC)
    distance: float         # Raw cosine distance from pgvector, unmodified

class SemanticResult:
    hits: tuple[SemanticHit, ...]       # Up to semantic_k ranked chunks
    complete: bool                      # Every matching chunk was considered
    filter_path: SemanticFilterPath     # How retrieval was executed - exact or ann_iterative
    scan_limit_hit: bool                # ANN scan stopped early and may have missed matches
    warnings: tuple[str, ...]           # Optional retrieval warnings
    elapsed_ms: float                   # Time spent in semantic retrieval
```

filter_path
- "exact" — materialized filtered rows, then exact cosine distance sort.
- "ann_iterative" — HNSW approximate scan with iterative scanning.

### Step 3 — Fusion
Combines the lexical and semantic candidate lists into one ranked candidate set for the reranker and final assembly.

fuse merges the lexical and semantic lists by chunk_id.
- Default: Reciprocal Rank Fusion (RRF):
score = lexical_weight / (rrf_k + lexical_rank)
      + semantic_weight / (rrf_k + semantic_rank)
- Alternative: convex combination of normalized BM25 and cosine similarity.
- Preserves each candidate’s lexical and semantic ranks.
- Sorts deterministically.
- Applies the per-message chunk cap.
- Truncates to fused_k.
The per-message cap prevents one long thread or message from consuming the whole candidate window.

Input
- LexicalResult | None
- SemanticResult | None
- SearchPlan.fusion configuration
At least one retrieval branch must be present.

1. Merge by chunk
Lexical hits and semantic hits are merged into a dictionary keyed by chunk_id.
Each merged candidate keeps:
- chunk_id
- email_id
- lexical_rank, lexical_score
- semantic_rank, semantic_distance
If the same chunk appears in both branches, both sets of provenance are retained. If the two branches disagree about the chunk’s email_id, fusion raises an error because that would indicate inconsistent index data.
A chunk only found by one branch is still a valid candidate.

2. Score
RRF — default
Reciprocal Rank Fusion:
score = lexical_weight / (rrf_k + lexical_rank)
      + semantic_weight / (rrf_k + semantic_rank)
Details:
- Uses ranks only, so BM25 and cosine-distance scales do not need normalization.
- A missing branch contributes 0.
- Default rrf_k = 60.
- Default weights are 1.0 for both branches.
Example:
lexical_rank = 2
semantic_rank = 5
rrf_k = 60

score = 1 / (60 + 2) + 1 / (60 + 5)
      = 0.01613 + 0.01538
      = 0.03151
A chunk found by both branches generally outranks a chunk found by only one, but a very high rank in one branch can still beat a weak result in both.

Convex — optional
Convex fusion combines normalized scores:
lexical_norm  = min-max normalized BM25 score
semantic_sim  = 1 - cosine_distance
score         = alpha * semantic_sim
              + (1 - alpha) * lexical_norm
Details:
- BM25 is min-max normalized across the current lexical candidates.
- Cosine similarity is used directly.
- A missing branch contributes 0 on that side.
- convex_alpha weights the semantic side and must be in [0, 1].
- If lexical scores have no spread, normalized lexical value is 0.

3. Sort deterministically
Candidates are ordered by:
1. fused_score descending
2. number of branches that found the candidate, descending
3. best original rank across branches, ascending
4. chunk_id, ascending
So if two candidates have equal fused scores, one found by both branches wins over one found by only one branch.
4. Apply the per-message cap
After sorting, fusion applies:
max_chunks_per_item
Default: 2.
It keeps at most that many chunks per canonical message. This prevents one long email or thread from consuming the entire candidate window.
The cap runs after scoring and sorting but before truncation, so diversity is imposed on the best-scored candidates.
The number of dropped chunks is reported as dropped_by_item_cap.
5. Truncate
The remaining candidates are truncated to plan.budgets.fused_k.
Fusion does not produce the final display order; it produces the candidate set the reranker will see.
One-branch behavior
If only lexical results exist:
- semantic provenance is absent,
- the lexical list is still scored, sorted, capped, and truncated,
- fusion effectively passes the branch through.
Same for semantic-only or a degraded hybrid search where the semantic branch failed.

```
class FusedCandidate:
    chunk_id: uuid.UUID                         # Chunk identity
    email_id: uuid.UUID                         # Canonical message
    fused_score: float                          # RRF or convex score
    fused_rank: int                             # 1-based final position after cap/truncation
    lexical_rank: int | None                    # Original lexical rank, or null
    lexical_score: float | None                 # Original BM25 score, or null
    semantic_rank: int | None                   # Original semantic rank, or null
    semantic_distance: float | None             # Original cosine distance, or null

class FusedCandidates:
    candidates: tuple[FusedCandidate, ...]      # Up to fused_k FusedCandidate values
    lexical_used: bool                          # Whether a lexical branch participated
    semantic_used: bool                         # Whether a semantic branch participated
    dropped_by_item_cap: int                    # Candidates dropped by the per-message cap
```

### Step 4 — Rerank
Takes the fused candidate set and reorders the strongest candidates with a cross-encoder that scores each (query, passage) pair directly.

Uses BAAI/bge-reranker-v2-m3

If reranking is enabled:
1. Take the top rerank_k fused candidates.
2. Fetch chunk text (text_for_index by default, or display text).
3. Truncate passages to the model’s input budget.
4. Score each (query, passage) pair with a cross-encoder.
5. Reorder by reranker score.
The reranker only reorders candidates fusion already admitted; it never retrieves new chunks.
Failure is all-or-nothing:
- If the reranker is unavailable or times out, keep the fused order.
- Add a rerank_skipped warning.
- Never mix reranked and non-reranked results.

Inputs
- FusedCandidates from step 3
- SearchPlan, including:
- budgets.rerank_k
- budgets.window_k
- versions.reranker
- rerank_query
- ChunkTextPort — fetches chunk text
- RerankerPort — the cross-encoder backend
- TokenCounter — passage truncation
- RerankConfig:
- max_input_tokens
- text_mode (index or display)
- max_batch_size
- deadline_ms
1. Select candidates
Take the top plan.budgets.rerank_k fused candidates.
The plan invariant ensures:
window_k <= rerank_k
so the final result window comes from reranked candidates.
2. Fetch text
Fetch text for those chunk IDs using RerankTextMode:
- index — text_for_index, which includes the contextual prefix; default.
- display — text_for_display.
If a chunk disappeared between retrieval and rerank, it is dropped and counted in dropped_missing.
3. Truncate passages
The cross-encoder input budget is:
passage_budget =
    max_input_tokens
    - query_tokens
    - 3 fixed special tokens
The three extra tokens account for the cross-encoder’s [CLS] and two [SEP] tokens.
Each passage is truncated with the tokenizer to fit that budget. The number truncated is recorded in truncated_passages.
If the query leaves no passage budget, reranking raises RerankError.
4. Score with the cross-encoder
The query sent to the reranker is:
- plan.query.semantic_text when available, otherwise
- lexical terms and phrases joined.
The reranker receives the query and all passages in batches bounded by max_batch_size.
Scoring is wrapped in an overall asyncio.timeout(config.deadline_ms / 1000).
5. Order by reranker score
Candidates are sorted by:
1. reranker score descending,
2. fused rank ascending,
3. chunk ID ascending.
The reranker’s raw score is preserved; higher is better.
Failure policy
Reranking is all-or-nothing:
- If the backend fails, times out, or is unavailable:
- keep the fused order,
- return applied=False,
- add a rerank_skipped warning.
- Never mix reranked and non-reranked candidates.
Invalid input/config or a malformed reranker response raises RerankError.

```
class RerankedHit:
    chunk_id: uuid.UUID                     # Chunk identity
    rerank_rank: int                        # 1-based final position after reranking
    rerank_score: float | None              # Raw cross-encoder score; None when reranking was not applied
    fused_rank: int                         # Original 1-based rank from fusion
    fused_score: float                      # Original fusion score

class RerankStats:
    candidates_in: int                      # Candidates sent into rerank, before missing chunks are dropped
    scored: int                             # Candidates actually scored
    dropped_missing: int                    # Candidates whose chunk text vanished between retrieval and rerank
    truncated_passages: int                 # Passages truncated to fit the model input budget
    batches: int                            # Estimated number of backend batches: ceil(scored / max_batch_size)
    fetch_ms: float                         # Time spent fetching chunk text
    score_ms: float                         # Time spent in the reranker backend

class RerankResult:
    ranked: tuple[RerankedHit, ...]         # Final ordered candidates, limited to window_k
    applied: bool                           # Whether the cross-encoder actually ran
    model: str | None                       # Reranker version from the plan; None when disabled
    warnings: tuple[PlanWarning, ...]       # Typically rerank_skipped on fallback
    stats: RerankStats                      # Rerank diagnostics
    elapsed_ms: float                       # Total rerank-stage time
```

### Step 5 — Assembly
Turns the ranked chunk window into the client-facing response.

Assembly produces the client response.
1. Take the top window_k ranked chunks.
2. Fetch presentation metadata:
- item ID, thread, subject, sender, date
- display text or metadata only
- attachment name
3. Group by message or thread:
- one result per message by default
- one per thread when group_by=thread
4. Generate deterministic snippets:
- whitespace-normalize
- trim
- truncate to snippet_max_chars
5. Attach score:
- reranker score when reranking applied
- fused score otherwise
6. Page inside the assembled window using a ranked cursor.
7. Deduplicate warnings and return citations and applied filters.

There are two paths:
- assemble_ranked — query-based search
- assemble_list — filter-only listing
Ranked assembly
1. Select the final window
Assembly takes:
window = reranked.ranked[: plan.budgets.window_k]
These are the chunks available across all pages of this rank-ordered result set.
A score lookup is built:
score_by_chunk = {hit.chunk_id: hit for hit in window}
2. Fetch presentation metadata
SearchPipeline first calls SearchResultDataPort.get_results(...) for the window’s chunk IDs.
Each SearchResultData contains:
- chunk_id
- item_id — canonical message ID
- thread_id
- chunk_kind
- occurred_at
- sender_handle
- subject
- display_text — only when view=snippet
- attachment_name
For view=metadata, display_text is not loaded.
3. Collapse to one result per message or thread
Assembly iterates the fetched metadata in ranked order and applies a grouping key.
Default grouping by message:
("item", item_id)
Grouping by thread:
("thread", thread_id)
A message without a thread is treated as its own group, never merged with other threadless messages.
Only the first chunk seen for a group becomes the representative result. Later chunks from the same message or thread are skipped.
This means:
- one result per message by default;
- one result per thread when group_by=thread;
- ranking order is preserved by the first representative chunk.
4. Build result records
For each representative result:
- choose the score:
- rerank_score when reranking applied;
- fused_score otherwise;
- generate a snippet when requested;
- set matched_in to "attachment" for attachment chunks, otherwise "body";
- attach a citation containing:
- item_id
- chunk_id
- thread_id.
5. Generate snippets
make_snippet is deterministic:
1. whitespace-normalize the display text;
2. trim it;
3. truncate to snippet_max_chars;
4. append … when truncated.
For view=metadata, the snippet is None.
6. Paginate inside the assembled window
Ranked pagination is not SQL offset pagination. It pages inside the assembled result window:
start = plan.cursor.window_offset if cursor else 0
page = assembled[start : start + plan.presentation.limit]
next_offset = start + len(page)
If more results remain, a new signed cursor is created with:
- current plan fingerprint;
- next window_offset;
- account ID;
- index version.
Grouping happens before pagination so a message/thread cannot be skipped or duplicated across page boundaries.
List assembly
Filter-only searches already retrieve one representative body chunk per message in keyset order.
assemble_list:
1. takes the first limit items;
2. generates snippets if requested;
3. sets score=None;
4. creates a keyset cursor from the last returned item:
(occurred_at, email_id)
5. returns the exact total count as total_estimate.
There is no grouping, fusion, reranking, or ranked-window pagination.

```
class SearchCitation:
    item_id: uuid.UUID                          # Canonical email message ID
    chunk_id: uuid.UUID                         # Representative chunk that matched
    thread_id: uuid.UUID | None                 # Conversation thread, if assigned

class SearchResultRecord:
    item_id: uuid.UUID                          # Canonical message ID
    thread_id: uuid.UUID | None                 # Current thread ID
    chunk_id: uuid.UUID                         # Representative chunk for this result
    subject: str | None                         # Message subject
    sender: str                                 # Normalized from address
    date: datetime                              # Message occurred_at
    snippet: str | None                         # Generated snippet, or None for metadata-only view
    matched_in: MatchedIn                       # Which kind of content matched - body or attachment
    score: float | None                         # Reranker score, fused score, or None
    citation: SearchCitation                    # Evidence pointer

class SearchResponse:
    results: tuple[SearchResultRecord, ...]     # Current page
    applied_filters: dict[str, object]          # Normalized filters and plan metadata echoed back
    total_estimate: int | None                  # Exact total for list searches; None for ranked
    next_cursor: str | None                     # Signed cursor for the next page
    warnings: tuple[PlanWarning, ...]           # Deduplicated non-fatal warnings
```

### LIST path
Filter-only search strategy, used when the request has no query and no keywords but has at least one filter.
It does not embed the query, run BM25, run vector search, fuse, or rerank.

When the request has only filters:
- No query embedding, retrieval, fusion, or reranking.
- Reads one representative body chunk per message.
- Orders by date/keyset position.
- Uses a list cursor based on (occurred_at, email_id).
- Returns an exact total count and snippets.
Cross-cutting behavior
- Budgets are configuration, not agent input: lexical_k, semantic_k, fused_k, rerank_k, window_k.
- Limit is capped at the result window and at the hard maximum of 25.
- Degradation is explicit: semantic failure produces mode_degraded or retrieval_degraded warnings.
- Cursors are plan-bound: changing query, filters, budgets, fusion, or index versions invalidates them.
- Every run is auditable: Prepare records an audit event; the pipeline records a content-free trace with stage counts, timings, warnings, and returned IDs.

When it is selected
Prepare chooses:
strategy = SearchStrategy.RANKED if query or keywords else SearchStrategy.LIST
Rules:
- sort=relevance is invalid for list searches.
- Default sort is date_desc.
- date_asc is also supported.
- The request must still have at least one filter.
Pipeline path
SearchPipeline.run detects the list strategy and calls _run_list:
listed = await self._list.list(plan)
response = assemble_list(plan, listed, codec, ...)
Steps 2.1, 2.2, 3, and 4 are skipped entirely.
Message listing query
Implementation: backend/src/rosalind/adapters/outbound/search/list_retriever.py.
It lists one row per canonical message, using the representative body chunk:
WHERE chunk_kind = 'email_body'
  AND seq = 0
This makes the dedicated partial index:
chunk_list_idx (source_account_num, sent_at, email_id)
WHERE chunk_kind = 'email_body' AND seq = 0
useful for the listing scan.
Scope and filters
It applies:
- mandatory scope through source_account_num;
- the same resolved filters as ranked search via filter_conditions;
- default trash/spam exclusion unless include_trash_spam=true.
Because search filters are denormalized onto the representative chunk, the list path can filter by sender, recipients, participants, tags, direction, language, date range, attachment flag, thread, and trash/spam.
Exact total
It separately runs:
SELECT count(*)
FROM search.chunk
WHERE <scope + filters>
So total_estimate is exact for list searches, unlike ranked search where it is None.
Ordering
Default:
ORDER BY sent_at DESC, email_id DESC
For date_asc:
ORDER BY sent_at ASC, email_id ASC
The message ID is the deterministic tie-breaker.
Keyset pagination
The list path uses keyset pagination, never OFFSET.
For descending order, the cursor condition is:
sent_at < :cursor_sent_at
OR (sent_at = :cursor_sent_at AND email_id < :cursor_email_id)
For ascending order, the comparisons reverse.
The cursor’s ListPosition contains:
(occurred_at, email_id)
The query fetches limit + 1 rows so assembly can determine whether another page exists.
Assembly
assemble_list:
1. Takes the first limit rows.
2. Generates snippets if view=snippet.
3. Sets score=None.
4. Uses the last returned item to build the next keyset cursor.
5. Returns the exact total.
There is no grouping because the query already returns one row per message.

```
class SearchResultData:
    chunk_id: uuid.UUID                     # Matched chunk
    item_id: uuid.UUID                      # Canonical email message ID
    thread_id: uuid.UUID | None             # Current conversation thread
    chunk_kind: ChunkKind                   # email_body, email_quote, or attachment
    occurred_at: datetime                   # Message timestamp
    sender_handle: str                      # Normalized from address
    subject: str | None                     # Message subject
    display_text: str | None                # Chunk text for snippets; None for metadata-only views
    attachment_name: str | None             # Attachment filename when relevant

class ListResult:
    items: tuple[SearchResultData, ...]     # Listed messages, in keyset order
    total: int                              # Exact number of matching messages
```

assemble_list then:
- takes the first limit items,
- optionally generates snippets,
- sets score = None,
- returns the exact total_estimate,
- creates the next keyset cursor from the last returned item.