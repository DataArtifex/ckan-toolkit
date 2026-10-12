# Server Compatibility & API Constraints

When interacting with worldwide CKAN servers, applications must account for varying server architectures, extensions, and security policies.

## 1. Apex Domain vs. Catalog Separation

Large portal deployments frequently host CMS applications (WordPress, Drupal, Cloud.gov Pages) on the apex domain, while the CKAN catalog engine resides on a dedicated subdomain or path:

- **Apex Domain**: e.g., `https://data.gov`, `https://open.canada.ca`
- **Catalog Domain**: e.g., `https://catalog.data.gov`, `https://open.canada.ca/data/en/`

Reverse proxies fronting apex domains typically allow only `GET` and `HEAD` requests (`access-control-allow-methods: GET, HEAD`). Because standard CKAN clients (including `ckanapi.RemoteCKAN`) send Action API requests using HTTP `POST`, submitting action requests to the apex domain results in an immediate **`HTTP 405 Method Not Allowed`**.

`dartfx-ckan` resolves installation metadata from curated ecosystem directories and matches clean hostnames.

## 2. Data.gov Restrictions & Gateway Migration

The US Federal Data.gov portal enforces specific API access policies:

- **Legacy Action API Lockdown**: Direct unauthenticated requests to standard CKAN Action API endpoints on `catalog.data.gov` (`/api/3/action/package_search`, `/api/3/action/status_show`) are rejected with policy restriction errors (`"Request not allowed by policy"`).
- **GSA API Gateway (v4)**: Data.gov has migrated all official programmatic catalog access to the managed GSA API Gateway at `https://api.gsa.gov/technology/datagov/v4/`. Access requires an API key issued by [api.data.gov](https://api.data.gov) (passed via the `x-api-key` header). This gateway uses custom REST schemas rather than the standard CKAN Action API.
- **Federal Data Inventories**: Individual US federal agencies publish their public DCAT-US 1.1 inventories at `https://<agency>.gov/data.json`.
- **Toolkit Resilience**: The `dartfx-ckan info` command detects `status_show` restrictions and falls back to cached ecosystem directory records.

## 3. `status_show` Disablement & Security Hardening

In production environments, security administrators frequently disable or firewall the `status_show` action to prevent version fingerprinting and extension reconnaissance.

- The `CKANServer.get_info_version()` and `CKANServer.get_info_server()` methods catch `status_show` exceptions (HTTP 405, 403, 404) and fall back to `ServerInstallation` metadata from the ecosystem registry.
- The CLI outputs a notice indicating that live status probing is restricted while displaying available catalog details.

## 4. Metadata Standards: Native vs. Extensions

Metadata formats supported by CKAN servers depend on whether extensions are deployed:

| Format | Identifier | Source | Requirements |
| :--- | :--- | :--- | :--- |
| **CKAN Package JSON** | `json` | Core Action API (`package_show`) | Native on all standard CKAN instances |
| **Resource Manifest** | `resources` | Core Action API (`package_show`) | Native on all standard CKAN instances |
| **DCAT RDF/XML** | `dcat` | `/dataset/{id}.xml` | Requires [`ckanext-dcat`](https://github.com/ckan/ckanext-dcat) |
| **DCAT JSON-LD** | `jsonld` | `/dataset/{id}.jsonld` | Requires [`ckanext-dcat`](https://github.com/ckan/ckanext-dcat) |
| **DCAT Turtle** | `ttl` | `/dataset/{id}.ttl` | Requires [`ckanext-dcat`](https://github.com/ckan/ckanext-dcat) |
| **OGC CSW & ISO 19139** | `csw` | `/csw` | Requires [`ckanext-spatial`](https://github.com/ckan/ckanext-spatial) |
| **OAI-PMH (Dublin Core)** | `oai` | `/oai` | Requires [`ckanext-oaipmh`](https://github.com/geosolutions-it/ckanext-oaipmh) |
| **DCAT-US 1.1** | `datajson` | `/data.json` | Requires [`ckanext-datajson`](https://github.com/GSA/ckanext-datajson) |

## 5. Web Application Firewalls (WAF) & Rate Limiting

Public CKAN deployments frequently sit behind Cloudflare, AWS CloudFront, or Imperva WAFs:

- Rapid crawling can trigger `HTTP 429 Too Many Requests` or `HTTP 403 Forbidden` (bot mitigation / CAPTCHA).
- Use the `--workers` option (default: 4) to control concurrency during harvest runs.
- The harvest error classification engine categorizes WAF blocks, rate limits, and parsing errors into structured manifest records.

## 6. Authentication Requirements

When servers return `HTTP 401 Unauthorized`, an API key is required. The toolkit resolves credentials via a 6-tier hierarchy:

1. Explicit CLI argument (`--api-token` / `-k`)
2. Server directory token file (`<repo_root>/<host>/.api_token`)
3. Central token mapping (`<repo_root>/.ckan_tokens.json`)
4. Working directory tokens (`.ckan_tokens.json` or `.tokens.json`)
5. Server-specific environment variable (`CKAN_API_TOKEN_<HOST>`)
6. Global environment variable (`DARTFX_CKAN_API_KEY`, `CKAN_API_KEY`, `CKAN_API_TOKEN`)
