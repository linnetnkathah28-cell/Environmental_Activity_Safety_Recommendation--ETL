# Environmental Activity & Safety Recommendation Dashboard
### ETL Pipeline — Week 3 Assignment

A fully reproducible Python ETL pipeline that extracts live weather and air
quality data from the Open-Meteo API, transforms and validates it, loads the
results into a PostgreSQL database, and exports flat CSV files ready for Plotly Dash.

---

## Project Structure

```
project-root/
│
├── etl_pipeline.py          # Main ETL script (submit this)
├── .env                     # Your local credentials (never commit)
├── .env.sample              # Template — copy to .env and fill in values
├── requirements.txt         # Python dependencies
├── .gitignore
├── README.md
│
└── data/                    # Reference files (ship with project)
    ├── weather_codes.xlsx
    ├── activities.xlsx
    ├── safety_guidance.xlsx
    │
    └── (generated on run)
        ├── analytics_forecast.csv
        └── analytics_recommendations.csv
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10 or higher |
| PostgreSQL | 14 or higher (local or Supabase) |

---

## Setup Instructions

### 1. Clone the repository

```bash
git clone https://github.com/your-username/your-repo-name.git
cd your-repo-name
```

### 2. Create and activate a virtual environment

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

# Windows (Command Prompt)
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.sample .env
```

Open `.env` in any text editor and fill in your database credentials:

```
DB_HOST=localhost          # or your Supabase host
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your_password
RESET_TABLES=false
```

> **Supabase users:** your host will look like
> `db.xxxxxxxxxxxx.supabase.co`. Find it under
> *Project Settings → Database → Connection string*.

### 5. Add the reference data files

Place the following files in the `data/` directory (create it if needed):

- `data/weather_codes.xlsx`
- `data/activities.xlsx`
- `data/safety_guidance.xlsx`

These are the dimension/lookup tables for the pipeline. Column requirements
are documented in the Database Schema section below.

---

## Running the Pipeline

```bash
python etl_pipeline.py
```

The script runs all stages automatically from start to finish:

1. Connects to the database and creates tables if they do not exist
2. Pulls a 7-day daily weather forecast from Open-Meteo (Louisville, KY)
3. Pulls a 7-day hourly air quality forecast, aggregated to daily
4. Loads reference dimension data from the XLSX files
5. Cleans, normalises, and enriches all datasets
6. Runs data quality and validation checks
7. Loads new rows into PostgreSQL (incremental — skips dates already loaded)
8. Exports `data/analytics_forecast.csv` and `data/analytics_recommendations.csv`

Progress and validation results are printed to the console and written to
`etl_pipeline.log` in the project root.

### Reset / full reload

To drop all tables and reload from scratch (useful during development):

```bash
# In .env, set:
RESET_TABLES=true
```

Then re-run the script. Change back to `false` after the reset.

---

## Pipeline Stages

| Stage | Description |
|---|---|
| **Extract** | Open-Meteo weather & air quality APIs + XLSX reference files |
| **Transform** | Type casting, deduplication, Celsius → Fahrenheit conversion, daily aggregation of hourly AQI data |
| **Validate** | Row counts, null checks, range validation, referential integrity, duplicate detection |
| **Load** | Incremental PostgreSQL insert via SQLAlchemy (skips already-loaded dates) |
| **Export** | Flat denormalized CSVs for Power BI / Plotly Dash |

---

## Database Schema

Seven tables are created in the `public` schema:

```
locations           — city/coordinates dimension
weather_codes       — WMO weather code lookup
activities          — recommended activity types
safety_guidance     — safety guidance rules
weather_forecast    — daily weather forecast (fact)
air_quality_forecast — daily AQI forecast (fact)
recommendations     — rule-based activity/safety recommendations (fact)
```

See the Database Schema document for full column definitions.

---

## Analytics Outputs

After each run, two flat CSV files are written to `data/`:

- **`analytics_forecast.csv`** — weather and air quality joined by date, ready
  for time-series charts or tabular reports.
- **`analytics_recommendations.csv`** — recommendations enriched with activity
  names, guidance labels, and key weather metrics, ready for dashboard cards
  or filtered views.

---

## Logging

All pipeline activity is logged to:

- **Console** — visible during execution
- **`etl_pipeline.log`** — appended on every run, useful for audit trails

Each log entry includes a timestamp, log level, and descriptive message.
Validation results (PASS / WARN / FAIL) are clearly marked.

---

## Incremental Loading

The pipeline checks which `forecast_date` values already exist in each fact
table before inserting. Re-running the script on the same day will skip rows
that were already loaded. This prevents duplicates without requiring a full
table reset.

> Dimension tables (weather codes, activities, safety guidance) are loaded
> with a standard append. Set `RESET_TABLES=true` if you need to replace
> dimension data.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `could not connect to server` | Check `DB_HOST`, `DB_PORT`, and that PostgreSQL is running |
| `password authentication failed` | Verify `DB_PASSWORD` in `.env` |
| `FileNotFoundError: data/weather_codes.xlsx` | Ensure all three XLSX reference files are in `data/` |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` inside your virtual environment |
| Tables already exist error | Set `RESET_TABLES=true` in `.env` for a clean reload |

---

## License

For academic use — Week 3 ETL Pipeline Assignment.
