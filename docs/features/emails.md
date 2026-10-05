# Emails ingestion and management

Rosalind mission statement:
- Own my data: my personal data should be centralized in a data warehouse over which I have total control - my name, address and phone number live in my data warehouse
- Know who has my data: some of my personal data may live in service providers servers. This is fine, but I should be able to know at anytime who has what - e-commerce x, healthcare provider y, social network z have my name, address and phone number
- Control who is authorized to access and hold my data: I can decide to give access to some of my data to a third party in exchange of a service, and decide if the third party can keep my data or should delete it - I buy a pair of shoes from e-commerce x, I give it my name, address and phone number, once I get the shoes, I request e-commerce x delete my data from its servers
- Continue getting services from third parties: own my data does not mean I can't still benefit from sharing it in exchange for a service

Here we focus on emails, and how we can exploit the personal data they contain. 
In scope:
- Ingest emails from multiple emails providers (Google, Apple, etc)
- Being able to query the data to access the data contained in the emails with an AI agent
Out of scope:
- Built a new emails server


Archive / API payload     original zip or API response, stored untouched, content-addressed
        ▼
Raw records               one per underlying record (a message, a contact, a VEVENT)
        ▼
Items                     small common envelope, typed by kind
        ▼
Entities                  people, orgs, places, resolved across sources
        ▼
Facts                     attributes about entities (address, email...), with provenance
        ▼
Indexes                   FTS + embeddings, derived and rebuildable




