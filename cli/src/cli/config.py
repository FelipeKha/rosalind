"""CLI configuration accessors.

Values are resolved from environment variables and an optional YAML config
file. See :mod:`cli.settings` for the precedence and file layout.
"""

from __future__ import annotations

from cli import settings


def api_url() -> str:
    return settings.get_settings().api_url


def search_timeout() -> float:
    return settings.get_settings().search_timeout


def s3_endpoint() -> str:
    return settings.get_settings().s3_endpoint


def s3_access_key() -> str:
    return settings.get_settings().s3_access_key


def s3_secret_key() -> str:
    return settings.get_settings().s3_secret_key


def s3_bucket() -> str:
    return settings.get_settings().s3_bucket


def s3_region() -> str:
    return settings.get_settings().s3_region


def keycloak_url() -> str:
    return settings.get_settings().keycloak_url


def keycloak_realm() -> str:
    return settings.get_settings().keycloak_realm


def keycloak_client_id() -> str:
    return settings.get_settings().keycloak_client_id
