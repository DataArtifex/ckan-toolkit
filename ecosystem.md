# CKAn ECOSYSTEM

The https://ecosystem.ckan.org CKAN server is a special official catalog that compiles other CKAN servers.

It exposes two datasets:
- ckan-sites-metadata: a time series of CKAN sites metadata
- ckan-extensions-metadata: a time series of CKAN extensions metadata

See more details and data dicttionnaries below

I would like to have a dedicate dartfx.ckan.ecosystem module to sync these datasets in this Python package and make then searchable/queryable.

Given that this gets updated on a weeky basis, live querying is not necessary. I would like to have a local copy of the data in parquet format (for size and speed).

We can then load on polars for querying.

We should have a sync command that checks if our version is outdated and updates it if necessary.
It should be possible to force a sync.

Could you create pydnatic classes and methods to handle all this.

## ckan-sites-metadata

This dataset is a time series of CKAN sites metadata.

Column	Type	Label	Description
tstamp	text	tstamp
name	text	name
url	text	url
num_datasets	numeric	num_datasets
num_groups	numeric	num_groups
num_organizations	numeric	num_organizations
ckan_version	text	ckan_version
extensions	text	extensions

# ckan-extensions-metadata:

Column	Type	Label	Description
tstamp	text	tstamp
repository_name	text	repository_name
url	text	url
forks_count	numeric	forks_count
total_releases	numeric	total_releases
latest_release	text	latest_release
release_date	text	release_date
stars	numeric	stars
open_issues	numeric	open_issues
contributors_count	numeric	contributors_count
discussions	text	discussions
