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