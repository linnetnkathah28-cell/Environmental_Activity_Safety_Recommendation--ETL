-- =============================================================================
-- views_tables.sql
-- Louisville ENV Dashboard — PostgreSQL View Definitions
-- =============================================================================
-- Run in order — each view depends on the one above it:
--   1. v_weather_daily
--   2. v_recommendations_full
--   3. v_daily_summary
-- =============================================================================


-- =============================================================================
-- 1. v_weather_daily
-- =============================================================================
-- One row per forecast day. Joins weather_forecast → weather_codes and
-- air_quality_forecast, and derives Fahrenheit conversions (temp_max_f /
-- temp_min_f) which are NOT stored in the DB — the ETL drops them before load.
-- =============================================================================

CREATE OR REPLACE VIEW public.v_weather_daily AS
WITH daily_air AS (
    -- air_quality_forecast is one row per day — just aggregate the key fields
    SELECT
        location_id,
        forecast_date,
        MAX(air_quality_id)                     AS air_quality_id,
        ROUND(AVG(aqi_us)::numeric, 2)          AS aqi_us,
        ROUND(AVG(aqi_european)::numeric, 2)    AS aqi_european,
        ROUND(AVG(pm25)::numeric, 2)            AS pm25,
        ROUND(AVG(pm10)::numeric, 2)            AS pm10,
        ROUND(AVG(nitrogen_dioxide)::numeric, 2) AS nitrogen_dioxide,
        ROUND(AVG(ozone)::numeric, 2)           AS ozone,
        ROUND(AVG(carbon_monoxide)::numeric, 2) AS carbon_monoxide,
        ROUND(AVG(uv_index)::numeric, 2)        AS uv_index
    FROM public.air_quality_forecast
    GROUP BY location_id, forecast_date
)
SELECT
    wf.weather_id,
    wf.location_id,
    wf.forecast_date,

    -- Temperature Celsius (as stored)
    wf.temperature_2m_max                                               AS temp_max_c,
    wf.temperature_2m_min                                               AS temp_min_c,

    -- Temperature Fahrenheit (derived — not stored in DB)
    ROUND((wf.temperature_2m_max * 9.0 / 5 + 32)::numeric, 1)         AS temp_max_f,
    ROUND((wf.temperature_2m_min * 9.0 / 5 + 32)::numeric, 1)         AS temp_min_f,

    -- UV
    wf.uv_index_max,
    wf.uv_index_clear_sky_max,

    -- Precipitation
    wf.precipitation_sum,
    wf.precipitation_hours,
    wf.precipitation_probability_max,

    -- Wind
    wf.wind_speed_10m_max,
    wf.wind_gusts_10m_max,

    -- Weather condition (from lookup)
    wc.condition_name,
    wc.is_precipitation,

    -- Air quality
    da.air_quality_id,
    da.aqi_us,
    da.aqi_european,
    da.pm25,
    da.pm10,
    da.nitrogen_dioxide,
    da.ozone,
    da.carbon_monoxide,
    da.uv_index                                                         AS uv_index_air

FROM public.weather_forecast    wf
JOIN public.weather_codes        wc ON wc.weather_code_id = wf.weather_code_id
LEFT JOIN daily_air              da ON da.location_id     = wf.location_id
                                   AND da.forecast_date   = wf.forecast_date

ORDER BY wf.forecast_date;


-- =============================================================================
-- 2. v_recommendations_full
-- =============================================================================
-- One row per recommendation. Extends recommendations with activity name/type,
-- safety guidance text, and all weather + AQ factors from v_weather_daily.
-- The Fahrenheit temp columns come from the view since they're not in the DB.
-- =============================================================================

CREATE OR REPLACE VIEW public.v_recommendations_full AS
SELECT
    -- Recommendation identity
    r.recommendation_id,
    r.forecast_date,
    r.location_id,
    r.weather_id,
    r.air_quality_id,

    -- Condition & alert
    r.condition_type,
    r.recommendation_reason,
    sg.alert_level,

    -- Activity
    a.activity_name,
    a.activity_type,
    a.activity_intensity,
    a.suitable_condition,

    -- Guidance
    sg.guidance_type,
    sg.guidance_text,
    sg.recommended_item,
    sg.avoidance_guidance,

    -- Weather factors (from v_weather_daily which derives °F)
    wd.temp_max_f,
    wd.temp_min_f,
    wd.temp_max_c,
    wd.temp_min_c,
    wd.uv_index_max,
    wd.precipitation_probability_max,
    wd.precipitation_sum,
    wd.wind_speed_10m_max,
    wd.wind_gusts_10m_max,
    wd.condition_name,
    wd.is_precipitation,

    -- Air quality factors
    wd.aqi_us,
    wd.aqi_european,
    wd.pm25,
    wd.pm10,
    wd.nitrogen_dioxide,
    wd.ozone

FROM public.recommendations         r
JOIN public.activities               a   ON a.activity_id          = r.activity_id
JOIN public.safety_guidance          sg  ON sg.safety_guidance_id  = r.safety_guidance_id
JOIN public.v_weather_daily          wd  ON wd.weather_id           = r.weather_id

ORDER BY r.forecast_date, sg.alert_level;


-- =============================================================================
-- 3. v_daily_summary
-- =============================================================================
-- One row per forecast day. Picks the dominant recommendation per day
-- (Extreme > High > Moderate > Low, then condition severity as tiebreaker)
-- so the dashboard day-card loop needs no Python groupby or merge.
-- =============================================================================

CREATE OR REPLACE VIEW public.v_daily_summary AS

WITH ranked_recs AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY forecast_date
            ORDER BY
                CASE alert_level
                    WHEN 'Extreme'  THEN 1
                    WHEN 'High'     THEN 2
                    WHEN 'Moderate' THEN 3
                    WHEN 'Low'      THEN 4
                    ELSE 5
                END,
                CASE condition_type
                    WHEN 'Poor Air Quality'     THEN 1
                    WHEN 'High Temperature'     THEN 2
                    WHEN 'High UV'              THEN 3
                    WHEN 'High Precipitation'   THEN 4
                    WHEN 'Favorable Conditions' THEN 5
                    ELSE 6
                END
        ) AS rn
    FROM public.v_recommendations_full
)
SELECT
    -- Date & location
    wd.forecast_date,
    wd.location_id,

    -- Temperature
    wd.temp_max_f,
    wd.temp_min_f,
    wd.temp_max_c,
    wd.temp_min_c,

    -- UV
    wd.uv_index_max,
    wd.uv_index_clear_sky_max,

    -- Precipitation
    wd.precipitation_probability_max,
    wd.precipitation_sum,

    -- Wind
    wd.wind_speed_10m_max,
    wd.wind_gusts_10m_max,

    -- Air quality
    wd.aqi_us,
    wd.aqi_european,
    wd.pm25,
    wd.pm10,
    wd.nitrogen_dioxide,
    wd.ozone,

    -- Weather label
    wd.condition_name       AS weather_condition,
    wd.is_precipitation,

    -- Dominant recommendation for the day
    r.condition_type,
    r.alert_level,
    r.recommendation_reason,
    r.activity_name,
    r.activity_type,
    r.activity_intensity,
    r.guidance_type,
    r.guidance_text,
    r.recommended_item,
    r.avoidance_guidance

FROM public.v_weather_daily     wd
LEFT JOIN ranked_recs            r
       ON r.forecast_date = wd.forecast_date
      AND r.rn = 1

ORDER BY wd.forecast_date;