| Startegy |	Description |	Tools | Overview | References
| :--- | :--- | :---| :---| :---|
| General-purpose search engine | A filterable lexical index and a stable filter vocabulary: people, dates, kind, tags, direction, attachments, conversation |	PostgreSQL Full Text Search (FTS) |  | [PostgreSQL doc - Full Text Search](https://www.postgresql.org/docs/current/textsearch.html) |
|  |  |	Generalized Inverted Index (GIN) |  | [PostgreSQL doc - GIN Indexes](https://www.postgresql.org/docs/current/gin.html) |
|  |  |	Text Search Vector (tsvector) |  | [PostgreSQL doc - Text Search Types](https://www.postgresql.org/docs/current/datatype-textsearch.html) |
|  |  |	Trigram Matching (pg_trgm) |  | [PostgreSQL doc - pg_trgm — support for similarity of text using trigram matching](https://www.postgresql.org/docs/current/pgtrgm.html) |
|  |  |	BM25 ranking (for Best Matching) |  | [Elastic - L'algorithme BM25](https://www.elastic.co/fr/blog/practical-bm25-part-2-the-bm25-algorithm-and-its-variables) |
|  |  |	pg_search (ParadeDB's Postgres extension) |  | [ParadeDB - pg_search: Elastic-Quality Full Text Search Inside Postgres](https://www.paradedb.com/blog/introducing-search) |
|  |  |	Meilisearch | Platform to build, scale, and unify search and AI retrieval | [Meilisearch website](https://www.meilisearch.com/) |
|  |  |	Typesense |  Cutting-edge, in-memory search engine for mere mortals. Knowledge of rocket science optional  | [Typesense website](https://typesense.org/) |
|  |  |	OpenSearch |  The open engine for AI-powered search and observability  | [OpenSearch website](https://opensearch.org/) |
|  |  |	FastText |  Library for efficient text classification and representation learning (can be used to detect language)  | [FastText website](https://fasttext.cc/) |
| Semantic layer | Embeddings over chunks, a vector index, and fusion with lexical results |	pgvector with an HNSW index |  | [GitHub - pgvector](https://github.com/pgvector/pgvector/) |
|  |  |	bge-m3 | Embedded model mixed French and English | [Hugging Face - BGE-M3](https://huggingface.co/BAAI/bge-m3) |
|  |  |	multilingual-e5 | Embedded model mixed French and English | [Hugging Face - Multilingual-E5-large ](https://huggingface.co/intfloat/multilingual-e5-large) |
|  |  |	nomic-embed-text | Embedded model English-only | [Hugging Face - nomic-embed-text-v1 ](https://huggingface.co/nomic-ai/nomic-embed-text-v1) |
|  |  |	SentenceTransformers (SBERT) | Python module for using and training state-of-the-art embedding and reranker models | [SBERT webiste](https://sbert.net/) |
|  |  |	Ollama | Ollama lets you use open models with your coding agents so you can spend less while keeping your data private | [Ollama website](https://ollama.com/) |
|  |  |	Llama.cpp | Run efficient Large Language Model Inference in pure  C/C++ | [Llama.cpp website](https://llama-cpp.com/) |
|  |  |	Hugging Face's Text Embeddings Inference server | Toolkit designed for efficient deployment and serving of open source text embeddings models | [Text Embeddings Inference](https://huggingface.co/docs/text-embeddings-inference/en/index) |
|  |  |	bge-reranker-v2-m3 | Different from embedding model, reranker uses question and document as input and directly output similarity instead of embedding | [Reranker](https://huggingface.co/BAAI/bge-reranker-v2-m3) |
| The LLM as query planner | Good tool surface, because the planning happens in the agent |	Model Context Protocol (MCP) | Open-source standard for connecting AI applications to external systems | [MCP website](https://modelcontextprotocol.io/docs/2026-07-28/getting-started/intro) |
| Entity extraction at ingestion | Structured extraction for the categories people ask about most: purchases, bookings, appointments, bills |	Schema.org | Collaborative, community activity with a mission to create, maintain, and promote schemas for structured data on the Internet, on web pages, in email messages, and beyond | [Schema.org website](https://schema.org/) |
|  |  |	iCalendar | Open standard for exchanging calendar and scheduling information between users and computers | [iCalendar website](https://icalendar.org/) |
|  |  |	dateparser |  | [dateparser website](https://dateparser.readthedocs.io/en/stable/) |
|  |  |	Duckling | Haskell library that parses text into structured data | [GitHub - Duckling](https://github.com/facebook/duckling) |
|  |  |	phonenumbers | Python version of Google's common library for parsing, formatting, storing and validating international phone numbers | [phonenumbers](https://pypi.org/project/phonenumbers/) |
|  |  |	price-parser | Small library for extracting price and currency from raw text strings | [GitHub - price-parser](https://github.com/scrapinghub/price-parser) |
|  |  |	spaCy | Named entities | [spaCy website](https://spacy.io/) |
|  |  |	GLiNER | Named entities: framework for training and deploying small Named Entity Recognition (NER) models with zero-shot capabilities | [GitHub - GLiNER](https://github.com/urchade/GLiNER) |
|  |  |	Instructor | Structured outputs powered by LLMs | [Instructor website](https://useinstructor.com/) |
|  |  |	Outlines | Outlines guarantees structured outputs during generation — directly from any LLM | [Outlines website](https://dottxt-ai.github.io/outlines/latest/) |
|  |  |	llama.cpp grammars | GBNF (GGML BNF) is a format for defining formal grammars to constrain model outputs in llama.cpp | [GitHub - GBNF Guide](https://github.com/ggml-org/llama.cpp/tree/master/grammars) |
| Personal context signals | Interaction statistics per entity, used to rank and disambiguate |	RapidFuzz | For suggested merges, handles string similarity | [GitHub - RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) |
|  |  |	Splink | Package for probabilistic record linkage (entity resolution) that allows you to deduplicate and link records from datasets that lack unique identifiers | [GitHub - Splink](https://github.com/moj-analytical-services/splink) |
|  |  |	Apache AGE | PostgreSQL Graph database compatible with PostgreSQL's distributed assets and leverages graph data structures to analyze and use relationships and patterns in data (may be overkill) | [Apache AGE website](https://age.apache.org/) |
| Large context and iteration | Results shaped so an agent can afford to search repeatedly, especially a local model with a modest context window |	tokenizer of your chosen model (or tiktoken) | Count tokens. If you build your own client later, Pydantic AI, LangGraph or smolagents can handle the loop | [TikToken website](https://tiktoken.net/) |
| Deep integration with the data | Equivalent of App Intents, meaning typed, discoverable operations that clients can rely on |	MCP SDK, plus FastAPI for REST |  | []() |


                         OFFLINE
Documents ──► parse/chunk ──► embeddings ──► search index
                                      │
                                      └──► metadata / features

                         ONLINE
User query
   │
   ▼
query processing
   │
   ├──► lexical search (BM25 / Elasticsearch / Solr)
   │
   └──► semantic search (embedding → vector search)
                 │
                 ▼
          candidate set, e.g. 100
                 │
                 ▼
             reranker
       (ML model / Vertex AI / LLM)
                 │
                 ▼
          top 5–10 results
                 │
                 ▼
               RAG
                 │
                 ▼
                LLM
                 │
                 ▼
             final answer

## Offline pipeline

Stage contract: every derived table is keyed by (input hash or id, stage version), and re-running a stage is a no-op unless the version changed.

Documents ─► parse ─► canonicalize ─► enrich ─► chunk ─┬─► embeddings ─► vector index
                                                       ├─► BM25 index
                                                       └─► metadata columns (filters)

Let's use the example of an email to follow the pipeline:

From 1790123456789012345@xxx Tue Mar 17 13:32:08 +0000 2026
X-GM-THRID: 1790123456789012345
X-Gmail-Labels: Inbox,Important,Projects
Message-ID: <CAF7x9=roof-2291@mail.gmail.com>
In-Reply-To: <orig-001@mail.gmail.com>
References: <orig-001@mail.gmail.com>
Date: Tue, 17 Mar 2026 09:32:08 -0400
From: Mike Turner <mike@turnerroofing.com>
To: Alex Dupont <alex.dupont@gmail.com>
Cc: billing@turnerroofing.com
Subject: Re: Roof quote - 12 Elm Street
Content-Type: multipart/mixed
  ├─ multipart/alternative
  │    ├─ text/plain
  │    └─ text/html
  └─ application/pdf; name="quote-2026-0412.pdf"

Hi Alex,

Following our site visit, here is the revised quote: $8,400 including
materials and labor for the full roof replacement (natural slate). We
could start on Monday, April 6. I can stop by Thursday at 10am to
finalize, does that work for you?

Best regards,
Mike Turner
Turner Roofing | (415) 555-0142

On Tue, Mar 10, 2026 at 9:15 AM Alex Dupont <alex.dupont@gmail.com> wrote:
> Can you confirm the price? The first quote was $9,200.

Attachment:
The PDF text is a quote ("QUOTE #2026-0412") with Materials $4,650.00, Labor $3,750.00 and Total $8,400.00.

Notes from building online plan:
- Trash/spam needs a canonical flag. Tags are provider-namespaced (gmail:Trash), but the default exclusion must work for Apple Mail folders too. Canonicalization should compute an is_trash_or_spam boolean on the item, and denormalize it onto the chunk or filter through the item.
- Index every chunk twice: language-specific and simple. - Language detection will be wrong sometimes, on short replies, mixed-language messages, or languages you don't support. A wrongly tagged chunk gets stemmed badly and may be unfindable by keyword. A second, unstemmed index over all chunks fixes that. It also gives exact matching for names, invoice numbers, amounts and tokens like 2026-0412, which stemming can mangle. The cost is roughly double the lexical index size, which is small at mailbox scale. I'd treat the simple branch as mandatory, not optional. --> Let's ignore internationalization for now
- Use chunks schema in chunk_schemas.sql


### 1. Documents
#### 1.1. Archive intake
Ingest the whole archive file, all the emails imported at once, into object storage. The DB only gets one small metadata row. The SHA-256 hash  does two jobs: it detects when you upload the same archive twice, and it proves the evidence hasn't been altered. Attachments are not separate objects yet, they only exist as base64 inside the mbox.

raw.archive
  provider = google          
  sha256   = 3b9a…           
  status   = received → split
  format = takeout_mbox
  storage_uri = seaweedfs://rosalind-raw/archives/3b/3b9a…

#### 1.2. Record split
Cuts the archive into individual messages, attachment included. Still live in the object storage (possible optimization is to save just its offset and length inside the archive instead of storing the exact bytes of each message to save space), and save one row per message in the DB.

raw.source_record
  resource_type  = gmail.message
  external_id    = <CAF7x9=roof-2291@mail.gmail.com>
  payload_sha256 = 91d7a2…
  payload_uri    = seaweedfs://…/records/91/91d7…

### 2. Parse
#### 2.1 Parse to observation (pure)
This stage is a function, it just takes the email from previous step, parse it and return structured data for our canonical objects in the next step. This include attachment's metadata and the decoded bytes, in memory (filename, declared MIME type, size, and SHA-256 of the decoded bytes).

Edge cases to handle in the parser: 
- A forwarded email attached as message/rfc822 (return it as a nested ParsedEmail, or flag it)
- A declared type that disagrees with the real file (check magic bytes with python-magic or filetype).

{
  "message_id": "CAF7x9=roof-2291@mail.gmail.com",
  "in_reply_to": "orig-001@mail.gmail.com",
  "references": ["orig-001@mail.gmail.com"],
  "provider_thread_hint": "1790123456789012345",
  "date_header": "Tue, 17 Mar 2026 09:32:08 -0400",
  "date_utc": "2026-03-17T13:32:08Z",
  "date_offset_minutes": -240,
  "subject": "Re: Roof quote - 12 Elm Street",
  "addresses": [
    {"role":"from","name":"Mike Turner","addr":"mike@turnerroofing.com"},
    {"role":"to","name":"Alex Dupont","addr":"alex.dupont@gmail.com"},
    {"role":"cc","name":null,"addr":"billing@turnerroofing.com"}
  ],
  "provider_tags": ["Inbox","Important","Projects"],
  "text_plain": "Hi Alex, Following our...",
  "text_html": "Hi Alex, Following our...",
  "attachments": [{"filename":"quote-2026-0412.pdf","mime":"application/pdf",
                   "size":41877,"sha256":"e5a1…", "disposition": attachment vs inline}],
  "parse_warnings": [],
  "parser_version": "gmail-mbox/1.3.0"
}

### 3. Canonicalize
#### 3.1. Canonicalize to items
Takes parsed data from previous step and saves it in DB. It also saves attachments in object storage as blob (binary file stored without interpretation and addressed by its hash (blobs/e5/e5a1…))

item.email
  id             = uuid5(NS, source_account_id || ':' || CAF7x9=roof-2291@…)   → e_9f2c
  occurred_at    = 2026-03-17T13:32:08Z
  utc_offset_min = -240
  direction      = received       (alex.dupont@gmail.com ∈ account self-handles)
  subject        = Re: Roof quote - 12 Elm Street
  "text_plain": "Hi Alex, Following our...",
  "text_html": "Hi Alex, Following our...",
  has_attachments = true

item.participant   (entity_id is null at this stage)
  from  email  mike@turnerroofing.com     "Mike Turner"
  to    email  alex.dupont@gmail.com      "Alex Dupont"
  cc    email  billing@turnerroofing.com  null

item.attachment    quote-2026-0412.pdf  application/pdf  blob e5a1…  status=present "disposition": attachment vs inline
item.tag           gmail:Inbox, gmail:Important, gmail:Projects
conv.thread        t_41aa  root_message_id=orig-001@mail.gmail.com
                           provider_hint=1790123456789012345

#### 3.2. Reconcile 
Builds conv.thread from References, and later computes which quoted segments are covered by an existing item. Both depend on other items in the DB, so they can't happen in the parser. They must be re-runnable when an older message arrives later.

### 4. Enrich
#### 4.1. Derived text
Turns a raw message into clean, segmented text that both extraction and chunking consume. We split the email into body, signature, quoted text and attachment text. We also segment's detect language at this stage.

What is does:
- Get plain text. Use the text/plain part, or convert HTML (selectolax) if there isn't one.
- Segment the body into new content, quoted history, signature, disclaimer, and forwarded content.
- Detect language per segment.
- Extract attachment text. PDF text layer, Office files via docling, OCR for scans. This is the slow, expensive part.

Key attachment_text by blob_sha256, not by attachment ID. The same PDF attached to ten emails then gets OCRed once.

Note: at this stage, we focus on text only, images and other formats to be handled at a later stage

derived.item_text        (item_id, version) → clean_text, method ('plain'|'html')

derived.item_segment     (item_id, version, seq)
  kind                   new | quoted | signature | disclaimer | forwarded
  text, language, language_confidence
  quoted_author, quoted_at         -- from the attribution line
  covered_by_item_id               -- null = orphan quote, treated as content

derived.attachment_text  (blob_sha256, version) → text, method, page_count, language


Example:
derived.item_text   "Hi Alex, Following our site visit, here is the revised quote:
                    $8,400 including materials and labor for the full roof
                    replacement (natural slate). We could start on Monday,
                    April 6. I can stop by Thursday at 10am to finalize,
                    does that work for you?"

derived.item_segment     (item_id, version, seq)
  kind                   new
  text                   "Hi Alex, Following our site visit, here is the revised quote:
                         $8,400 including materials and labor for the full roof
                         replacement (natural slate). We could start on Monday,
                         April 6. I can stop by Thursday at 10am to finalize,
                         does that work for you?"
  language                  en
  language_confidence       98%
  quoted_author, quoted_at  mike@turnerroofing.com
  covered_by_item_id               -- null = orphan quote, treated as content

derived.attachment_text  (blob_sha256, version) → text, method, page_count, language
    "QUOTE #2026-0412 … Materials $4,650.00 … Labor $3,750.00 … Total $8,400.00"


#### 4.2. Extraction
This is where we analyze the email and extract useful data for future search.
Example and schemas for data to be extracted can be found at:
https://schema.org/FlightReservation
https://developers.google.com/workspace/gmail/markup/overview#google-calendar
Generic types (Duckling/OntoNotes)


Tier list:
- Mentions: dates, amounts, phones, addresses
- Structured documents: reservations, orders, invoices, events
- Message type: receipt, quote, appointment

Extractors read from two places:
- Generic mentions come from segments (new content, plus orphan quotes)
- Schema.org and ICS come from the original text_html and attachment bytes, because the clean-text conversion strips the markup.

The schema example should show the columns that make it auditable: source segment or blob, span offsets, extractor, extractor_version, confidence, source_hash

derived.extraction
  amount           {value: 8400.00, currency: USD}                        segment_reference   price-parser
  amount           {value: 8400.00, currency: USD, label: "Total"}        pdf        ← corroborates
  amount           {value: 4650.00, currency: USD, label: "Materials"}    pdf
  amount           {value: 3750.00, currency: USD, label: "Labor"}        pdf
  datetime_mention {text: "Monday, April 6", resolved: "2026-04-06",
                    precision: "day"}                                      dateparser
  datetime_mention {text: "Thursday at 10am", resolved: "2026-03-19T10:00-04:00",
                    anchor: "occurred_at", precision: "minute"}            dateparser
  phone            {e164: "+14155550142"}                                  phonenumbers

### 5. Chunk
#### 5.1. Chunking
A chunk is a passage of text that is the unit of retrieval. For email, a short message is one chunk. A long message or attachment is split at paragraph boundaries into roughly 300–500 token pieces, with a small overlap. Every chunk gets a contextual prefix (subject, sender, date), so it still makes sense when seen alone.


chunk A  (email_body)
  text_for_index:
    "Email · Re: Roof quote - 12 Elm Street · From Mike Turner (turnerroofing.com)
     to Alex Dupont · March 17, 2026
     Hi Alex, Following our site visit, here is the revised quote: $8,400
     including materials and labor for the full roof replacement …"
  language            = en            (tsvector built with the 'english' config)
  time
  kind
  participant_handles = {mike@turnerroofing.com, alex.dupont@gmail.com, billing@turnerroofing.com}
  tags                = {gmail:Inbox, gmail:Projects}

chunk B  (attachment)
  text_for_index:
    "Attachment quote-2026-0412.pdf from Mike Turner, March 17, 2026
     QUOTE #2026-0412 … Full roof replacement … Total $8,400.00"

### 6. Embedding
#### 6.1. Embedding
Each chunk's text_for_index (prefix included) goes to the embedding model, and the resulting vector is stored next to the chunk.

search.chunk_embedding
  (chunk A, bge-m3, v1) → vector(1024)
  (chunk B, bge-m3, v1) → vector(1024)

### Indexing stategy
#### Indexes
##### 1. Lexical: BM25 on the chunk text (ParadeDB pg_search)
CREATE INDEX chunk_bm25_idx ON search.chunk
USING bm25 (id, text_for_index, language)
WITH (key_field = 'id');

##### 2. Semantic: HNSW on the embeddings (pgvector)
--    chunk_embedding.embedding is declared as plain `vector`, so one table
--    can hold several models. Each model gets its own partial index.
CREATE INDEX chunk_emb_bge_m3_v1_idx ON search.chunk_embedding
USING hnsw ((embedding::vector(1024)) vector_cosine_ops)
WHERE model = 'bge-m3' AND model_version = 'v1';

##### 3. Filters: the columns nearly every query narrows on
CREATE INDEX chunk_time_idx         ON search.chunk (occurred_from, occurred_to);
CREATE INDEX chunk_conversation_idx ON search.chunk (conversation_id);
CREATE INDEX chunk_kind_lang_idx    ON search.chunk (chunk_kind, language);
CREATE INDEX chunk_participants_idx ON search.chunk USING gin (participant_handles);
CREATE INDEX chunk_tags_idx         ON search.chunk USING gin (tags);
CREATE INDEX chunk_items_idx        ON search.chunk USING gin (item_ids);

##### 4. Joins used by structured lookups
CREATE INDEX extraction_item_type_idx ON derived.extraction (item_id, type);
CREATE INDEX participant_handle_idx   ON item.participant (handle_type, handle_value);

#### What each one is for
| Index |	Query it serves |
| :--- | :--- |
| BM25 on text_for_index |	Keyword matching and ranking: "roof quote" |
| HNSW on embedding	| Nearest-neighbor search: "how much did the roofer charge" matches a chunk that says "$8,400 for the slate replacement" |
| btree on time / conversation |	"last month", and get_context / get_thread expansion |
| GIN on participant_handles, tags, item_ids |	Array containment: "involving mike@turnerroofing.com", "tagged gmail:Projects" |
| extraction (item_id, type) |	The EXISTS join for "has an amount" without denormalizing it onto the chunk |
| participant (handle_type, handle_value) |	Joining handles to entities at query time |

#### How the indexes get used

WITH lexical AS (
  SELECT id, row_number() OVER (ORDER BY paradedb.score(id) DESC) AS rank
  FROM search.chunk
  WHERE text_for_index @@@ 'roof quote'              -- BM25 index
    AND participant_handles @> ARRAY['mike@turnerroofing.com']  -- GIN
    AND occurred_from >= '2026-01-01'                -- btree
  LIMIT 50
),
semantic AS (
  SELECT c.id, row_number() OVER (ORDER BY e.embedding <=> :query_vec) AS rank
  FROM search.chunk_embedding e
  JOIN search.chunk c ON c.id = e.chunk_id
  WHERE e.model = 'bge-m3' AND e.model_version = 'v1'   -- matches the partial index
    AND c.participant_handles @> ARRAY['mike@turnerroofing.com']
    AND c.occurred_from >= '2026-01-01'
  ORDER BY e.embedding <=> :query_vec
  LIMIT 50
)
SELECT id, sum(1.0 / (60 + rank)) AS rrf_score      -- reciprocal rank fusion
FROM (SELECT * FROM lexical UNION ALL SELECT * FROM semantic) t
GROUP BY id
ORDER BY rrf_score DESC
LIMIT 20;

### TBD: Entity resolution
core.entity
  Alex Dupont        person   handle: alex.dupont@gmail.com        (self, from account config)
  Mike Turner        person   handle: mike@turnerroofing.com       (new, deterministic)
  Turner Roofing billing  org?  handle: billing@turnerroofing.com  (role mailbox, new)

core.merge_suggestion
  Mike Turner ↔ billing@turnerroofing.com   reason: same domain   status: pending
  → suggested org entity "Turner Roofing"                          status: pending


## Online search
External agent, Rosalind exposed via MCP.
MCP tools:
describe_capabilities   filters, kinds, sources, date coverage
find_entity             name → handles / entity
search                  see below
get_context             neighbors of a hit  
get_thread              ordered email thread
get_item                full item + extractions
list_extractions        structured queries  

filters (SQL WHERE) ──┬─► lexical (BM25)  │
                │                           └─► semantic (vector)
                │                                   ▼           │
                │                              fusion (RRF)     │
                │                                   ▼           │
                │                        reranker (top ~30–50)  │
                │                                   ▼           │
                │                        context assembly       │
                │                   (dedupe, budget, citations)



### 0. Request            query text + SearchFilters (from the agent)
from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class SearchFilters(BaseModel):
    """Lists are OR within a field; different fields are AND."""
    model_config = ConfigDict(extra="forbid")   # a typo'd field errors instead of being ignored

    sender: list[str] | None = Field(None, description="Email addresses or entity IDs (from find_entity).")
    recipient: list[str] | None = Field(None, description="To/Cc/Bcc.")
    participant: list[str] | None = Field(None, description="Any role.")
    direction: Literal["received", "sent"] | None = None
    date_from: date | None = Field(None, description="Inclusive. ISO date.")
    date_before: date | None = Field(None, description="Exclusive. ISO date.")
    tags: list[str] | None = Field(None, description="Any of. Namespaced, e.g. 'gmail:Projects'.")
    exclude_tags: list[str] | None = None
    has_attachment: bool | None = None
    thread_id: UUID | None = None
    language: list[str] | None = Field(None, description="ISO 639-1, e.g. ['fr','en'].")
    source_accounts: list[UUID] | None = None
    include_trash_spam: bool = False

class SearchEmailsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(None, description="What you're looking for, in natural language. "
        "Used for semantic search, and for keyword search unless `keywords` is set.")
    keywords: str | None = Field(None, description="Optional exact-match terms for keyword search "
        "(names, IDs, amounts). Supports \"quoted phrases\".")
    filters: SearchFilters = SearchFilters()
    sort: Literal["relevance", "date_desc", "date_asc"] | None = None  # default: relevance if query, else date_desc
    group_by: Literal["message", "thread"] = "message"
    view: Literal["metadata", "snippet"] = "snippet"
    limit: int = Field(10, ge=1, le=25)
    cursor: str | None = None
    mode: Literal["hybrid", "lexical", "semantic"] = "hybrid"   # mainly for evaluation
    # validator: at least one of query / keywords / any filter must be set


### 1. Prepare            validate filters, resolve handles, embed query
What is done here:
auth context → scope → cursor decode → validate → normalize
   → [entity/tag lookups ‖ query embedding] → build plan → short-circuit checks → audit start

Prepare receives from the adapter (iss, sub) mapped to an account, and never reads it from tool arguments.

#### 1.1. Validate
Pydantic covers types. Prepare covers meaning:
- at least one of query, keywords or a filter
- date_from < date_before
- mode is consistent with the inputs (semantic mode with only keywords makes no sense)
- the cursor decodes, matches this account, and matches the current index version, otherwise it fails with a clear message
- lengths are within bounds (query length, list sizes, so a filter with 5,000 addresses can't be sent)

Three outcomes:
| Situation |	Behavior |
| :--- | :--- |
| Malformed (bad date range, unknown field)	| Hard error that says how to fix it |
| Valid but suspicious (tag nobody has, sender never seen) |	Proceed, with a warning and a suggestion. For example: A warning like "no tag gmail:Project; did you mean gmail:Projects?" fixes it. A fuzzy match with rapidfuzz against the account's tags is enough. |
| Valid but impossible (empty range, entity with no handles) |	Short-circuit with an explanation, with no retrieval |

#### 1.2. Normalize
- Addresses: use the same normalization function as canonicalization. If the two diverge (case, plus-tags), filters silently miss. A shared function, tested for idempotency, is the safeguard.
- Entity IDs: expand each to all its known handles, restricted to what this account can see.
"me" alias: let the agent write me in sender, recipient and participant, expanding to the account's self-handles. Agents reach for this constantly and it removes a lookup call.
- Dates: convert to UTC bounds using a timezone. Rosalind doesn't persist profile data (§6.4), but Keycloak's standard zoneinfo claim, if populated, arrives with the token at request time. Fall back to a server setting. The resolved timezone goes into the echoed filters so the agent sees what "March 1" meant.
- Tags and languages: canonicalize case and validate against known values.
- Relative dates: don't parse "last week" here. The agent resolves it using the date from describe_capabilities, and Prepare only accepts ISO. Parsing it here would be guessing intent.

#### 1.3. Prepare the query text
- Clean: Unicode normalization, whitespace trimming, a length cap tied to what the embedding model sensibly accepts.
- Sanitize keywords for the BM25 query syntax. Characters like quotes, colons and parentheses can mean operators in the search engine. Parse the quoted phrases yourself and escape or strip the rest, or a keyword like C++ or 12 Elm St. throws a syntax error. This is a correctness issue as much as a security one.
****** 
Parked for now, ignore 
- Language handling is the hard part. Each chunk's lexical index uses its own language config, so the query must be analyzed with the same config to match stems. In a mixed mailbox, one detected query language isn't enough: a French question may target an English chunk. Options:
  - compile the lexical query once per language present in the corpus and match each against chunks of that language
  - detect the query language and also include simple
  - rely on filters.language when the agent sets it
Short queries are poorly detected anyway, so I lean toward the first.
******


#### 1.4. Embed the query
- Skip it when mode="lexical".
- Run it in parallel with the database lookups. They are independent, and the embedding is the slowest part of Prepare.
- The embedding model's own conventions (query prefixes, normalization) live in the Embedder adapter, so the application layer doesn't know them.
- Cache by (model, version, text). Agents repeat queries often.
- If the embedding service is down, you can either fail or fall back to lexical and say so in the response. I'd degrade and warn, with the actual mode reported back, since a partial answer helps an agent more than an error. This should be an explicit choice.

#### 1.5. Build the plan
The plan is one frozen object holding:
- the mandatory scope predicate and the resolved filters
- compiled lexical queries and the query vector
- effective mode, sort and group-by
- candidate sizes for each later stage, from configuration
- version stamps: index version, embedding model and version, and a reranker version (for later)

It has three uses:
- It is what applied_filters echoes back
- It is what the cursor encodes, so paging is reproducible
- It is what evaluation logs, so a run can be replayed.

#### 1.6. Optional: choose a strategy from filter selectivity
A cheap count of how many chunks the filters leave tells you whether to use the vector index or scan exactly. Filtered HNSW search degrades when filters are very selective. If a filter leaves 300 chunks, an exact scan is faster and more accurate. It's an optimization, so I'd note it as a hook and measure first.

#### 1.7. Output
SearchPlan
├── identity
│     request_id, audit_id, account_id, client_id, plan_fingerprint
├── scope                        non-removable, separate from filters
│     source_account_ids: set    (later: grant reference)
├── filters                      resolved
│     senders / recipients / participants:  sets of normalized handles
│     direction, tags_any, tags_exclude, has_attachment, thread_id, language
│     date_from_utc, date_before_utc, timezone_used
│     include_trash_spam
├── query
│     semantic_text: str | None
│     lexical: { terms: [...], phrases: [...] } | None     structured, not engine syntax
│     query_vector: vector | None
├── behavior
│     strategy: ranked | list
│     mode_requested, mode_effective
│     sort, group_by, view, limit
│     cursor: { window_offset, last_sort_key } | None
├── budgets                      from config, never from the agent
│     lexical_k, semantic_k, fused_k, rerank_k, return_k
├── versions
│     index_version, embedding_model, embedding_version, reranker_version
├── applied                      what the response echoes as `applied_filters`
├── warnings                     [{code, field, message, suggestion}]
├── hints
│     estimated_matching_chunks: int | None     (the 1.6 selectivity hook)
└── timings_ms                   {validate, resolve, embed, total}

### 2. Retrieve
Lives in backend/src/rosalind/application/search/

#### 2.1 lexical (filtered) (BM25)
Takes the plan's scope, filters, query.lexical and budgets.lexical_k. It returns an ordered list of chunk IDs with ranks.

Output:
LexicalResult
  hits: [(chunk_id, rank, score)]       up to lexical_k
  exhausted: bool                        fewer than lexical_k matched in total
  filter_path: "pushdown" | "overfetch"  how the filters were applied
  warnings, elapsed_ms

#### 2.2 semantic (filtered) (vector)
same contract as 2.1. It takes the plan's scope, filters, query.vector and budgets.semantic_k, and returns ranked chunk IDs.

Output:
SemanticResult
  hits: [(chunk_id, rank, distance)]       up to semantic_k
  complete: bool        every matching chunk was considered (exact path, or fewer matches than k)
  filter_path: "exact" | "ann_iterative"
  scan_limit_hit: bool  the ANN scan stopped early and may have missed matches
  warnings, elapsed_ms

### 3. Fuse
Reciprocal rank fusion (RRF)
It merges the two ranked chunk lists into one candidate list for the reranker. It's a pure function with no database access, so it lives in application/services.
Each candidate keeps its per-branch rank and score. Step 5 can then tell the agent whether a result matched by keyword, by meaning or both, and your eval harness can see which branch found the answer. If a branch is missing (lexical-only mode, or a degraded call), fusion passes the other list through unchanged.


fuse(plan, lexical: LexicalResult | None, semantic: SemanticResult | None) -> FusedCandidates

FusedCandidates
  candidates: [(chunk_id, fused_score, lexical: (rank, score) | None, semantic: (rank, distance) | None)]
  branches_used: {lexical: bool, semantic: bool}
  dropped_by_item_cap: int


Considerations:
A correction first. I told you RRF needs no tuning. The literature says that's too strong. Reciprocal rank fusion scores each chunk as the sum of 1 / (k + rank) over the lists it appears in, with the usual constant k = 60 from the original paper. Bruch, Gai and Ingber's analysis of hybrid fusion found RRF sensitive to its parameters. They also found that a convex combination of normalized lexical and semantic scores beat RRF both in-domain and out-of-domain, and that it needs only a small labelled set to tune its single weight. Cormack's original claim, which they cite, was that RRF is non-parametric and works zero-shot. So the evidence is mixed in a way that matters for you: RRF is the safe start when you have no labels, and CC can win once you have some.

My recommendation:
- v1: RRF with k = 60 and equal weights. It needs no normalization and you have no training data yet.
- Put it behind a FusionStrategy interface. Parameters live in configuration and in the plan, so the fingerprint changes when they do.
- Compare against convex combination on your eval set. Your 30 to 50 questions are enough to tune a single weight, which is what the paper says CC needs. For CC, min-max normalize the BM25 scores per query, use cosine similarity as is, and score a chunk missing from one list as 0 on that side.
- Judge the methods by recall@fused_k, not by top-of-list quality. The reranker reorders the top candidates anyway, so fusion's real job is to get the answer chunk into the window. Order quality matters only if you run without the reranker.

After scoring, three rules apply in order:
- Sort deterministically: fused score descending, then number of branches containing the chunk, then best rank, then chunk ID. The same inputs must always give the same output.
- Cap chunks per message (config, default 2 or 3, best by fused score). A long PDF attachment can contribute twenty chunks to one candidate list, and that wastes reranker slots and crowds out other emails. This is a change from my earlier plan, where I said to leave all grouping to assembly. Assembly still groups results for display, but crowding has to be prevented before reranking, because the reranker has a fixed budget.
- Truncate to fused_k.


### 4. Rerank
It reorders the top fused candidates with a cross-encoder. A cross-encoder reads the query and one chunk together and outputs a relevance score. It's more accurate than comparing separately computed embeddings, but it costs one model pass per candidate.

It sits behind a Reranker port in application/ports, with a TEI adapter in adapters/outbound. It runs only for the ranked strategy, and only when versions.reranker is set.

Model choice: bge-reranker-v2-m3

Considerations:
The reranker is optional and switchable by configuration, and your eval set decides:
- Compare with and without it on nDCG@10 or MRR of the final order, and on recall within window_k.
- Compare rerank_k of 20, 40 and 60. Larger is rarely better.
- Compare chunk text with and without the prefix.
- Include the cross-lingual cases (the Spanish, French and English example) specifically, because that's where score behavior is least predictable.
- Record p50 and p95 latency for each setting.


rerank(plan, fused) -> RerankResult

RerankResult
  ranked: [(chunk_id, rerank_rank, rerank_score, fused_rank)]
  applied: bool            False if disabled, skipped or failed
  model: str | None
  warnings, elapsed_ms




### 5. Assemble (Context assembly (dedupe, budget, citations))
Output:
{
  "results": [{"item_id":"…","thread_id":"…","chunk_id":"…","subject":"…","from":"…",
               "date":"…","snippet":"…","matched_in":"body|attachment","score":0.0}],
  "applied_filters": { "...resolved, normalized echo of what was actually used..." },
  "total_estimate": 134,
  "next_cursor": null,
  "warnings": ["no results matched filters; 0 emails from sender X before 2026-01-01"]
}