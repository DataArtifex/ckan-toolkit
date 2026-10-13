import csv
import io
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field

from .exceptions import CKANAPIRequestError

# Raw Country Name to ISO 3166-1 Alpha-2 Code Crosswalk (Alphabetical)
COUNTRY_TO_ISO2: dict[str, str] = {
    "AFGHANISTAN": "AF",
    "ALBANIA": "AL",
    "ALGERIA": "DZ",
    "ANDORRA": "AD",
    "ANGOLA": "AO",
    "ARGENTINA": "AR",
    "ARMENIA": "AM",
    "AUSTRALIA": "AU",
    "AUSTRIA": "AT",
    "AZERBAIJAN": "AZ",
    "BAHAMAS": "BS",
    "BAHRAIN": "BH",
    "BANGLADESH": "BD",
    "BARBADOS": "BB",
    "BELARUS": "BY",
    "BELGIUM": "BE",
    "BELIZE": "BZ",
    "BENIN": "BJ",
    "BHUTAN": "BT",
    "BOLIVIA": "BO",
    "BOSNIA AND HERZEGOVINA": "BA",
    "BOTSWANA": "BW",
    "BRAZIL": "BR",
    "BRUNEI": "BN",
    "BULGARIA": "BG",
    "BURKINA FASO": "BF",
    "BURUNDI": "BI",
    "CABO VERDE": "CV",
    "CAMBODIA": "KH",
    "CAMEROON": "CM",
    "CANADA": "CA",
    "CAPE VERDE": "CV",
    "CENTRAL AFRICAN REPUBLIC": "CF",
    "CHAD": "TD",
    "CHILE": "CL",
    "CHINA": "CN",
    "COLOMBIA": "CO",
    "COMOROS": "KM",
    "CONGO": "CG",
    "COSTA RICA": "CR",
    "CROATIA": "HR",
    "CUBA": "CU",
    "CYPRUS": "CY",
    "CZECH REPUBLIC": "CZ",
    "CZECHIA": "CZ",
    "DEMOCRATIC REPUBLIC OF THE CONGO": "CD",
    "DENMARK": "DK",
    "DEUTSCHLAND": "DE",
    "DJIBOUTI": "DJ",
    "DOMINICA": "DM",
    "DOMINICAN REPUBLIC": "DO",
    "ECUADOR": "EC",
    "EGYPT": "EG",
    "EL SALVADOR": "SV",
    "EQUATORIAL GUINEA": "GQ",
    "ERITREA": "ER",
    "ESTONIA": "EE",
    "ESWATINI": "SZ",
    "ETHIOPIA": "ET",
    "FIJI": "FJ",
    "FINLAND": "FI",
    "FRANCE": "FR",
    "GABON": "GA",
    "GAMBIA": "GM",
    "GEORGIA": "GE",
    "GERMANY": "DE",
    "GHANA": "GH",
    "GREAT BRITAIN": "GB",
    "GREECE": "GR",
    "GRENADA": "GD",
    "GUATEMALA": "GT",
    "GUINEA": "GN",
    "GUINEA-BISSAU": "GW",
    "GUYANA": "GY",
    "HAITI": "HT",
    "HOLLAND": "NL",
    "HONDURAS": "HN",
    "HONG KONG": "HK",
    "HUNGARY": "HU",
    "ICELAND": "IS",
    "INDIA": "IN",
    "INDONESIA": "ID",
    "IRAN": "IR",
    "IRAQ": "IQ",
    "IRELAND": "IE",
    "ISRAEL": "IL",
    "ITALY": "IT",
    "IVORY COAST": "CI",
    "JAMAICA": "JM",
    "JAPAN": "JP",
    "JORDAN": "JO",
    "KAZAKHSTAN": "KZ",
    "KENYA": "KE",
    "KIRIBATI": "KI",
    "KOREA": "KR",
    "KUWAIT": "KW",
    "KYRGYZSTAN": "KG",
    "LAOS": "LA",
    "LATVIA": "LV",
    "LEBANON": "LB",
    "LESOTHO": "LS",
    "LIBERIA": "LR",
    "LIBYA": "LY",
    "LIECHTENSTEIN": "LI",
    "LITHUANIA": "LT",
    "LUXEMBOURG": "LU",
    "MADAGASCAR": "MG",
    "MALAWI": "MW",
    "MALAYSIA": "MY",
    "MALDIVES": "MV",
    "MALI": "ML",
    "MALTA": "MT",
    "MARSHALL ISLANDS": "MH",
    "MAURITANIA": "MR",
    "MAURITIUS": "MU",
    "MEXICO": "MX",
    "MICRONESIA": "FM",
    "MOLDOVA": "MD",
    "MONACO": "MC",
    "MONGOLIA": "MN",
    "MONTENEGRO": "ME",
    "MOROCCO": "MA",
    "MOZAMBIQUE": "MZ",
    "MYANMAR": "MM",
    "NAMIBIA": "NA",
    "NAURU": "NR",
    "NEPAL": "NP",
    "NETHERLANDS": "NL",
    "NEW ZEALAND": "NZ",
    "NICARAGUA": "NI",
    "NIGER": "NE",
    "NIGERIA": "NG",
    "NORTH KOREA": "KP",
    "NORTH MACEDONIA": "MK",
    "NORWAY": "NO",
    "OMAN": "OM",
    "PAKISTAN": "PK",
    "PALAU": "PW",
    "PALESTINE": "PS",
    "PANAMA": "PA",
    "PAPUA NEW GUINEA": "PG",
    "PARAGUAY": "PY",
    "PERU": "PE",
    "PHILIPPINES": "PH",
    "POLAND": "PL",
    "PORTUGAL": "PT",
    "QATAR": "QA",
    "ROMANIA": "RO",
    "RUSSIA": "RU",
    "RWANDA": "RW",
    "SAINT KITTS AND NEVIS": "KN",
    "SAINT LUCIA": "LC",
    "SAINT VINCENT AND THE GRENADINES": "VC",
    "SAMOA": "WS",
    "SAN MARINO": "SM",
    "SAO TOME AND PRINCIPE": "ST",
    "SAUDI ARABIA": "SA",
    "SENEGAL": "SN",
    "SERBIA": "RS",
    "SEYCHELLES": "SC",
    "SIERRA LEONE": "SL",
    "SINGAPORE": "SG",
    "SLOVAKIA": "SK",
    "SLOVENIA": "SI",
    "SOLOMON ISLANDS": "SB",
    "SOMALIA": "SO",
    "SOUTH AFRICA": "ZA",
    "SOUTH KOREA": "KR",
    "SOUTH SUDAN": "SS",
    "SPAIN": "ES",
    "SRI LANKA": "LK",
    "SUDAN": "SD",
    "SURINAME": "SR",
    "SWEDEN": "SE",
    "SWITZERLAND": "CH",
    "SYRIA": "SY",
    "TAIWAN": "TW",
    "TAJIKISTAN": "TJ",
    "TANZANIA": "TZ",
    "THAILAND": "TH",
    "TIMOR-LESTE": "TL",
    "TOGO": "TG",
    "TONGA": "TO",
    "TRINIDAD AND TOBAGO": "TT",
    "TUNISIA": "TN",
    "TURKEY": "TR",
    "TURKMENISTAN": "TM",
    "TUVALU": "TV",
    "TÜRKIYE": "TR",
    "UGANDA": "UG",
    "UK": "GB",
    "UKRAINE": "UA",
    "UNITED ARAB EMIRATES": "AE",
    "UNITED KINGDOM": "GB",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "URUGUAY": "UY",
    "USA": "US",
    "UZBEKISTAN": "UZ",
    "VANUATU": "VU",
    "VATICAN CITY": "VA",
    "VENEZUELA": "VE",
    "VIETNAM": "VN",
    "YEMEN": "YE",
    "ZAMBIA": "ZM",
    "ZIMBABWE": "ZW",
}

