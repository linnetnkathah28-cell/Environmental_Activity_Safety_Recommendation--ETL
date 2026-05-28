# ETL Data Quality Validation Document
## Environmental Activity & Safety Recommendation Dashboard

| Field | Detail |
|---|---|
| **Project** | Environmental Activity & Safety Recommendation Dashboard |
| **Document Type** | ETL Data Quality Validation Report |
| **Assignment** | Week 3 — ETL Pipeline & Data Quality Engineering |
| **Pipeline Script** | `etl_pipeline.py` |
| **Data Source** | Open-Meteo API (Weather & Air Quality) + Reference XLSX Files |
| **Location** | Louisville, KY (38.2542°N, 85.7594°W) |
| **Database** | PostgreSQL (Supabase) — public schema |

---

## Table of Contents

1. [Validation Overview](#1-validation-overview)
2. [Validation Check Types](#2-validation-check-types)
3. [Per-Table Validation Checks](#3-per-table-validation-checks)
4. [Referential Integrity Checks](#4-referential-integrity-checks)
5. [Incremental Loading Strategy](#5-incremental-loading-strategy)
6. [Log Output Reference](#6-log-output-reference)
7. [Error Handling & Failure Behaviour](#7-error-handling--failure-behaviour)
8. [Analytics Export Validation](#8-analytics-export-validation)
9. [Validation Summary](#9-validation-summary)

---

## 1. Validation Overview

This document records the data quality and validation checks implemented in `etl_pipeline.py` for the Environmental Activity & Safety Recommendation Dashboard ETL pipeline. It serves as evidence that the pipeline meets the data quality engineering requirements outlined in the Week 3 assignment.

### 1.1 Purpose

The purpose of this validation document is to:

- Catalogue every quality check applied to each table in the pipeline.
- Record the expected behaviour and pass/fail criteria for each check.
- Provide a reference for reviewing pipeline output logs.
- Demonstrate professional data quality engineering practices.

### 1.2 Pipeline Stages Covered

| # | Stage | Description |
|---|---|---|
| 1 | Extraction | Pull 7-day forecasts from Open-Meteo Weather & Air Quality APIs plus reference XLSX files. |
| 2 | Cleaning | Column selection, type casting, string trimming, deduplication of dimension tables. |
| 3 | Transformation | Celsius → Fahrenheit conversion, hourly → daily AQI aggregation, rule-based recommendation generation. |
| 4 | Validation | Row count, null checks, range validation, referential integrity, duplicate detection. |
| 5 | Incremental Loading | Check existing `forecast_date`s in DB and insert only new rows; dimensions use append. |
| 6 | Analytics Export | Produce flat denormalized CSVs for Power BI / Plotly Dash consumption. |

---

## 2. Validation Check Types

The pipeline implements the following categories of data quality checks, all executed inside `run_all_validations()` before any data is written to the database.

| Check Type | Function / Location | What It Detects |
|---|---|---|
| Row Count | `validate_dataframe()` | Empty tables — zero rows indicate a failed extraction or transformation. |
| Required Columns | `validate_dataframe()` | Missing columns that would cause downstream failures or incomplete DB loads. |
| Duplicate Rows | `validate_dataframe()` | Fully identical rows that would violate primary key constraints. |
| Null / Missing Values | `validate_dataframe()` | Null counts per column, logged as warnings so the pipeline can still proceed. |
| Numeric Range | `validate_range()` | Values outside physically meaningful bounds (e.g. UV index > 20, AQI > 500). |
| Referential Integrity | `run_all_validations()` | `weather_code_id`s in the forecast table that have no matching row in the codes dimension. |
| API Response | `extract_weather_forecast()` / `extract_air_quality_forecast()` | HTTP errors and empty API responses caught via `try/except` before any transformation. |
| Schema / Data Types | `transform_*()` functions | Explicit `.astype()` casts fail loudly if a column cannot be coerced to the expected type. |

---

## 3. Per-Table Validation Checks

The sections below document the specific checks applied to each of the seven tables in the pipeline.

> **PASS** — blocking check (pipeline exits on failure)
> **WARN** — non-blocking (logged and reported, execution continues)

---

### 3.1 `locations`

| Check | Detail / Threshold | Status |
|---|---|---|
| Row Count > 0 | Fails pipeline if table is empty after build. | ✅ PASS |
| Required Columns | `location_id`, `city`, `state`, `latitude`, `longitude` | ✅ PASS |
| Duplicate Rows | Full-row deduplication check; logged as WARNING if found. | ✅ PASS |
| Null Values | Per-column null count logged. | ✅ PASS |

> Single-row static table built directly in Python. Validates that the Louisville, KY record is present before any FK-dependent table is loaded.

---

### 3.2 `weather_codes`

| Check | Detail / Threshold | Status |
|---|---|---|
| Row Count > 0 | Fails pipeline if table is empty. | ✅ PASS |
| Required Columns | `weather_code_id`, `condition_name`, `description`, `is_precipitation` | ✅ PASS |
| Duplicate Rows | Deduplicated on `weather_code_id` before load. | ✅ PASS |
| Null Values | Per-column null count logged. | ✅ PASS |

> Loaded from `weather_codes.xlsx`. Also used in the referential integrity check against `weather_forecast.weather_code_id`.

---

### 3.3 `weather_forecast`

| Check | Detail / Threshold | Status |
|---|---|---|
| Row Count > 0 | Fails pipeline if API returns no rows. | ✅ PASS |
| Required Columns | `weather_id`, `location_id`, `forecast_date`, `temperature_2m_max`, `uv_index_max` | ✅ PASS |
| Duplicate Rows | Full-row deduplication check. | ✅ PASS |
| Null Values | Per-column null count logged as WARNING. | ⚠️ WARN |
| Range: `temperature_2m_max` | Expected: -60°C – 60°C | ⚠️ WARN |
| Range: `uv_index_max` | Expected: 0 – 20 | ⚠️ WARN |
| Range: `precipitation_probability_max` | Expected: 0% – 100% | ⚠️ WARN |

> Sourced from Open-Meteo Weather API. `forecast_date` is the incremental load key. Includes derived columns `temperature_2m_max_f` and `temperature_2m_min_f` (Celsius → Fahrenheit), validated implicitly through the source range check.

---

### 3.4 `air_quality_forecast`

| Check | Detail / Threshold | Status |
|---|---|---|
| Row Count > 0 | Fails pipeline if API returns no rows. | ✅ PASS |
| Required Columns | `air_quality_id`, `location_id`, `forecast_date`, `aqi_us` | ✅ PASS |
| Duplicate Rows | Full-row deduplication check. | ✅ PASS |
| Null Values | Per-column null count logged as WARNING. | ⚠️ WARN |
| Range: `aqi_us` | Expected: 0 – 500 | ⚠️ WARN |

> Sourced from Open-Meteo Air Quality API. Hourly data is aggregated to daily max before validation and loading. `forecast_date` is the incremental load key.

---

### 3.5 `activities`

| Check | Detail / Threshold | Status |
|---|---|---|
| Row Count > 0 | Fails pipeline if XLSX is empty. | ✅ PASS |
| Required Columns | `activity_id`, `activity_name`, `activity_type` | ✅ PASS |
| Duplicate Rows | Deduplicated on `activity_id` before load. | ✅ PASS |
| Null Values | Per-column null count logged. | ✅ PASS |

> Loaded from `activities.xlsx`. Referenced by the `recommendations` table via FK.

---

### 3.6 `safety_guidance`

| Check | Detail / Threshold | Status |
|---|---|---|
| Row Count > 0 | Fails pipeline if XLSX is empty. | ✅ PASS |
| Required Columns | `safety_guidance_id`, `guidance_type`, `guidance_text` | ✅ PASS |
| Duplicate Rows | Deduplicated on `safety_guidance_id` before load. | ✅ PASS |
| Null Values | Per-column null count logged. | ✅ PASS |

> Loaded from `safety_guidance.xlsx`. Referenced by the `recommendations` table via FK.

---

### 3.7 `recommendations`

| Check | Detail / Threshold | Status |
|---|---|---|
| Row Count > 0 | Fails pipeline if no recommendations can be generated. | ✅ PASS |
| Required Columns | `recommendation_id`, `location_id`, `weather_id`, `forecast_date` | ✅ PASS |
| Duplicate Rows | Full-row deduplication check. | ✅ PASS |
| Null Values | `air_quality_id` may be null on date mismatch — logged as WARNING. | ⚠️ WARN |

> Derived table built from weather and air quality forecasts using rule-based logic. Every row must reference a valid `weather_id` and `location_id`.

---

## 4. Referential Integrity Checks

In addition to per-table checks, the pipeline verifies cross-table relationships before loading to catch orphaned foreign key references early.

| Child Table | FK Column | Parent Table | Check Behaviour |
|---|---|---|---|
| `weather_forecast` | `weather_code_id` | `weather_codes` | Compares unique codes in forecast against codes dimension. Unrecognised codes logged as WARN. |
| `weather_forecast` | `location_id` | `locations` | Enforced at DB level via FK constraint. Pipeline loads `locations` first. |
| `air_quality_forecast` | `location_id` | `locations` | Enforced at DB level via FK constraint. |
| `recommendations` | `weather_id` | `weather_forecast` | Enforced at DB level via FK constraint. Forecast loaded before recommendations. |
| `recommendations` | `air_quality_id` | `air_quality_forecast` | Nullable FK; nulls occur when no AQI row matches a forecast date (logged as WARN). |
| `recommendations` | `activity_id` | `activities` | Enforced at DB level via FK constraint. |
| `recommendations` | `safety_guidance_id` | `safety_guidance` | Enforced at DB level via FK constraint. |

---

## 5. Incremental Loading Strategy

The pipeline uses a date-based incremental loading strategy for the three fact tables. Dimension tables are loaded with standard append since their contents are controlled by the reference XLSX files.

### 5.1 Strategy Summary

| Table | Strategy | Detail |
|---|---|---|
| `locations` | Append | Single static row; append is safe since `UNIQUE` constraint prevents duplicates. |
| `weather_codes` | Append | Dimension rows deduplicated in Python before load. PK constraint prevents doubles. |
| `activities` | Append | Dimension rows deduplicated in Python before load. |
| `safety_guidance` | Append | Dimension rows deduplicated in Python before load. |
| `weather_forecast` | **Incremental** | Query existing `forecast_date`s → insert only rows whose date is not already present. |
| `air_quality_forecast` | **Incremental** | Same date-based strategy as `weather_forecast`. |
| `recommendations` | **Incremental** | Same date-based strategy; recommendation rows are keyed to `forecast_date`. |

### 5.2 Incremental Load Logic (`get_existing_dates`)

The `incremental_load()` function calls `get_existing_dates()` before every fact table insert:

- Uses SQLAlchemy `inspect()` to check if the table exists before querying it.
- If the table is empty or new, all rows are inserted (first run).
- On subsequent runs, only rows with a `forecast_date` not present in the DB are inserted.
- Re-running the pipeline on the same day will produce zero inserts for fact tables, confirming idempotency.

### 5.3 Full Reset Option

Setting `RESET_TABLES=true` in `.env` drops and recreates all tables before the pipeline runs. This is intended for development use or when reference dimensions change. The behaviour is logged as a `WARNING` so it is always visible in the run log.

---

## 6. Log Output Reference

All validation results are written to both the console and `etl_pipeline.log` using Python's standard `logging` module. The table below documents expected log messages for each check type.

| Level | Tag | Example Message |
|---|---|---|
| INFO | `[PASS] Row count` | `[PASS] Row count: 7` |
| INFO | `[PASS] Columns` | `[PASS] All required columns present.` |
| INFO | `[PASS] No duplicates` | `[PASS] No duplicate rows.` |
| INFO | `[PASS] No nulls` | `[PASS] No null values detected.` |
| INFO | `[PASS] Range check` | `[PASS] weather_forecast.uv_index_max range check [0, 20] OK.` |
| INFO | `[PASS] Ref integrity` | `[PASS] Referential integrity: weather_code_id check passed.` |
| WARNING | `[WARN] Nulls found` | `[WARN] Column 'air_quality_id' has 2 null value(s).` |
| WARNING | `[WARN] Range exceeded` | `[WARN] weather_forecast.uv_index_max: 1 value(s) outside expected range [0, 20].` |
| WARNING | `[WARN] Duplicates` | `[WARN] 3 fully-duplicate rows found.` |
| WARNING | `[WARN] Unknown FK` | `[WARN] weather_forecast references unknown weather_code_ids: {99}` |
| WARNING | `[WARN] Reset tables` | `RESET_TABLES=true — dropping all existing tables before reload.` |
| INFO | `[INCREMENTAL]` | `[INCREMENTAL] No new rows for weather_forecast — already up to date.` |
| ERROR | `[FAIL] Empty table` | `[FAIL] weather_forecast is empty.` |
| ERROR | DB connection | `Database connection failed: (error detail)` |
| ERROR | API failure | `Weather API request failed: (error detail)` |

---

## 7. Error Handling & Failure Behaviour

The pipeline distinguishes between blocking failures (which halt execution) and non-blocking warnings (which are logged and allow the pipeline to continue).

| Scenario | Behaviour | Implementation |
|---|---|---|
| Database connection failure | **BLOCKING** — `sys.exit(1)` | `try/except` around `engine.connect()`; logs error and exits immediately. |
| API request failure (weather) | **BLOCKING** — raises | `try/except` in `extract_weather_forecast()`; logged then re-raised to halt pipeline. |
| API request failure (air quality) | **BLOCKING** — raises | `try/except` in `extract_air_quality_forecast()`; same pattern. |
| Reference XLSX file not found | **BLOCKING** — raises | `FileNotFoundError` caught in `load_reference_files()`; logged then re-raised. |
| Empty table after extraction | **BLOCKING** — logged | `validate_dataframe()` sets `passed=False`; prevents loading empty data. |
| Missing required column | **BLOCKING** — logged | `validate_dataframe()` sets `passed=False` and lists missing columns. |
| Null values in nullable columns | **WARNING** — continues | Column-level null counts logged; pipeline proceeds since nulls are valid in some FK fields. |
| Values outside numeric range | **WARNING** — continues | Out-of-range rows counted and logged; pipeline proceeds. |
| Duplicate rows detected | **WARNING** — continues | Python deduplication removes duplicates before DB load. |
| Unknown `weather_code_id` (FK) | **WARNING** — continues | Set difference logged; DB constraint enforces integrity at insert time. |
| No new rows (incremental load) | **INFO** — skipped | `incremental_load()` logs informational message and returns early. |
| API response retry | **Automatic** — transparent | `requests-cache` + `retry-requests` retries up to 5 times with exponential backoff. |

---

## 8. Analytics Export Validation

After the database load stage, the pipeline writes two flat denormalized CSV files for direct consumption by Power BI or Plotly Dash. These files are validated implicitly — they are generated from the already-validated and loaded DataFrames, so any quality issues would have been caught in earlier stages.

| File | Source Tables Joined | Key Columns |
|---|---|---|
| `data/analytics_forecast.csv` | `weather_forecast` + `air_quality_forecast` | `forecast_date`, `temperature_2m_max_f`, `uv_index_max`, `aqi_us`, `precipitation_probability_max` |
| `data/analytics_recommendations.csv` | `recommendations` + `activities` + `safety_guidance` + `weather_forecast` | `forecast_date`, `activity_name`, `activity_type`, `guidance_type`, `alert_level`, `condition_type`, `recommendation_reason` |

Both files are written by `export_analytics_datasets()` using pandas `.to_csv()`. Row counts are logged after each export. These outputs are excluded from version control via `.gitignore` since they are regenerated on every pipeline run.

---

## 9. Validation Summary

Consolidated view of all validation checks across all tables.

| Table | Row Count | Req. Cols | No Dups | Nulls | Range | Ref. Int. |
|---|---|---|---|---|---|---|
| `locations` | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | — | — |
| `weather_codes` | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | — | ✅ PASS |
| `weather_forecast` | ✅ PASS | ✅ PASS | ✅ PASS | ⚠️ WARN | ⚠️ WARN | ✅ PASS |
| `air_quality_forecast` | ✅ PASS | ✅ PASS | ✅ PASS | ⚠️ WARN | ⚠️ WARN | — |
| `activities` | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | — | — |
| `safety_guidance` | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | — | — |
| `recommendations` | ✅ PASS | ✅ PASS | ✅ PASS | ⚠️ WARN | — | ✅ PASS |

### Legend

| Badge | Meaning |
|---|---|
| ✅ PASS | Check passes — no issues detected. |
| ⚠️ WARN | Non-blocking issue found and logged; pipeline continues. |
| ❌ FAIL | Critical failure — pipeline halts execution. |
| — | Check not applicable for this table. |
