import os
from typing import Optional

# Environment variables specific to the subpackage
ENV_ARIZE_SPACE_ID = "ARIZE_SPACE_ID"
ENV_ARIZE_API_KEY = "ARIZE_API_KEY"
ENV_ARIZE_PROJECT_NAME = "ARIZE_PROJECT_NAME"
ENV_ARIZE_PROJECT_TYPE = "ARIZE_PROJECT_TYPE"
ENV_ARIZE_COLLECTOR_ENDPOINT = "ARIZE_COLLECTOR_ENDPOINT"
ENV_ARIZE_BLOB_ENDPOINT = "ARIZE_BLOB_ENDPOINT"

ACCEPTED_PROJECT_TYPES = frozenset({"application", "harness", "experiment"})
DEFAULT_PROJECT_TYPE = "application"


def get_env_arize_space_id() -> str:
    return os.getenv(ENV_ARIZE_SPACE_ID, "")


def get_env_arize_api_key() -> str:
    return os.getenv(ENV_ARIZE_API_KEY, "")


def get_env_project_name() -> str:
    return os.getenv(ENV_ARIZE_PROJECT_NAME, "default")


def get_env_project_type() -> str:
    return os.getenv(ENV_ARIZE_PROJECT_TYPE, DEFAULT_PROJECT_TYPE)


def parse_project_type(value: str) -> str:
    if value not in ACCEPTED_PROJECT_TYPES:
        accepted = ", ".join(sorted(ACCEPTED_PROJECT_TYPES))
        raise ValueError(
            f"Invalid project_type {value!r}. Accepted values are: {accepted}."
        )
    return value


def get_env_collector_endpoint() -> Optional[str]:
    return os.getenv(ENV_ARIZE_COLLECTOR_ENDPOINT)


def get_env_blob_endpoint() -> Optional[str]:
    return os.getenv(ENV_ARIZE_BLOB_ENDPOINT)