# Common country code top-level domains and national suffixes
CCTLD_TO_ISO2: dict[str, str] = {
    "uk": "GB",
    "gb": "GB",
    "us": "US",
    "gov": "US",
    "ca": "CA",
    "au": "AU",
    "de": "DE",
    "fr": "FR",
    "nl": "NL",
    "it": "IT",
    "es": "ES",
    "ch": "CH",
    "jp": "JP",
    "br": "BR",
    "id": "ID",
    "za": "ZA",
    "in": "IN",
    "se": "SE",
    "no": "NO",
    "fi": "FI",
    "dk": "DK",
    "be": "BE",
    "at": "AT",
    "ie": "IE",
    "nz": "NZ",
    "pl": "PL",
    "cz": "CZ",
    "pt": "PT",
    "gr": "GR",
    "ro": "RO",
    "hu": "HU",
    "sg": "SG",
    "mx": "MX",
    "ar": "AR",
    "cl": "CL",
    "co": "CO",
    "pe": "PE",
    "ng": "NG",
    "ke": "KE",
    "gh": "GH",
    "rw": "RW",
    "ug": "UG",
    "sn": "SN",
    "tz": "TZ",
    "et": "ET",
    "eu": "EU",
    "sv": "SV",
}

ISO2_TO_COUNTRY: dict[str, str] = {
    "GB": "United Kingdom",
    "US": "United States",
    "CA": "Canada",
    "AU": "Australia",
    "DE": "Germany",
    "FR": "France",
    "NL": "Netherlands",
    "IT": "Italy",
    "ES": "Spain",
    "CH": "Switzerland",
    "JP": "Japan",
    "BR": "Brazil",
    "ID": "Indonesia",
    "ZA": "South Africa",
    "IN": "India",
    "SE": "Sweden",
    "NO": "Norway",
    "FI": "Finland",
    "DK": "Denmark",
    "BE": "Belgium",
    "AT": "Austria",
    "IE": "Ireland",
    "NZ": "New Zealand",
    "PL": "Poland",
    "CZ": "Czech Republic",
    "PT": "Portugal",
    "GR": "Greece",
    "RO": "Romania",
    "HU": "Hungary",
    "SG": "Singapore",
    "MX": "Mexico",
    "AR": "Argentina",
    "CL": "Chile",
    "CO": "Colombia",
    "PE": "Peru",
    "NG": "Nigeria",
    "KE": "Kenya",
    "GH": "Ghana",
    "RW": "Rwanda",
    "UG": "Uganda",
    "SN": "Senegal",
    "TZ": "Tanzania",
    "ET": "Ethiopia",
    "EU": "European Union",
    "SV": "El Salvador",
}


