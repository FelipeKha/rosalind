"""Rosalind application layer: use cases, services, and ports.

Depends on ``domain`` and is depended upon by ``adapters``. It must not import
concrete adapter implementations; instead it defines ports (interfaces) that
adapters implement.
"""
