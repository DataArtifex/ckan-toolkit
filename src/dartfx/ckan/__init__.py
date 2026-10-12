# SPDX-FileCopyrightText: 2024-present kulnor <pascal.heus@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Public package API for the CKAN toolkit."""

from dotenv import find_dotenv, load_dotenv

from .ckan import (
    CKAN_DIRECTORY_URLS,
    COUNTRY_TO_ISO2,
    DEFAULT_CKAN_INSTALLATIONS,
    CKANApiError,
    SearchParameters,
    ServerInstallation,
    fetch_ckan_installations,
    get_iso2_code,
    matches_country,
)
from .exceptions import (
    CKANAPIRequestError,
    CKANConnectionError,
    CKANError,
    CKANValidationError,
)
from .harvester import (
    ServerHarvester,
    analyze_harvest_errors,
    classify_harvest_error,
    display_server_stats,
    fetch_active_datasets,
    fetch_dataset_record,
    fetch_server_stats,
    format_dataset_url,
    format_response_latency,
    format_version,
    resolve_server_token,
    save_server_token,
)
from .models import Dataset, HealthCheckResponse, Organization, Resource, ServerInfo, ServerStats, Tag
from .server import CKANServer

# Auto-load environment variables from .env file
load_dotenv(find_dotenv(usecwd=True))

__all__ = [
    "CKANAPIRequestError",
    "CKANApiError",
    "CKANConnectionError",
    "CKANError",
    "CKANServer",
    "CKANValidationError",
    "CKAN_DIRECTORY_URLS",
    "COUNTRY_TO_ISO2",
    "DEFAULT_CKAN_INSTALLATIONS",
    "Dataset",
    "HealthCheckResponse",
    "Organization",
    "Resource",
    "SearchParameters",
    "ServerInfo",
    "ServerInstallation",
    "ServerStats",
    "Tag",
    "ServerHarvester",
    "analyze_harvest_errors",
    "classify_harvest_error",
    "display_server_stats",
    "fetch_active_datasets",
    "fetch_dataset_record",
    "fetch_ckan_installations",
    "fetch_server_stats",
    "format_dataset_url",
    "format_response_latency",
    "format_version",
    "get_iso2_code",
    "matches_country",
    "resolve_server_token",
    "save_server_token",
]