def get_iso2_code(raw_country: str, existing_code: str = "") -> str:
    """Resolve raw country string to 2-letter ISO 3166-1 Alpha-2 code."""
    if existing_code and len(existing_code.strip()) == 2:
        return existing_code.strip().upper()

    clean_country = raw_country.strip().upper()
    if clean_country in COUNTRY_TO_ISO2:
        return COUNTRY_TO_ISO2[clean_country]

    if len(clean_country) == 2:
        return clean_country

    return ""


def infer_country_from_hostname(hostname: str) -> tuple[str, str]:
    """Infer country name and ISO2 code from hostname domain ending (e.g. .es -> Spain, ES)."""
    clean = hostname.replace("https://", "").replace("http://", "").strip("/").lower()
    if "/" in clean:
        clean = clean.split("/", 1)[0]
    tokens = clean.split(".")
    if not tokens:
        return "", ""

    tld = tokens[-1]
    if tld in CCTLD_TO_ISO2:
        iso2 = CCTLD_TO_ISO2[tld]
        return ISO2_TO_COUNTRY.get(iso2, tld.upper()), iso2

    if len(tokens) >= 2 and tokens[-2] in CCTLD_TO_ISO2:
        iso2 = CCTLD_TO_ISO2[tokens[-2]]
        return ISO2_TO_COUNTRY.get(iso2, tokens[-2].upper()), iso2

    return "", ""


def matches_country(target_filter: str, raw_country: str, existing_code: str = "") -> bool:
    """Check if user filter matches 2-letter ISO country code or raw country name."""
    tf = target_filter.strip().upper()
    server_iso2 = get_iso2_code(raw_country, existing_code)

    # 1. If target filter is a 2-letter code, strictly match server ISO2 code only
    if len(tf) == 2:
        return tf == server_iso2

    # 2. Compare target filter resolved ISO2 vs server ISO2
    filter_iso2 = COUNTRY_TO_ISO2.get(tf)
    if filter_iso2 and server_iso2 and filter_iso2 == server_iso2:
        return True

    # 3. Fallback substring matching on raw country string ONLY for filters longer than 2 characters
    tf_low = target_filter.strip().lower()
    if len(tf_low) > 2 and raw_country and tf_low in raw_country.lower():
        return True

    return False


