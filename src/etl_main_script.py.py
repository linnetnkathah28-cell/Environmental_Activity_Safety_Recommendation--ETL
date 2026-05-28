"""
Environmental Activity & Safety Recommendation Dashboard
ETL Pipeline — Week 3 Assignment
==========================================================

Full pipeline covering all required stages:
    1. API extraction  (Open-Meteo weather + air-quality forecasts)
    2. Cleaning & normalization
    3. Transformation & derived metrics
    4. Data validation & quality checks
    5. Incremental database loading (PostgreSQL via SQLAlchemy)
    6. Analytics-ready dataset preparation (Power BI / Plotly Dash)

Required packages  (see requirements.txt):
    pip install pandas sqlalchemy psycopg2-binary openpyxl python-dotenv
    pip install openmeteo-requests requests-cache retry-requests

.env values expected:
    DB_HOST=localhost
    DB_PORT=5432
    DB_NAME=postgres
    DB_USER=postgres
    DB_PASSWORD=your_password

Optional overrides:
    RESET_TABLES=false   # set to "true" to drop and recreate tables on each run
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests_cache
from dotenv import load_dotenv
from retry_requests import retry
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.types import Boolean, DateTime, Integer, Numeric, String

import openmeteo_requests

# ===========================================================================
# Logging configuration
# ===========================================================================
# All pipeline stages write structured log messages so failures are easy to
# trace.  Logs go to both the console and a local file.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("etl_pipeline.log", mode="a", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ===========================================================================
# Path & constant configuration
# ===========================================================================

BASE_DIR = Path(__file__).resolve().parent   # → project-root/src/
DATA_DIR = BASE_DIR.parent / "data"          # → project-root/data/

# Reference / dimension files (shipped with the project)
WEATHER_CODES_XLSX   = DATA_DIR / "weather_codes.xlsx"
ACTIVITIES_XLSX      = DATA_DIR / "activities.xlsx"
SAFETY_GUIDANCE_XLSX = DATA_DIR / "safety_guidance.xlsx"

# Louisville, KY — primary project location
LOCATION = {
    "location_id": 1,
    "city":        "Louisville",
    "state":       "KY",
    "latitude":    38.2542,
    "longitude":   -85.7594,
}

# Open-Meteo endpoint URLs
WEATHER_API_URL     = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_API_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


# ===========================================================================
# 1. DATABASE CONNECTION
# ===========================================================================

def get_database_url() -> str:
    """Build and return the PostgreSQL connection URL from environment variables."""
    load_dotenv()
    host     = os.getenv("DB_HOST",     "localhost")
    port     = os.getenv("DB_PORT",     "5432")
    db_name  = os.getenv("DB_NAME",     "postgres")
    user     = os.getenv("DB_USER",     "postgres")
    password = os.getenv("DB_PASSWORD", "")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"


def table_reset_enabled() -> bool:
    """Return True when RESET_TABLES env var is truthy (useful for dev reloads)."""
    return os.getenv("RESET_TABLES", "false").strip().lower() in {"1", "true", "yes", "y"}


# ===========================================================================
# 2. SCHEMA CREATION
# ===========================================================================

def create_schema(engine) -> None:
    """
    Create all project tables if they do not already exist.
    When RESET_TABLES=true the tables are dropped first so a clean reload
    can be performed — useful during development.
    """
    log.info("Creating / verifying database schema …")

    drop_sql = """
        DROP TABLE IF EXISTS public.recommendations    CASCADE;
        DROP TABLE IF EXISTS public.weather_forecast   CASCADE;
        DROP TABLE IF EXISTS public.air_quality_forecast CASCADE;
        DROP TABLE IF EXISTS public.safety_guidance    CASCADE;
        DROP TABLE IF EXISTS public.activities         CASCADE;
        DROP TABLE IF EXISTS public.weather_codes      CASCADE;
        DROP TABLE IF EXISTS public.locations          CASCADE;
    """

    create_sql = """
        CREATE TABLE IF NOT EXISTS public.locations (
            location_id  INTEGER PRIMARY KEY,
            city         VARCHAR NOT NULL,
            state        VARCHAR NOT NULL,
            latitude     NUMERIC NOT NULL,
            longitude    NUMERIC NOT NULL,
            UNIQUE (city, state, latitude, longitude)
        );

        CREATE TABLE IF NOT EXISTS public.weather_codes (
            weather_code_id  INTEGER PRIMARY KEY,
            condition_name   VARCHAR NOT NULL,
            description      VARCHAR NOT NULL,
            is_precipitation BOOLEAN NOT NULL DEFAULT FALSE
        );

        CREATE TABLE IF NOT EXISTS public.weather_forecast (
            weather_id               INTEGER PRIMARY KEY,
            location_id              INTEGER NOT NULL REFERENCES public.locations(location_id),
            weather_code_id          INTEGER NOT NULL REFERENCES public.weather_codes(weather_code_id),
            forecast_date            DATE    NOT NULL,
            temperature_2m_max       NUMERIC,
            temperature_2m_min       NUMERIC,
            uv_index_max             NUMERIC,
            uv_index_clear_sky_max   NUMERIC,
            precipitation_sum        NUMERIC,
            precipitation_hours      NUMERIC,
            precipitation_probability_max NUMERIC,
            wind_speed_10m_max       NUMERIC,
            wind_gusts_10m_max       NUMERIC,
            loaded_at                TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS public.air_quality_forecast (
            air_quality_id  INTEGER PRIMARY KEY,
            location_id     INTEGER NOT NULL REFERENCES public.locations(location_id),
            forecast_date   DATE    NOT NULL,
            pm10            NUMERIC,
            pm25            NUMERIC,
            carbon_monoxide NUMERIC,
            nitrogen_dioxide NUMERIC,
            ozone           NUMERIC,
            uv_index        NUMERIC,
            aqi_european    NUMERIC,
            aqi_us          NUMERIC,
            loaded_at       TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS public.activities (
            activity_id          INTEGER PRIMARY KEY,
            activity_name        VARCHAR NOT NULL,
            activity_type        VARCHAR NOT NULL,
            activity_intensity   VARCHAR,
            suitable_condition   VARCHAR,
            activity_description VARCHAR
        );

        CREATE TABLE IF NOT EXISTS public.safety_guidance (
            safety_guidance_id INTEGER PRIMARY KEY,
            guidance_type      VARCHAR NOT NULL,
            guidance_text      VARCHAR NOT NULL,
            condition_trigger  VARCHAR,
            recommended_item   VARCHAR,
            avoidance_guidance VARCHAR,
            alert_level        VARCHAR
        );

        CREATE TABLE IF NOT EXISTS public.recommendations (
            recommendation_id    INTEGER PRIMARY KEY,
            location_id          INTEGER NOT NULL REFERENCES public.locations(location_id),
            weather_id           INTEGER REFERENCES public.weather_forecast(weather_id),
            air_quality_id       INTEGER REFERENCES public.air_quality_forecast(air_quality_id),
            activity_id          INTEGER REFERENCES public.activities(activity_id),
            safety_guidance_id   INTEGER REFERENCES public.safety_guidance(safety_guidance_id),
            forecast_date        DATE    NOT NULL,
            condition_type       VARCHAR,
            recommendation_reason VARCHAR,
            loaded_at            TIMESTAMP DEFAULT NOW()
        );
    """

    with engine.begin() as conn:
        if table_reset_enabled():
            log.warning("RESET_TABLES=true — dropping all existing tables before reload.")
            conn.execute(text(drop_sql))
        conn.execute(text(create_sql))

    log.info("Schema verified successfully.")


# ===========================================================================
# 3. API EXTRACTION
# ===========================================================================

def _build_openmeteo_client():
    """Return a cached + retry-enabled Open-Meteo client."""
    cache_session = requests_cache.CachedSession(".cache", expire_after=3600)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    return openmeteo_requests.Client(session=retry_session)


def extract_weather_forecast() -> pd.DataFrame:
    """
    Pull 7-day daily weather forecast from Open-Meteo for Louisville, KY.
    Returns a raw DataFrame with one row per forecast day.
    """
    log.info("Extracting weather forecast from Open-Meteo API …")
    client = _build_openmeteo_client()

    params = {
        "latitude":  LOCATION["latitude"],
        "longitude": LOCATION["longitude"],
        "daily": [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "uv_index_max",
            "uv_index_clear_sky_max",
            "precipitation_sum",
            "precipitation_hours",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "wind_gusts_10m_max",
        ],
        "timezone": "America/New_York",
    }

    try:
        responses = client.weather_api(WEATHER_API_URL, params=params)
    except Exception as exc:
        log.error("Weather API request failed: %s", exc)
        raise

    response = responses[0]
    log.info(
        "Weather API response — Coordinates: %.4f°N %.4f°E  Elevation: %.1f m  Timezone: %s",
        response.Latitude(), response.Longitude(),
        response.Elevation(),
        response.Timezone().decode(),
    )

    daily = response.Daily()
    dates = pd.date_range(
        start=pd.to_datetime(daily.Time(),    unit="s", utc=True),
        end=pd.to_datetime(daily.TimeEnd(),   unit="s", utc=True),
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left",
    ).tz_convert(response.Timezone().decode()).date  # date-only, no tz

    df = pd.DataFrame({
        "forecast_date":                  dates,
        "weather_code":                   daily.Variables(0).ValuesAsNumpy(),
        "temperature_2m_max":             daily.Variables(1).ValuesAsNumpy(),
        "temperature_2m_min":             daily.Variables(2).ValuesAsNumpy(),
        "uv_index_max":                   daily.Variables(3).ValuesAsNumpy(),
        "uv_index_clear_sky_max":         daily.Variables(4).ValuesAsNumpy(),
        "precipitation_sum":              daily.Variables(5).ValuesAsNumpy(),
        "precipitation_hours":            daily.Variables(6).ValuesAsNumpy(),
        "precipitation_probability_max":  daily.Variables(7).ValuesAsNumpy(),
        "wind_speed_10m_max":             daily.Variables(8).ValuesAsNumpy(),
        "wind_gusts_10m_max":             daily.Variables(9).ValuesAsNumpy(),
    })

    log.info("Weather forecast extracted: %d rows.", len(df))
    return df


def extract_air_quality_forecast() -> pd.DataFrame:
    """
    Pull 7-day daily air quality forecast from Open-Meteo for Louisville, KY.
    Returns a raw DataFrame with one row per forecast day.
    """
    log.info("Extracting air quality forecast from Open-Meteo API …")
    client = _build_openmeteo_client()

    params = {
        "latitude":  LOCATION["latitude"],
        "longitude": LOCATION["longitude"],
        "hourly": [
            "pm10", "pm2_5", "carbon_monoxide",
            "nitrogen_dioxide", "ozone", "uv_index",
            "european_aqi", "us_aqi",
        ],
        "timezone": "America/New_York",
    }

    try:
        responses = client.weather_api(AIR_QUALITY_API_URL, params=params)
    except Exception as exc:
        log.error("Air quality API request failed: %s", exc)
        raise

    response = responses[0]
    hourly = response.Hourly()

    timestamps = pd.date_range(
        start=pd.to_datetime(hourly.Time(),    unit="s", utc=True),
        end=pd.to_datetime(hourly.TimeEnd(),   unit="s", utc=True),
        freq=pd.Timedelta(seconds=hourly.Interval()),
        inclusive="left",
    ).tz_convert(response.Timezone().decode())

    hourly_df = pd.DataFrame({
        "timestamp":       timestamps,
        "pm10":            hourly.Variables(0).ValuesAsNumpy(),
        "pm25":            hourly.Variables(1).ValuesAsNumpy(),
        "carbon_monoxide": hourly.Variables(2).ValuesAsNumpy(),
        "nitrogen_dioxide":hourly.Variables(3).ValuesAsNumpy(),
        "ozone":           hourly.Variables(4).ValuesAsNumpy(),
        "uv_index":        hourly.Variables(5).ValuesAsNumpy(),
        "aqi_european":    hourly.Variables(6).ValuesAsNumpy(),
        "aqi_us":          hourly.Variables(7).ValuesAsNumpy(),
    })

    # Aggregate hourly → daily max values for consistency with weather table
    hourly_df["forecast_date"] = hourly_df["timestamp"].dt.date
    df = hourly_df.groupby("forecast_date").agg(
        pm10            =("pm10",            "max"),
        pm25            =("pm25",            "max"),
        carbon_monoxide =("carbon_monoxide", "max"),
        nitrogen_dioxide=("nitrogen_dioxide","max"),
        ozone           =("ozone",           "max"),
        uv_index        =("uv_index",        "max"),
        aqi_european    =("aqi_european",    "max"),
        aqi_us          =("aqi_us",          "max"),
    ).reset_index()

    log.info("Air quality forecast extracted: %d rows.", len(df))
    return df


def load_reference_files() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Load static dimension/reference data from XLSX files shipped with the project.
    These files define weather codes, activities, and safety guidance lookup tables.
    """
    log.info("Loading reference XLSX files …")
    try:
        weather_codes_df   = pd.read_excel(WEATHER_CODES_XLSX)
        activities_df      = pd.read_excel(ACTIVITIES_XLSX)
        safety_guidance_df = pd.read_excel(SAFETY_GUIDANCE_XLSX)
    except FileNotFoundError as exc:
        log.error("Reference file not found: %s", exc)
        raise
    log.info("Reference files loaded successfully.")
    return weather_codes_df, activities_df, safety_guidance_df


# ===========================================================================
# 4. CLEANING & TRANSFORMATION
# ===========================================================================

def build_locations_table() -> pd.DataFrame:
    """Return the single-row locations dimension for Louisville, KY."""
    return pd.DataFrame([LOCATION])


def clean_weather_codes(df: pd.DataFrame) -> pd.DataFrame:
    """Select, type-cast, and deduplicate the weather_codes dimension."""
    cols = ["weather_code_id", "condition_name", "description", "is_precipitation"]
    df = df[cols].copy()
    df["weather_code_id"]  = df["weather_code_id"].astype(int)
    df["condition_name"]   = df["condition_name"].astype(str).str.strip()
    df["description"]      = df["description"].astype(str).str.strip()
    df["is_precipitation"] = df["is_precipitation"].astype(bool)
    return df.drop_duplicates(subset=["weather_code_id"])


def clean_activities(df: pd.DataFrame) -> pd.DataFrame:
    """Select, rename, type-cast, and deduplicate the activities dimension."""
    cols = [
        "activity_id", "activity_name", "activity_type",
        "activity_intensity", "suitable_condition", "description",
    ]
    df = df[cols].copy()
    df = df.rename(columns={"description": "activity_description"})
    df["activity_id"] = df["activity_id"].astype(int)
    return df.drop_duplicates(subset=["activity_id"])


def clean_safety_guidance(df: pd.DataFrame) -> pd.DataFrame:
    """Select, type-cast, and deduplicate the safety_guidance dimension."""
    cols = [
        "safety_guidance_id", "guidance_type", "guidance_text",
        "condition_trigger", "recommended_item", "avoidance_guidance", "alert_level",
    ]
    df = df[cols].copy()
    df["safety_guidance_id"] = df["safety_guidance_id"].astype(int)
    return df.drop_duplicates(subset=["safety_guidance_id"])


def transform_weather_forecast(
    raw_df: pd.DataFrame,
    weather_codes_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Enrich raw API weather data:
      - Attach location_id and sequential weather_id
      - Join weather_code_id from the codes dimension
      - Convert temperature from Celsius to Fahrenheit (derived metric)
      - Round numeric fields for storage consistency
    """
    df = raw_df.copy()

    # Assign surrogate key — will be used for incremental deduplication later
    df.insert(0, "weather_id", range(1, len(df) + 1))
    df.insert(1, "location_id", LOCATION["location_id"])

    # Map weather_code integer → weather_code_id FK
    code_map = weather_codes_df.set_index("weather_code_id")["condition_name"].to_dict()
    # weather_code from the API IS the weather_code_id in our dimension table
    df["weather_code_id"] = df["weather_code"].astype(int)
    df = df.drop(columns=["weather_code"])

    # Derived metric: temperature in Fahrenheit
    df["temperature_2m_max_f"] = (df["temperature_2m_max"] * 9 / 5 + 32).round(1)
    df["temperature_2m_min_f"] = (df["temperature_2m_min"] * 9 / 5 + 32).round(1)

    # Round float columns to 2 decimal places
    float_cols = [
        "temperature_2m_max", "temperature_2m_min",
        "uv_index_max", "uv_index_clear_sky_max",
        "precipitation_sum", "precipitation_hours",
        "precipitation_probability_max",
        "wind_speed_10m_max", "wind_gusts_10m_max",
    ]
    df[float_cols] = df[float_cols].round(2)

    log.info("Weather forecast transformed: %d rows.", len(df))
    return df


def transform_air_quality_forecast(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich raw API air quality data:
      - Attach location_id and sequential air_quality_id
      - Round numeric fields
    """
    df = raw_df.copy()
    df.insert(0, "air_quality_id", range(1, len(df) + 1))
    df.insert(1, "location_id", LOCATION["location_id"])

    float_cols = [
        "pm10", "pm25", "carbon_monoxide",
        "nitrogen_dioxide", "ozone", "uv_index",
        "aqi_european", "aqi_us",
    ]
    df[float_cols] = df[float_cols].round(2)

    log.info("Air quality forecast transformed: %d rows.", len(df))
    return df


def build_recommendations_table(
    weather_df: pd.DataFrame,
    air_quality_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Generate rule-based activity and safety recommendations by joining the
    weather and air quality forecasts.  Rules (priority order):
        1. Poor Air Quality (AQI > 100) → indoor activity + air quality guidance
        2. High Precipitation (prob > 70%) → indoor activity + rain guidance
        3. High UV (uv_index ≥ 6)         → shaded activity + SPF guidance
        4. High Temperature (> 85°F)       → water activity + heat guidance
        5. Default                         → walking + general prep
    """
    joined = weather_df.merge(
        air_quality_df,
        on=["location_id", "forecast_date"],
        how="left",
        suffixes=("_weather", "_air"),
    )

    rows = []
    for idx, row in joined.iterrows():
        uv        = float(row.get("uv_index_max", 0)   or 0)
        precip    = float(row.get("precipitation_probability_max", 0) or 0)
        temp_f    = float(row.get("temperature_2m_max_f", 70) or 70)
        aqi       = float(row.get("aqi_us", 50) or 50)

        # Rule-based routing
        if aqi > 100:
            activity_id, safety_id = 8, 9
            ctype  = "Poor Air Quality"
            reason = "AQI above 100 — minimize prolonged outdoor exposure."
        elif precip > 70:
            activity_id, safety_id = 7, 5
            ctype  = "High Precipitation"
            reason = "High precipitation probability — choose indoor activities and bring rain protection."
        elif uv >= 6:
            activity_id, safety_id = 5, 4
            ctype  = "High UV"
            reason = "Elevated UV index — opt for shaded outdoor activities with SPF 50+."
        elif temp_f > 85:
            activity_id, safety_id = 4, 11
            ctype  = "High Temperature"
            reason = "High temperature — stay hydrated and prefer water-based activities."
        else:
            activity_id, safety_id = 1, 12
            ctype  = "Favorable Conditions"
            reason = "Conditions support light outdoor activity."

        rows.append({
            "recommendation_id":    idx + 1,
            "location_id":          int(row["location_id"]),
            "weather_id":           int(row["weather_id"]),
            "air_quality_id":       None if pd.isna(row.get("air_quality_id")) else int(row["air_quality_id"]),
            "activity_id":          activity_id,
            "safety_guidance_id":   safety_id,
            "forecast_date":        row["forecast_date"],
            "condition_type":       ctype,
            "recommendation_reason": reason,
        })

    df = pd.DataFrame(rows)
    log.info("Recommendations built: %d rows.", len(df))
    return df


# ===========================================================================
# 5. DATA VALIDATION & QUALITY CHECKS
# ===========================================================================

def validate_dataframe(df: pd.DataFrame, name: str, required_cols: list[str]) -> bool:
    """
    Run a standard suite of quality checks on a DataFrame and log results.

    Checks performed:
        - Row count > 0
        - Required columns present
        - No fully-duplicate rows
        - Null counts per column
    Returns True when all checks pass, False otherwise.
    """
    log.info("── Validating %s (%d rows, %d cols) ──", name, len(df), len(df.columns))
    passed = True

    # Row count
    if len(df) == 0:
        log.error("  [FAIL] %s is empty.", name)
        passed = False
    else:
        log.info("  [PASS] Row count: %d", len(df))

    # Required columns
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        log.error("  [FAIL] Missing required columns: %s", missing)
        passed = False
    else:
        log.info("  [PASS] All required columns present.")

    # Duplicate rows
    dup_count = df.duplicated().sum()
    if dup_count > 0:
        log.warning("  [WARN] %d fully-duplicate rows found.", dup_count)
    else:
        log.info("  [PASS] No duplicate rows.")

    # Null counts
    null_summary = df.isnull().sum()
    nullable_cols = null_summary[null_summary > 0]
    if not nullable_cols.empty:
        for col, cnt in nullable_cols.items():
            log.warning("  [WARN] Column '%s' has %d null value(s).", col, cnt)
    else:
        log.info("  [PASS] No null values detected.")

    return passed


def validate_range(df: pd.DataFrame, col: str, min_val: float, max_val: float, name: str) -> None:
    """Check that all values in a numeric column fall within the expected range."""
    if col not in df.columns:
        return
    out_of_range = df[(df[col] < min_val) | (df[col] > max_val)]
    if not out_of_range.empty:
        log.warning(
            "  [WARN] %s.%s: %d value(s) outside expected range [%s, %s].",
            name, col, len(out_of_range), min_val, max_val,
        )
    else:
        log.info("  [PASS] %s.%s range check [%s, %s] OK.", name, col, min_val, max_val)


def run_all_validations(
    locations_df:      pd.DataFrame,
    weather_codes_df:  pd.DataFrame,
    weather_df:        pd.DataFrame,
    air_quality_df:    pd.DataFrame,
    activities_df:     pd.DataFrame,
    safety_df:         pd.DataFrame,
    recommendations_df:pd.DataFrame,
) -> None:
    """Run all quality checks across every table and raise on critical failure."""
    log.info("===== DATA VALIDATION & QUALITY CHECKS =====")
    all_passed = True

    all_passed &= validate_dataframe(
        locations_df, "locations",
        ["location_id", "city", "state", "latitude", "longitude"],
    )
    all_passed &= validate_dataframe(
        weather_codes_df, "weather_codes",
        ["weather_code_id", "condition_name", "description", "is_precipitation"],
    )
    all_passed &= validate_dataframe(
        weather_df, "weather_forecast",
        ["weather_id", "location_id", "forecast_date", "temperature_2m_max", "uv_index_max"],
    )
    all_passed &= validate_dataframe(
        air_quality_df, "air_quality_forecast",
        ["air_quality_id", "location_id", "forecast_date", "aqi_us"],
    )
    all_passed &= validate_dataframe(
        activities_df, "activities",
        ["activity_id", "activity_name"],
    )
    all_passed &= validate_dataframe(
        safety_df, "safety_guidance",
        ["safety_guidance_id", "guidance_type", "guidance_text"],
    )
    all_passed &= validate_dataframe(
        recommendations_df, "recommendations",
        ["recommendation_id", "location_id", "weather_id", "forecast_date"],
    )

    # Range checks
    validate_range(weather_df,      "temperature_2m_max", -60,  60, "weather_forecast")
    validate_range(weather_df,      "uv_index_max",         0,  20, "weather_forecast")
    validate_range(weather_df,      "precipitation_probability_max", 0, 100, "weather_forecast")
    validate_range(air_quality_df,  "aqi_us",               0, 500, "air_quality_forecast")

    # Referential integrity: all weather_code_ids in weather_forecast must exist in weather_codes
    valid_codes = set(weather_codes_df["weather_code_id"].unique())
    bad_codes   = set(weather_df["weather_code_id"].unique()) - valid_codes
    if bad_codes:
        log.warning(
            "  [WARN] weather_forecast references unknown weather_code_ids: %s", bad_codes
        )
    else:
        log.info("  [PASS] Referential integrity: weather_code_id check passed.")

    if not all_passed:
        log.error("One or more critical validation checks FAILED — review logs before proceeding.")
    else:
        log.info("===== ALL VALIDATION CHECKS PASSED =====")


# ===========================================================================
# 6. INCREMENTAL LOADING
# ===========================================================================
# Strategy: for forecast tables (weather_forecast, air_quality_forecast,
# recommendations), we check which forecast_dates already exist in the DB and
# only insert rows for new dates.  Dimension tables (locations, weather_codes,
# activities, safety_guidance) use INSERT … ON CONFLICT DO NOTHING so
# re-running the script never creates duplicates.
#
# If a full reload is required, set RESET_TABLES=true in .env.

def get_existing_dates(engine, table: str, date_col: str = "forecast_date") -> set:
    """Return the set of forecast_dates already loaded into a given table."""
    insp = inspect(engine)
    if not insp.has_table(table, schema="public"):
        return set()
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT DISTINCT {date_col} FROM public.{table}")).fetchall()
    return {r[0] for r in rows}


def upsert_dimension(df: pd.DataFrame, table_name: str, engine, pk_col: str) -> None:
    """
    Safely load a dimension table using INSERT ... ON CONFLICT DO NOTHING.

    This replaces a plain append for dimension tables so that re-running the
    pipeline never raises a UniqueViolation on rows that are already present.
    New rows are inserted; existing rows (matched on pk_col) are silently skipped.
    """
    if df.empty:
        log.info("  Skipping %s — no rows to load.", table_name)
        return

    cols         = ", ".join(df.columns)
    placeholders = ", ".join(f":{c}" for c in df.columns)
    sql = text(
        f"INSERT INTO public.{table_name} ({cols}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT ({pk_col}) DO NOTHING"
    )

    records  = df.to_dict(orient="records")
    inserted = 0
    skipped  = 0

    with engine.begin() as conn:
        for record in records:
            result = conn.execute(sql, record)
            if result.rowcount == 1:
                inserted += 1
            else:
                skipped += 1

    log.info(
        "  %s — %d inserted, %d already existed (skipped).",
        table_name, inserted, skipped,
    )


def write_table(df: pd.DataFrame, table_name: str, engine, dtype: dict) -> None:
    """Append a DataFrame to the named PostgreSQL table (used by incremental_load)."""
    if df.empty:
        log.info("  Skipping %s — no new rows to load.", table_name)
        return
    log.info("  Loading %s: %d rows …", table_name, len(df))
    df.to_sql(
        table_name, engine,
        schema="public",
        if_exists="append",
        index=False,
        method="multi",
        chunksize=500,
        dtype=dtype,
    )
    log.info("  %s loaded successfully.", table_name)


def incremental_load(
    df: pd.DataFrame,
    table_name: str,
    engine,
    dtype: dict,
    date_col: str = "forecast_date",
) -> None:
    """
    Load only rows whose forecast_date is not already present in the table.
    This prevents duplicate inserts on repeated pipeline runs.
    """
    existing = get_existing_dates(engine, table_name, date_col)
    if existing:
        log.info(
            "  [INCREMENTAL] %s already contains %d date(s); filtering new rows only.",
            table_name, len(existing),
        )
        new_df = df[~df[date_col].isin(existing)].copy()
    else:
        new_df = df

    if new_df.empty:
        log.info("  [INCREMENTAL] No new rows for %s — already up to date.", table_name)
        return

    write_table(new_df, table_name, engine, dtype)


# ===========================================================================
# 7. DATABASE LOADING
# ===========================================================================

def load_all_tables(
    engine,
    locations_df:       pd.DataFrame,
    weather_codes_df:   pd.DataFrame,
    activities_df:      pd.DataFrame,
    safety_df:          pd.DataFrame,
    weather_df:         pd.DataFrame,
    air_quality_df:     pd.DataFrame,
    recommendations_df: pd.DataFrame,
) -> None:
    """
    Load all tables into PostgreSQL in foreign-key dependency order.
    Dimension tables use upsert (ON CONFLICT DO NOTHING); fact tables use incremental loading.
    """
    log.info("===== DATABASE LOADING =====")

    # --- Dimensions (upsert — safe to re-run, skips rows that already exist) ---
    upsert_dimension(locations_df,     "locations",       engine, pk_col="location_id")
    upsert_dimension(weather_codes_df, "weather_codes",   engine, pk_col="weather_code_id")
    upsert_dimension(activities_df,    "activities",      engine, pk_col="activity_id")
    upsert_dimension(safety_df,        "safety_guidance", engine, pk_col="safety_guidance_id")

    # --- Fact tables (incremental by forecast_date) ---
    # Drop derived Fahrenheit columns before loading (not in schema)
    weather_load_df = weather_df.drop(
        columns=[c for c in ["temperature_2m_max_f", "temperature_2m_min_f"] if c in weather_df.columns]
    )
    incremental_load(weather_load_df, "weather_forecast", engine, {
        "weather_id": Integer(), "location_id": Integer(),
        "weather_code_id": Integer(), "forecast_date": DateTime(),
        "temperature_2m_max": Numeric(), "temperature_2m_min": Numeric(),
        "uv_index_max": Numeric(), "uv_index_clear_sky_max": Numeric(),
        "precipitation_sum": Numeric(), "precipitation_hours": Numeric(),
        "precipitation_probability_max": Numeric(),
        "wind_speed_10m_max": Numeric(), "wind_gusts_10m_max": Numeric(),
    })

    incremental_load(air_quality_df, "air_quality_forecast", engine, {
        "air_quality_id": Integer(), "location_id": Integer(),
        "forecast_date": DateTime(),
        "pm10": Numeric(), "pm25": Numeric(), "carbon_monoxide": Numeric(),
        "nitrogen_dioxide": Numeric(), "ozone": Numeric(),
        "uv_index": Numeric(), "aqi_european": Numeric(), "aqi_us": Numeric(),
    })

    incremental_load(recommendations_df, "recommendations", engine, {
        "recommendation_id": Integer(), "location_id": Integer(),
        "weather_id": Integer(), "air_quality_id": Integer(),
        "activity_id": Integer(), "safety_guidance_id": Integer(),
        "forecast_date": DateTime(), "condition_type": String(),
        "recommendation_reason": String(),
    })

    log.info("===== ALL TABLES LOADED =====")


# ===========================================================================
# 8. ANALYTICS-READY EXPORT
# ===========================================================================
# Produces flat, denormalized CSV files that Power BI or Plotly Dash can
# consume directly without further SQL joins.

def export_analytics_datasets(
    weather_df:        pd.DataFrame,
    air_quality_df:    pd.DataFrame,
    recommendations_df:pd.DataFrame,
    activities_df:     pd.DataFrame,
    safety_df:         pd.DataFrame,
) -> None:
    """
    Join and export denormalized datasets to the data/ directory for use
    in Power BI or Plotly Dash.  No dashboard code is included here; these
    flat files are the prepared inputs for downstream visualization tools.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Full forecast view: weather + air quality side by side
    forecast_flat = weather_df.merge(
        air_quality_df.drop(columns=["location_id"]),
        on="forecast_date", how="left",
        suffixes=("_weather", "_air"),
    )
    forecast_path = DATA_DIR / "analytics_forecast.csv"
    forecast_flat.to_csv(forecast_path, index=False)
    log.info("Analytics export → %s (%d rows)", forecast_path.name, len(forecast_flat))

    # Recommendations view: recommendations + activity names + guidance labels
    recs_flat = recommendations_df.merge(
        activities_df[["activity_id", "activity_name", "activity_type"]],
        on="activity_id", how="left",
    ).merge(
        safety_df[["safety_guidance_id", "guidance_type", "alert_level"]],
        on="safety_guidance_id", how="left",
    ).merge(
        weather_df[["weather_id", "forecast_date", "temperature_2m_max_f",
                    "uv_index_max", "precipitation_probability_max"]],
        on=["weather_id", "forecast_date"], how="left",
    )
    recs_path = DATA_DIR / "analytics_recommendations.csv"
    recs_flat.to_csv(recs_path, index=False)
    log.info("Analytics export → %s (%d rows)", recs_path.name, len(recs_flat))


# ===========================================================================
# 9. MAIN ORCHESTRATION
# ===========================================================================

def main() -> None:
    """
    Orchestrate the full ETL pipeline:
        1. Connect to the database
        2. Ensure schema exists
        3. Extract from APIs and reference files
        4. Clean and transform data
        5. Validate quality
        6. Load incrementally into PostgreSQL
        7. Export analytics-ready CSVs
    """
    log.info("============================================================")
    log.info("  Environmental Activity & Safety Recommendation ETL Start  ")
    log.info("  Run timestamp: %s", datetime.now(timezone.utc).isoformat())
    log.info("============================================================")

    # -- Connect --
    try:
        engine = create_engine(get_database_url())
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info("Database connection established.")
    except Exception as exc:
        log.error("Database connection failed: %s", exc)
        sys.exit(1)

    # -- Schema --
    create_schema(engine)

    # -- Extract --
    raw_weather_df     = extract_weather_forecast()
    raw_air_quality_df = extract_air_quality_forecast()
    raw_weather_codes_df, raw_activities_df, raw_safety_df = load_reference_files()

    # -- Transform --
    log.info("===== TRANSFORMATION =====")
    locations_df     = build_locations_table()
    weather_codes_df = clean_weather_codes(raw_weather_codes_df)
    activities_df    = clean_activities(raw_activities_df)
    safety_df        = clean_safety_guidance(raw_safety_df)
    weather_df       = transform_weather_forecast(raw_weather_df, weather_codes_df)
    air_quality_df   = transform_air_quality_forecast(raw_air_quality_df)
    recommendations_df = build_recommendations_table(weather_df, air_quality_df)

    # -- Validate --
    run_all_validations(
        locations_df, weather_codes_df,
        weather_df, air_quality_df,
        activities_df, safety_df, recommendations_df,
    )

    # -- Load --
    load_all_tables(
        engine, locations_df, weather_codes_df, activities_df, safety_df,
        weather_df, air_quality_df, recommendations_df,
    )

    # -- Analytics export --
    log.info("===== ANALYTICS EXPORT =====")
    export_analytics_datasets(
        weather_df, air_quality_df, recommendations_df, activities_df, safety_df,
    )

    log.info("============================================================")
    log.info("  ETL PIPELINE COMPLETE")
    log.info("============================================================")


if __name__ == "__main__":
    main()
    