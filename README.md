<p><img src="docs/assets/city-icon.png" width="112" height="112" alt="Berlin city icon: simplified Brandenburg Gate in ivory on navy"></p>

# CrimeMaps Berlin: police announcements on a map

[English](README.md) · [Deutsch](README.de.md) · [中文](README.zh-CN.md)

Browse the selected police announcements for Berlin, the places they mention and nearby facilities. Each announcement links to its source. Berlin is the starting point for 14 city projects, each with its own repository and map data.

This is an early open-source version, with plenty still to improve. Coverage, place matching, translations and usability have gaps; information can be missing or wrong. If you are interested, you are welcome to point out problems, suggest source-backed corrections, or help with the code, wording and user experience.

[Planned map address](https://ln6666.github.io/crimemaps-Berlin/)

[Reading the map](#read) · [Sources](#sources) · [Run locally](#run) · [Updates](#updates) · [Privacy and feedback](#privacy) · [Visits by country](#stats) · [Other cities](#cities) · [License](#license)

<a id="status"></a>

## Availability

The new city map is not online yet. This address is reserved for its future release and may not open a map today.

A local map has been prepared for the current selection of reports. Work on the public release is still under way.

Status recorded on 2026-10-03. This describes the current collection, not all crime in the city.

<a id="read"></a>

## Reading the map

Select a month, then open an area, road or place to read the linked announcements. An event may have happened earlier than publication; if its time is not known, it stays unknown.

Hexagons show selected announcements with a location suitable for the totals. Each announcement counts at most once in the selected month and map view. An announcement may describe several events, police activity or earlier events. These totals do not measure all crime, your chance of becoming a victim or how safe one city is compared with another.

A road, transport line or area may show a place mentioned in the source while the exact incident location remains unknown. Reports that name only a district, or cannot be located, remain in the list. No point is invented to fill the gap.

A darker place symbol marks a link to the type of place mentioned in an announcement. It does not establish that an offence happened at that business. Read the linked announcement to understand why the place is shown.

Where available, Chinese and English translations help readers understand the German police text. The original wording and links remain available. Translations may contain errors and do not add an address, time or precise location that the source did not give.

Software collects the sources and prepares the map. AI can assist with reading and classification; its suggestions need checking against the source.

Sources, categories, location descriptions and the way the map displays them are checked before announcements appear in a release. We have not measured how often each AI tool was correct across all 14 cities. Errors and missing information can remain.

A label such as ‘possible hate crime’ is an AI-assisted lead based on explicit evidence of bias in the narrative, not a finding by the police. Identity, origin or neighbourhood alone is not evidence of motive.

<a id="sources"></a>

## Sources and coverage

Report source: [Polizei Berlin](https://www.berlin.de/polizei/polizeimeldungen/).

Police press announcements are a selection of public reports. The absence of an announcement, an excluded article or an unknown location does not mean that no event occurred there. A police authority's service area may extend beyond the city; records must be checked against the city boundary.

Place information and mapped outlines use [OpenStreetMap](https://www.openstreetmap.org/copyright), including [Geofabrik extracts](https://download.geofabrik.de/europe/germany.html). Source links, collection dates and location limits are retained. The city illustration in this README identifies the project; it does not mark an event.

<a id="run"></a>

## Run locally

Use Node.js 22 and npm for the map interface. Python 3.12 and [uv](https://docs.astral.sh/uv/) are needed for the source-processing tools.

```sh
git clone https://github.com/LN6666/crimemaps-Berlin.git
cd crimemaps-Berlin
npm --prefix web ci
VITE_CRIMEMAPS_CITY=berlin npm --prefix web run dev
```

Open http://127.0.0.1:5173. The repository contains code; reviewed map data is delivered separately and is not committed to Git. Without a compatible city data bundle, the interface cannot show that city's records. Import the checked bundle into `web/public/safety/` using the city migration instructions; do not copy source databases or review archives there.

For backend development, install the locked dependencies and run the existing local checks:

```sh
uv sync --locked
uv run pytest test_suite/safety
```

The production frontend build is `VITE_CRIMEMAPS_CITY=berlin npm --prefix web run build`. Building code does not publish a website or prove that map data is complete.

<a id="contribute"></a>

## Contribute

[Report a software issue](https://github.com/LN6666/crimemaps-Berlin/issues) · [Propose a change](https://github.com/LN6666/crimemaps-Berlin/pulls) · [Contribution guide](docs/CONTRIBUTING.en.md). GitHub issues and pull requests are public when the repository is public. A private repository requires access; these links do not open a private feedback form.

Use a focused pull request for code or wording changes. See [the contribution guide](docs/CONTRIBUTING.en.md). A software issue should include the browser, a short reproduction and a public source link where relevant. Leave personal information, full police texts, databases, review packages and credentials out of public issues.

<a id="updates"></a>

## Updates and reliability

New announcements are checked against their sources and location descriptions before appearing on the map. Collection and checking take time; this is not a live feed. If an update fails, the previous usable map stays available. Collection dates and visible limits explain what that version includes.

Follow [repository releases](https://github.com/LN6666/crimemaps-Berlin/releases) and [code checks](https://github.com/LN6666/crimemaps-Berlin/actions). Older development notes are retained in `docs/`; the current city status here takes precedence over historical deployment descriptions.

<a id="privacy"></a>

## Privacy, corrections and security

Visit statistics and private correction feedback are not connected to a live service yet. No private feedback form is claimed to be available. Public GitHub issues are visible to others. Once a private correction route is enabled, the map will state its destination and privacy terms; unreviewed feedback will not be published automatically. See [feedback and unknown locations](docs/FEEDBACK.md).

Map tiles and external links use third-party providers. When you load those services, they may receive ordinary connection information such as an IP address. See the map's provider attribution and privacy notice before using an external service.

For security issues, see [SECURITY.md](SECURITY.md). If the repository shows ‘Report a vulnerability’, use that private route. Do not post credentials or sensitive details in a public issue.

<a id="stats"></a>

## Visits by country

Live visit collection is not connected. No country totals are shown until the service returns real aggregate data. Opening this README or its chart does not add a map page view.

<a id="cities"></a>

## The 14 city projects

Berlin is the default starting point. All 14 city repositories are public; the links below open their code and project pages. The new maps are still awaiting publication.

| City | Repository |
| --- | --- |
| Berlin | [crimemaps-Berlin](https://github.com/LN6666/crimemaps-Berlin) |
| Hamburg | [crimemaps-Hamburg](https://github.com/LN6666/crimemaps-Hamburg) |
| Munich | [crimemaps-Munich](https://github.com/LN6666/crimemaps-Munich) |
| Cologne | [crimemaps-Cologne](https://github.com/LN6666/crimemaps-Cologne) |
| Frankfurt am Main | [crimemaps-Frankfurt](https://github.com/LN6666/crimemaps-Frankfurt) |
| Düsseldorf | [crimemaps-Dusseldorf](https://github.com/LN6666/crimemaps-Dusseldorf) |
| Stuttgart | [crimemaps-Stuttgart](https://github.com/LN6666/crimemaps-Stuttgart) |
| Leipzig | [crimemaps-Leipzig](https://github.com/LN6666/crimemaps-Leipzig) |
| Dortmund | [crimemaps-Dortmund](https://github.com/LN6666/crimemaps-Dortmund) |
| Bremen | [crimemaps-Bremen](https://github.com/LN6666/crimemaps-Bremen) |
| Essen | [crimemaps-Essen](https://github.com/LN6666/crimemaps-Essen) |
| Dresden | [crimemaps-Dresden](https://github.com/LN6666/crimemaps-Dresden) |
| Hanover | [crimemaps-Hannover](https://github.com/LN6666/crimemaps-Hannover) |
| Nuremberg | [crimemaps-Nuremberg](https://github.com/LN6666/crimemaps-Nuremberg) |

<a id="license"></a>

## License and disclaimer

Project code is licensed under [Apache-2.0](LICENSE). OpenStreetMap data has its own [ODbL and attribution terms](https://www.openstreetmap.org/copyright). Police publications and other source material retain their respective terms; the code license does not grant a blanket right to redistribute them.

CrimeMaps is an independent project, not an official police service. Read the linked police text before drawing conclusions about a record. The map is not an emergency service or a measure of personal safety. The software is provided under the terms in LICENSE.
