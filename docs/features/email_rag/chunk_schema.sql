-- ============================================================================
-- search.chunk: revised schema (email only, embedding on the chunk row)
--
-- Sketch for docs/schema.md and a later Alembic migration. Not final DDL.
-- Verify against the versions you pin:
--   * pgvector >= 0.8.0 (halfvec, iterative index scans)
--   * the ParadeDB pg_search index syntax and tokenizer/filter options
--     (its docs describe a legacy API and a newer one)
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;
CREATE SCHEMA IF NOT EXISTS search;

-- Small integer surrogate for scope filtering. Chosen because index pushdown
-- documents integer types explicitly; uuid support is unconfirmed.
-- ALTER TABLE core.source_account ADD COLUMN num smallint GENERATED ALWAYS AS IDENTITY UNIQUE;

CREATE TABLE search.chunk (
    id                  uuid PRIMARY KEY,

    -- What the chunk is a piece of
    item_id             uuid        NOT NULL REFERENCES item.email (id) ON DELETE CASCADE,
    attachment_id       uuid        NULL REFERENCES item.attachment (id) ON DELETE CASCADE,
    thread_id           uuid        NULL REFERENCES conv.thread (id),
    chunk_kind          text        NOT NULL CHECK (chunk_kind IN ('email_body', 'attachment')),
    seq                 int         NOT NULL,          -- position within the item (or attachment)

    -- Text
    text_for_display    text        NOT NULL,
    text_for_index      text        NOT NULL,          -- contextual prefix + text
    text_sha256         bytea       NOT NULL,          -- lets a rebuild reuse an unchanged embedding
    language            text        NULL,              -- ISO 639-1, NULL = undetermined
    index_version       text        NOT NULL,          -- chunker + prefix template version

    -- Filter columns, denormalized from the item (see "Refresh" below)
    source_account_id   uuid        NOT NULL,
    source_account_num  smallint    NOT NULL,          -- scope predicate, pushdown-friendly
    sent_at             timestamptz NOT NULL,
    sender_handle       text        NOT NULL,          -- normalized address
    recipient_handles   text[]      NOT NULL DEFAULT '{}',   -- to/cc/bcc
    participant_handles text[]      NOT NULL DEFAULT '{}',   -- any role
    direction           text        NOT NULL CHECK (direction IN ('received', 'sent', 'self')),
    has_attachment      boolean     NOT NULL,
    is_trash_or_spam    boolean     NOT NULL DEFAULT false,  -- computed in canonicalization
    tags                text[]      NOT NULL DEFAULT '{}',   -- namespaced: gmail:Projects

    -- Embedding: one column per model version. Null until the embed job runs.
    embedding_bge_m3_v1 halfvec(1024) NULL,

    created_at          timestamptz NOT NULL DEFAULT now(),

    -- Idempotent chunking: re-running a stage with the same version is a no-op
    UNIQUE (item_id, chunk_kind, attachment_id, seq, index_version)
);

-- ----------------------------------------------------------------------------
-- Indexes (declared once in a migration, maintained by Postgres)
-- ----------------------------------------------------------------------------

-- 1. Lexical: BM25 on the chunk text (ParadeDB). SKETCH ONLY: tokenizer and
--    filter option names differ between pg_search versions.
--    Intended settings:
--      text_for_index   : ICU (or default) tokenizer, lowercase, ascii_folding
--      sent_at, source_account_num, has_attachment, is_trash_or_spam : included
--                          in the index so WHERE clauses can be pushed down
--      sender_handle, language, direction : literal tokenizer, so exact-match
--                          and set filters can be pushed down
--    Whether array columns (recipient_handles, participant_handles, tags) can
--    be pushed down is UNCONFIRMED. Test it; see the pushdown prototype.
--
-- CREATE INDEX chunk_bm25_idx ON search.chunk
-- USING bm25 (id, text_for_index, sent_at, source_account_num, has_attachment,
--             is_trash_or_spam, sender_handle, language, direction)
-- WITH (key_field = 'id', text_fields = '{ ... }');

-- 2. Semantic: HNSW on the embedding column. The column is typed halfvec(1024),
--    so no expression cast is needed and queries use the column directly.
CREATE INDEX chunk_emb_bge_m3_v1_hnsw ON search.chunk
    USING hnsw (embedding_bge_m3_v1 halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);
-- Bulk loads: backfill embeddings first, create this index afterwards.

-- 3. Filters used by both retrieval queries and by the exact-scan path
CREATE INDEX chunk_scope_time_idx ON search.chunk (source_account_num, sent_at DESC);
CREATE INDEX chunk_sender_idx     ON search.chunk (sender_handle);
CREATE INDEX chunk_thread_idx     ON search.chunk (thread_id);
CREATE INDEX chunk_item_idx       ON search.chunk (item_id);
CREATE INDEX chunk_recipients_idx   ON search.chunk USING gin (recipient_handles);
CREATE INDEX chunk_participants_idx ON search.chunk USING gin (participant_handles);
CREATE INDEX chunk_tags_idx         ON search.chunk USING gin (tags);

-- 4. "list" strategy (filter-only calls): keyset paging, one row per message.
--    seq = 0 of the email_body chunks represents the message.
CREATE INDEX chunk_list_idx ON search.chunk (source_account_num, sent_at DESC, item_id DESC)
    WHERE chunk_kind = 'email_body' AND seq = 0;

-- 5. Joins used elsewhere (unchanged from before)
-- CREATE INDEX extraction_item_type_idx ON derived.extraction (item_id, type);
-- CREATE INDEX participant_handle_idx   ON item.participant (handle_type, handle_value);

-- ----------------------------------------------------------------------------
-- Operations
-- ----------------------------------------------------------------------------

-- Embedding job (per chunk, idempotent):
--   UPDATE search.chunk SET embedding_bge_m3_v1 = :vec
--   WHERE id = :id AND embedding_bge_m3_v1 IS NULL;
--
-- Rebuild with a new chunker version: insert new rows (new index_version); copy
-- the embedding from an old row with the same text_sha256 instead of re-embedding.
--
-- Switch embedding model:
--   1. ALTER TABLE search.chunk ADD COLUMN embedding_<new> halfvec(<dim>);
--   2. backfill with the embed job
--   3. CREATE INDEX CONCURRENTLY ... USING hnsw (embedding_<new> halfvec_cosine_ops);
--   4. switch config (plan.versions.embedding_model / embedding_version)
--   5. DROP INDEX / DROP COLUMN for the old model
--
-- Refresh: tags, direction, is_trash_or_spam and the handle columns can change
-- when an item is re-observed or an older message arrives. A "refresh filter
-- columns" job, keyed by item_id, updates them in place. It is not a rebuild:
-- text, chunk boundaries and embeddings are untouched.
