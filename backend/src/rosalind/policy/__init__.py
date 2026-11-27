"""Rosalind policy service.

A separate deployable that interprets owner prompts into confirmed policies.
It shares PostgreSQL with the data warehouse but owns the ``authz``,
``semantic`` and ``audit`` schemas and never imports the RAG/search stack.
"""
