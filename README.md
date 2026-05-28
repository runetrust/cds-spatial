# Geographic Attention in Danish News Coverage
### Mapping the Muhammad  Crisis (2005–2006)

This project traces how the Danish newspaper *Politiken* distributed its geographic attention before, during, and after the Muhammad crisis. Articles are scraped, geoparsed via NER and the OpenCage geocoding API, and then visualised as KDE density surfaces and choropleth maps across three periods: pre-crisis, crisis peak, and post-crisis.

> **Data note:** Raw Politiken articles cannot be redistributed. However, if your institution holds an agreement with [Copydan Text & Node](https://www.copydan.dk/licenser/text-og-node), you are permitted to use the data for educational purposes. See the scraper instructions below.

---

## Project Structure

```
cds-spatial/
├── src/
│   ├── politiken_scraper_new.py   # Step 1 – scrape articles
│   ├── NER.py                     # Step 2 – extract place names
│   ├── preprocessing_NER.py       # Step 3 – filter noisy NER output
│   ├── Geoparsing.py              # Step 4 – geocode place names
│   ├── reformat_json.py           # Step 5 – flatten to CSV
│   ├── kde_w_centroids.Rmd        # Step 6a – KDE maps + centroid analysis
│   └── Choropleth.Rmd             # Step 6b – choropleth maps
├── in/                            # Intermediate files will be saved here (e.g. scraper output)
├── out/                           # Outputs: CSVs, rasters, PNGs
│   ├── place_mentions.csv
│   ├── geocache.json
│   ├── kde/                       # KDE related outputs (plots as PNG and SpatialRasters)
│   └── choropleth/                # Chropleth related outputs (plots as PNG)
├── requirements.txt
```

---

## Getting Started

### Prerequisites

- Python ≥ 3.10
- R ≥ 4.2 with the following packages: `tidyverse`, `sf`, `terra`, `rnaturalearth`, `rnaturalearthdata`, `patchwork`
- A Politiken subscription (institutional or personal)
- A free [OpenCage geocoding API key](https://opencagedata.com/) (2,500 requests/day on the free tier)

### Installation

```bash
git clone https://github.com/runetrust/cds-spatial.git
cd cds-spatial
```

### Dependencies
Install requiret packages for the entire pipline by running:

```bash
pip install -r requirements.txt
```

---

## Pipeline

Run the steps below in order from inside the `src/` directory to scrape all articles in the period 01/01/2005 - 31/12/2006.
CLI Also accepts a new url via the --url parameter (Remember to wrap it with "")

### Step 1 - Scrape articles

```bash
python politiken_scraper_new.py \
  --email YOUR_POLITIKEN_EMAIL \
  --password YOUR_POLITIKEN_PASSWORD \
```

Key options:

| Flag | Default | Description |
|---|---|---|
| `--email` | required | Politiken account e-mail |
| `--password` | required | Politiken account password |
| `--url` | 2005–2006 search | Search URL to scrape. Wrap in `""` |
| `--max-pages` | `None` (all) | Limit number of result pages |
| `--delay` | `0.1` | Seconds between requests |
| `--no-full-articles` | off | Collect stubs only (no body text) |
| `--output` | `politiken_results.json` | Output filename inside `out/` |

The scraper writes checkpoints every 200 articles so a crash does not lose progress. The final file is saved to `out/politiken_results.json` (or --output argument).


### Step 2 - Named Entity Recognition

```bash
python NER.py
```

Runs the [`saattrupdan/nbailab-base-ner-scandi`](https://huggingface.co/saattrupdan/nbailab-base-ner-scandi) model (Scandinavian NER) over each article and extracts location entities (`LOC`, `GPE`, `LOCATION`). Output is written to `in/politiken_NER.json`.

The model is downloaded automatically from HuggingFace on first run (~400 MB).

### Step 3 - Preprocessing / filtering

```bash
python preprocessing_NER.py
```

Filters out implausible place names (too short, lowercase, digits, long phrases) and drops any place that appears fewer than `MIN_FREQUENCY` times across the corpus (default: 2). Output: `in/politiken_NER_preprocessed.json`.

### Step 4 - Geocoding

```bash
python Geoparsing.py
```

Looks up each unique place name via the OpenCage API and caches results in `out/geocache.json` so the same lookup is never run twice.

> **Manual change required:** You must insert your OpenCage API key in `Geoparsing.py` at line ~31:
> ```python
> geocoder = OpenCageGeocode("")  # paste your key here
> ```
> Get a free key at [opencagedata.com](https://opencagedata.com/). The free tier allows 2,500 requests per day. If you have more unique place names than that, the commented-out line `#new_places = new_places[:2499]` below line 31 can be uncommented to slice the batch and avoid hitting the limit. Then re-run after the daily reset.

Output: `out/articles_geocoded.json`.

### Step 5 - Reformat to CSV

```bash
python reformat_json.py
```

Flattens the geocoded articles into a tidy CSV where each row is one place mention in one article. Output: `out/place_mentions.csv` with columns `place`, `date`, `lat`, `lon`, `country`.

### Step 6 - Visualisation (R)

Open and run the two R Markdown files in `src/`. Both read from `out/place_mentions.csv` and write all figures to `out/`.

**`kde_w_centroids.Rmd`** - Kernel density estimation surfaces with weighted centroids per period. The `CENTROID_METHOD` parameter at the top of the file controls whether centroids are weighted by mention frequency (`"weighted"`, default) or treat each mention equally (`"mean"`).

**`Choropleth.Rmd`** - Country-level choropleths of mention share, normalised within each period, with difference maps showing which countries gained or lost attention across transitions.

Both scripts share the same period parameters at the top - if the date windows are changed in one, update the other to match.

---

## Output Examples

The `out/` directory already contains pre-computed outputs from the original run:

- `out/kde/` - KDE density rasters (`.tif`) and PNG maps with centroid trajectories
- `out/choropleth/` - Choropleth PNGs for each period and the two difference maps
- `out/place_mentions.csv` - Full place-mention dataset
- `out/geocache.json` - Cached geocoding results

---

## Restrictions of use

For educational use under institutional Copydan Text & Node agreements. Raw article content may not be redistributed.


## Acknowledgements

- **[saattrupdan/nbailab-base-ner-scandi](https://huggingface.co/saattrupdan/nbailab-base-ner-scandi)**: Scandinavian NER model used for place name extraction, developed by the NbAiLab team.
- **[OpenCage Geocoding API](https://opencagedata.com/)**: Used for resolving place names to coordinates and country metadata.
- **[Natural Earth](https://www.naturalearthdata.com/)**: Free vector map data used for world polygons in all visualisations, accessed via the [`rnaturalearth`](https://docs.ropensci.org/rnaturalearth/) R package.
- **[Copydan Text & Node](https://www.copydan.dk/licenser/text-og-node)** The licensing framework that permits institutional educational use of Danish news content.