class ServerInstallation(BaseModel):
    """Represents a CKAN installation with metadata and helper properties."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    description: str | None = None
    hostname: str | None = None
    country: str | None = None
    country_code: str | None = None
    continent: str | None = None
    version: str | None = None
    dataset_count: int | None = None
    organization_count: int | None = None
    group_count: int | None = None
    extensions: list[str] | str | None = None
    contact_email: str | None = None
    about_url: str | None = None
    id: str | None = None
    scheme: str = "https"

    def model_post_init(self, __context: Any) -> None:
        """Derive country_code, clean hostname, and scheme if not provided."""
        if self.about_url and self.about_url.lower().startswith("http://"):
            self.scheme = "http"
        elif self.hostname and self.hostname.lower().startswith("http://"):
            self.scheme = "http"

        if self.hostname:
            clean = self.hostname.replace("https://", "").replace("http://", "").strip("/")
            if "/" in clean:
                clean = clean.split("/", 1)[0]
            self.hostname = clean

        if not self.country_code and self.country:
            self.country_code = get_iso2_code(self.country)

        # Fallback country inference from domain ending if still missing
        if not self.country_code and self.hostname:
            inferred_c, inferred_cc = infer_country_from_hostname(self.hostname)
            if inferred_cc:
                self.country_code = inferred_cc
                if not self.country:
                    self.country = inferred_c

        if not self.id and self.clean_hostname:
            self.id = self.clean_hostname

    @property
    def clean_hostname(self) -> str:
        """Return cleaned hostname without protocol, port or trailing slash."""
        if not self.hostname:
            return ""
        clean = self.hostname.replace("https://", "").replace("http://", "").strip("/")
        if "/" in clean:
            clean = clean.split("/", 1)[0]
        return clean

    @property
    def url(self) -> str:
        """Return URL for the installation."""
        if self.about_url and (self.about_url.startswith("http://") or self.about_url.startswith("https://")):
            return self.about_url.rstrip("/")
        if not self.clean_hostname:
            return ""
        return f"{self.scheme}://{self.clean_hostname}"


CKAN_DIRECTORY_URLS: list[str] = []

DEFAULT_CKAN_INSTALLATIONS: list[dict[str, Any]] = [
    {
        "name": "CKAN Official Demo",
        "hostname": "demo.ckan.org",
        "country": "International",
        "country_code": "XX",
        "version": "2.11",
        "description": "CKAN test instance and demonstration catalog.",
        "about_url": "https://demo.ckan.org",
    },
    {
        "name": "Data.gov",
        "hostname": "data.gov",
        "country": "United States",
        "country_code": "US",
        "version": "2.10",
        "description": "The home of the U.S. Government’s open data.",
        "about_url": "https://data.gov",
    },
    {
        "name": "data.gov.uk",
        "hostname": "data.gov.uk",
        "country": "United Kingdom",
        "country_code": "GB",
        "version": "2.10",
        "description": "Find open data published by UK central government and local authorities.",
        "about_url": "https://data.gov.uk",
    },
    {
        "name": "Open Government Canada",
        "hostname": "open.canada.ca",
        "country": "Canada",
        "country_code": "CA",
        "version": "2.10",
        "description": "Government of Canada open data and open information portal.",
        "about_url": "https://open.canada.ca",
    },
    {
        "name": "Humanitarian Data Exchange (HDX)",
        "hostname": "data.humdata.org",
        "country": "International",
        "country_code": "XX",
        "version": "2.10",
        "description": "Open platform for sharing humanitarian data across organizations.",
        "about_url": "https://data.humdata.org",
    },
    {
        "name": "European Data Portal",
        "hostname": "data.europa.eu",
        "country": "European Union",
        "country_code": "EU",
        "version": "2.10",
        "description": "The official portal for European data.",
        "about_url": "https://data.europa.eu",
    },
    {
        "name": "data.gov.au",
        "hostname": "data.gov.au",
        "country": "Australia",
        "country_code": "AU",
        "version": "2.10",
        "description": "Australian Government open data portal.",
        "about_url": "https://data.gov.au",
    },
    {
        "name": "opendata.swiss",
        "hostname": "opendata.swiss",
        "country": "Switzerland",
        "country_code": "CH",
        "version": "2.10",
        "description": "Swiss portal for open government data.",
        "about_url": "https://opendata.swiss",
    },
    {
        "name": "datos.gob.es",
        "hostname": "datos.gob.es",
        "country": "Spain",
        "country_code": "ES",
        "version": "2.10",
        "description": "National open data portal of Spain.",
        "about_url": "https://datos.gob.es",
    },
    {
        "name": "Open Africa",
        "hostname": "open.africa",
        "country": "South Africa",
        "country_code": "ZA",
        "version": "2.9",
        "description": "The largest independent repository of open data on the African continent.",
        "about_url": "https://open.africa",
    },
]


def fetch_ckan_installations(
    target_server: str | None = None,
    country: str | None = None,
    timeout: float = 10.0,
    urls: list[str] | None = None,
    fallback_unlisted: bool = False,
    use_ecosystem: bool = True,
) -> list[ServerInstallation]:
    """Returns a list of CKAN installations from ecosystem parquet, directory endpoints, or defaults.

    Supports optional filtering by server hostname or country (ISO-2 code or country name).
    If fallback_unlisted is True and a specific target_server is requested but not found in the
    registry, a fallback ServerInstallation is synthesized to support private/unlisted servers.
    """
    raw_list: list[dict[str, Any]] = []

    # 1. Load from local CKAN ecosystem metadata parquet if available
    if use_ecosystem:
        try:
            from dartfx.ckan.ecosystem.manager import EcosystemManager

            mgr = EcosystemManager()
            df = mgr.get_sites_dataframe()
            # Sort by descending timestamp and pick unique sites by URL
            if not df.is_empty():
                unique_df = df.sort("tstamp", descending=True).unique(subset=["url"], keep="first")
                for row in unique_df.to_dicts():
                    url = row.get("url") or ""
                    if not url:
                        continue
                    clean_h = url.replace("https://", "").replace("http://", "").strip("/")
                    if "/" in clean_h:
                        clean_h = clean_h.split("/", 1)[0]
                    raw_list.append(
                        {
                            "name": row.get("name") or clean_h,
                            "hostname": clean_h,
                            "version": row.get("ckan_version"),
                            "dataset_count": row.get("num_datasets"),
                            "group_count": row.get("num_groups"),
                            "organization_count": row.get("num_organizations"),
                            "extensions": row.get("extensions"),
                            "about_url": url,
                        }
                    )
        except Exception:
            pass

    # 2. Query remote directory URLs if provided
    directory_urls = urls or CKAN_DIRECTORY_URLS
    for url in directory_urls:
        if not url:
            continue
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                text = resp.text
                if "application/json" in resp.headers.get("Content-Type", "") or text.strip().startswith(("{", "[")):
                    try:
                        data = resp.json()
                        if isinstance(data, dict) and "installations" in data:
                            raw_list.extend(data["installations"])
                        elif isinstance(data, list):
                            raw_list.extend(data)
                    except Exception:
                        pass
                else:
                    try:
                        reader = csv.DictReader(io.StringIO(text))
                        for r in reader:
                            h_map = {k.strip().lower(): v.strip() for k, v in r.items() if k and v}
                            h = h_map.get("hostname") or h_map.get("url") or ""
                            if h:
                                raw_list.append(
                                    {
                                        "name": h_map.get("name") or h,
                                        "hostname": h,
                                        "country": h_map.get("country") or "",
                                        "country_code": h_map.get("country_code") or "",
                                        "version": h_map.get("version"),
                                    }
                                )
                    except Exception:
                        pass
        except Exception:
            continue

    # 3. Add default installations
    for default_inst in DEFAULT_CKAN_INSTALLATIONS:
        raw_list.append(dict(default_inst))

    clean_target = (
        target_server.replace("https://", "").replace("http://", "").strip("/")
        if target_server and target_server.upper() != "ALL"
        else None
    )
    if clean_target and "/" in clean_target:
        clean_target = clean_target.split("/", 1)[0]

    servers: list[ServerInstallation] = []
    seen_hosts: set[str] = set()

    for item in raw_list:
        if not isinstance(item, dict):
            continue
        try:
            inst = ServerInstallation(**item)
        except Exception:
            continue
        if not inst.clean_hostname:
            continue

        host_key = inst.clean_hostname.lower()
        if host_key in seen_hosts:
            continue

        # Target server filter
        if clean_target and host_key != clean_target.lower():
            continue

        # Country filter
        if country:
            if not matches_country(country, inst.country or "", inst.country_code or ""):
                continue

        seen_hosts.add(host_key)
        servers.append(inst)

    # Fallback if specific target server was not found in registry
    if clean_target and not servers and fallback_unlisted:
        servers.append(
            ServerInstallation(
                hostname=clean_target,
                name=clean_target,
                country="Target Server",
                country_code="-",
            )
        )

    return servers


class SearchParameters(BaseModel):
    """Parameters for CKAN package_search API."""

    model_config = ConfigDict(extra="ignore")

    q: str = Field(default="*", description="Search query string.")
    fq: str | None = Field(default=None, description="Filter query (e.g. 'tags:economy').")
    sort: str | None = Field(default=None, description="Sort parameter (e.g. 'metadata_modified desc').")
    rows: int | None = Field(default=25, ge=1, le=1000, description="Results per page.")
    start: int | None = Field(default=0, ge=0, description="Offset for pagination.")
    per_page: int | None = Field(default=None, ge=1, le=1000, description="Alias for rows.")

    def model_post_init(self, __context: Any) -> None:
        """Map per_page to rows if provided."""
        if self.per_page is not None:
            self.rows = self.per_page


# Custom alias for API exceptions
CKANApiError = CKANAPIRequestError
