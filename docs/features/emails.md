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