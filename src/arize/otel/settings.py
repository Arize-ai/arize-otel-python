import os
from typing import Optional

# Environment variables specific to the subpackage
ENV_ARIZE_SPACE_ID = "ARIZE_SPACE_ID"
ENV_ARIZE_API_KEY = "ARIZE_API_KEY"
ENV_ARIZE_PROJECT_NAME = "ARIZE_PROJECT_NAME"
ENV_ARIZE_COLLECTOR_ENDPOINT = "ARIZE_COLLECTOR_ENDPOINT"


def get_env_arize_space_id() -> str:
    return os.getenv(ENV_ARIZE_SPACE_ID, "")


def get_env_arize_api_key() -> str:
    return os.getenv(ENV_ARIZE_API_KEY, "")


def get_env_project_name() -> str:
    return os.getenv(ENV_ARIZE_PROJECT_NAME, "default")


def get_env_collector_endpoint() -> Optional[str]:
    return os.getenv(ENV_ARIZE_COLLECTOR_ENDPOINT)
