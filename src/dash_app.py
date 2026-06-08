"""
Environmental Activity & Safety Recommendation Dashboard
=========================================================
Dash MVP — Week 4 Assignment

Connects to the PostgreSQL database populated by the ETL pipeline and
presents interactive analytics for Louisville, KY weather forecasts,
air quality, and outdoor activity recommendations.

Run:
    python app.py

Then open http://127.0.0.1:8050 in your browser.
"""

from __future__ import annotations

import os

import dash
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dash import Input, Output, dcc, html
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Config & DB connection
# ---------------------------------------------------------------------------

load_dotenv()

DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.getenv('DB_USER', 'postgres')}:"
    f"{os.getenv('DB_PASSWORD', '')}@"
    f"{os.getenv('DB_HOST', 'localhost')}:"
    f"{os.getenv('DB_PORT', '5432')}/"
    f"{os.getenv('DB_NAME', 'postgres')}"
)

engine = create_engine(DB_URL, pool_pre_ping=True)

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def fetch_weather() -> pd.DataFrame:
    sql = """
        SELECT
            wf.forecast_date,
            wf.temperature_2m_max,
            wf.temperature_2m_min,
            ROUND((wf.temperature_2m_max * 9.0 / 5 + 32)::numeric, 1) AS temp_max_f,
            ROUND((wf.temperature_2m_min * 9.0 / 5 + 32)::numeric, 1) AS temp_min_f,
            wf.uv_index_max,
            wf.precipitation_sum,
            wf.precipitation_probability_max,
            wf.wind_speed_10m_max,
            wf.wind_gusts_10m_max,
            wc.condition_name,
            wc.is_precipitation
        FROM public.weather_forecast wf
        JOIN public.weather_codes wc USING (weather_code_id)
        ORDER BY wf.forecast_date
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, parse_dates=["forecast_date"])


def fetch_air_quality() -> pd.DataFrame:
    sql = """
        SELECT
            forecast_date,
            pm10, pm25,
            nitrogen_dioxide,
            ozone,
            aqi_us,
            aqi_european
        FROM public.air_quality_forecast
        ORDER BY forecast_date
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, parse_dates=["forecast_date"])


def fetch_recommendations() -> pd.DataFrame:
    sql = """
        SELECT
            r.forecast_date,
            r.condition_type,
            r.recommendation_reason,
            a.activity_name,
            a.activity_type,
            a.activity_intensity,
            sg.guidance_type,
            sg.alert_level,
            sg.recommended_item,
            sg.guidance_text
        FROM public.recommendations r
        JOIN public.activities a USING (activity_id)
        JOIN public.safety_guidance sg USING (safety_guidance_id)
        ORDER BY r.forecast_date
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, parse_dates=["forecast_date"])


# Load once at startup; callbacks will reload on demand
weather_df     = fetch_weather()
air_df         = fetch_air_quality()
recs_df        = fetch_recommendations()

# ---------------------------------------------------------------------------
# Color palette & helpers
# ---------------------------------------------------------------------------

PALETTE = {
    "bg":        "#0D1117",
    "surface":   "#161B22",
    "border":    "#30363D",
    "accent":    "#2EA043",
    "accent2":   "#58A6FF",
    "warn":      "#D29922",
    "danger":    "#F85149",
    "text":      "#E6EDF3",
    "muted":     "#7D8590",
    "card_bg":   "#1C2128",
}

ALERT_COLORS = {
    "Low":      PALETTE["accent"],
    "Moderate": PALETTE["warn"],
    "High":     PALETTE["danger"],
    "Extreme":  "#FF4C8B",
}

CONDITION_COLORS = {
    "Favorable Conditions": PALETTE["accent"],
    "High UV":              PALETTE["warn"],
    "High Temperature":     "#FF7A45",
    "High Precipitation":   PALETTE["accent2"],
    "Poor Air Quality":     PALETTE["danger"],
}

PLOT_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="'IBM Plex Mono', monospace", color=PALETTE["text"], size=12),
    margin=dict(l=48, r=24, t=36, b=48),
    xaxis=dict(
        gridcolor=PALETTE["border"], linecolor=PALETTE["border"],
        tickcolor=PALETTE["border"], zeroline=False,
    ),
    yaxis=dict(
        gridcolor=PALETTE["border"], linecolor=PALETTE["border"],
        tickcolor=PALETTE["border"], zeroline=False,
    ),
    legend=dict(
        bgcolor="rgba(0,0,0,0)", bordercolor=PALETTE["border"],
        borderwidth=1,
    ),
    hoverlabel=dict(
        bgcolor=PALETTE["surface"], bordercolor=PALETTE["border"],
        font_family="'IBM Plex Mono', monospace",
    ),
)


def card(children, style=None):
    base = {
        "background": PALETTE["card_bg"],
        "border": f"1px solid {PALETTE['border']}",
        "borderRadius": "8px",
        "padding": "20px",
    }
    if style:
        base.update(style)
    return html.Div(children, style=base)


def kpi(label: str, value: str, sub: str = "", color: str = PALETTE["accent2"]):
    return card([
        html.P(label, style={"color": PALETTE["muted"], "fontSize": "11px",
                              "letterSpacing": "0.1em", "textTransform": "uppercase",
                              "margin": "0 0 6px"}),
        html.P(value, style={"color": color, "fontSize": "28px", "fontWeight": "700",
                              "margin": "0 0 4px", "fontFamily": "'IBM Plex Mono', monospace",
                              "letterSpacing": "-0.02em"}),
        html.P(sub,   style={"color": PALETTE["muted"], "fontSize": "11px", "margin": "0"}),
    ])


# ---------------------------------------------------------------------------
# Header date range label (static — shows full dataset span)
# ---------------------------------------------------------------------------

if not weather_df.empty:
    d0 = weather_df["forecast_date"].min().strftime("%b %d")
    d1 = weather_df["forecast_date"].max().strftime("%b %d, %Y")
    date_range = f"{d0} – {d1}"
else:
    date_range = "No data"

# ---------------------------------------------------------------------------
# App layout
# ---------------------------------------------------------------------------

FONT_LINK = html.Link(
    rel="stylesheet",
    href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=IBM+Plex+Sans:wght@300;400;600&display=swap"
)

app = dash.Dash(
    __name__,
    title="Louisville ENV Dashboard",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server   # expose Flask server for deployment

app.layout = html.Div(
    style={
        "background": PALETTE["bg"],
        "minHeight": "100vh",
        "fontFamily": "'IBM Plex Sans', sans-serif",
        "color": PALETTE["text"],
        "padding": "0",
    },
    children=[
        FONT_LINK,

        # ── Header ──────────────────────────────────────────────────────────
        html.Div(
            style={
                "background": PALETTE["surface"],
                "borderBottom": f"1px solid {PALETTE['border']}",
                "padding": "16px 32px",
                "display": "flex",
                "alignItems": "center",
                "justifyContent": "space-between",
            },
            children=[
                html.Div([
                    html.Span("◈ ", style={"color": PALETTE["accent"], "fontSize": "20px"}),
                    html.Span("Louisville ENV Dashboard",
                              style={"fontFamily": "'IBM Plex Mono', monospace",
                                     "fontSize": "18px", "fontWeight": "700",
                                     "letterSpacing": "-0.02em"}),
                ]),
                html.Div(date_range,
                         style={"color": PALETTE["muted"], "fontSize": "12px",
                                "fontFamily": "'IBM Plex Mono', monospace"}),
            ]
        ),

        # ── Main content ────────────────────────────────────────────────────
        html.Div(
            style={"maxWidth": "1400px", "margin": "0 auto", "padding": "28px 24px"},
            children=[

                # ── KPI row (dynamic — updated by callback) ──────────────────
                html.Div(id="kpi-row",
                    style={"display": "grid",
                           "gridTemplateColumns": "repeat(5, 1fr)",
                           "gap": "14px", "marginBottom": "24px"},
                ),

                # ── Filters row ─────────────────────────────────────────────
                card(
                    style={"marginBottom": "24px", "padding": "16px 20px"},
                    children=[
                        html.Div(
                            style={"display": "flex", "alignItems": "center",
                                   "gap": "32px", "flexWrap": "wrap"},
                            children=[
                                html.Div([
                                    html.Label("DATE RANGE",
                                               style={"color": PALETTE["muted"], "fontSize": "10px",
                                                      "letterSpacing": "0.12em", "display": "block",
                                                      "marginBottom": "6px"}),
                                    dcc.DatePickerRange(
                                        id="date-filter",
                                        min_date_allowed=weather_df["forecast_date"].min() if not weather_df.empty else None,
                                        max_date_allowed=weather_df["forecast_date"].max() if not weather_df.empty else None,
                                        start_date=weather_df["forecast_date"].min() if not weather_df.empty else None,
                                        end_date=weather_df["forecast_date"].max() if not weather_df.empty else None,
                                        display_format="MMM DD",
                                        style={"fontFamily": "'IBM Plex Mono', monospace"},
                                    ),
                                ]),
                                html.Div([
                                    html.Label("CONDITION TYPE",
                                               style={"color": PALETTE["muted"], "fontSize": "10px",
                                                      "letterSpacing": "0.12em", "display": "block",
                                                      "marginBottom": "6px"}),
                                    dcc.Dropdown(
                                        id="condition-filter",
                                        options=[{"label": "All Conditions", "value": "ALL"}]
                                                + [{"label": c, "value": c}
                                                   for c in sorted(recs_df["condition_type"].unique())],
                                        value="ALL",
                                        clearable=False,
                                        style={
                                            "width": "220px",
                                            "fontFamily": "'IBM Plex Mono', monospace",
                                            "fontSize": "13px",
                                            "backgroundColor": PALETTE["bg"],
                                            "color": PALETTE["text"],
                                            "border": f"1px solid {PALETTE['border']}",
                                            "borderRadius": "6px",
                                        },
                                    ),
                                ]),
                                html.Div([
                                    html.Label("TEMPERATURE UNIT",
                                               style={"color": PALETTE["muted"], "fontSize": "10px",
                                                      "letterSpacing": "0.12em", "display": "block",
                                                      "marginBottom": "6px"}),
                                    dcc.RadioItems(
                                        id="temp-unit",
                                        options=[
                                            {"label": " °F", "value": "F"},
                                            {"label": " °C", "value": "C"},
                                        ],
                                        value="F",
                                        inline=True,
                                        inputStyle={"marginRight": "4px"},
                                        labelStyle={"marginRight": "18px",
                                                    "fontSize": "13px",
                                                    "fontFamily": "'IBM Plex Mono', monospace",
                                                    "color": PALETTE["text"]},
                                    ),
                                ]),
                            ]
                        )
                    ]
                ),

                # ── Row 1: Temperature + UV/Precip ──────────────────────────
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "1.6fr 1fr",
                           "gap": "16px", "marginBottom": "16px"},
                    children=[
                        card([
                            html.P("7-Day Temperature Forecast",
                                   style={"color": PALETTE["muted"], "fontSize": "11px",
                                          "letterSpacing": "0.08em", "textTransform": "uppercase",
                                          "margin": "0 0 4px"}),
                            dcc.Graph(id="temp-chart", config={"displayModeBar": False},
                                      style={"height": "280px"}),
                        ]),
                        card([
                            html.P("UV Index & Precipitation Probability",
                                   style={"color": PALETTE["muted"], "fontSize": "11px",
                                          "letterSpacing": "0.08em", "textTransform": "uppercase",
                                          "margin": "0 0 4px"}),
                            dcc.Graph(id="uv-precip-chart", config={"displayModeBar": False},
                                      style={"height": "280px"}),
                        ]),
                    ]
                ),

                # ── Row 2: Air Quality + Condition breakdown ─────────────────
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                           "gap": "16px", "marginBottom": "16px"},
                    children=[
                        card([
                            html.P("Air Quality Index Trend (US AQI)",
                                   style={"color": PALETTE["muted"], "fontSize": "11px",
                                          "letterSpacing": "0.08em", "textTransform": "uppercase",
                                          "margin": "0 0 4px"}),
                            dcc.Graph(id="aqi-chart", config={"displayModeBar": False},
                                      style={"height": "260px"}),
                        ]),
                        card([
                            html.P("Condition Distribution",
                                   style={"color": PALETTE["muted"], "fontSize": "11px",
                                          "letterSpacing": "0.08em", "textTransform": "uppercase",
                                          "margin": "0 0 4px"}),
                            dcc.Graph(id="condition-pie", config={"displayModeBar": False},
                                      style={"height": "260px"}),
                        ]),
                    ]
                ),

                # ── Row 3: Wind + Recommendations table ──────────────────────
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "1fr 1.4fr",
                           "gap": "16px", "marginBottom": "16px"},
                    children=[
                        card([
                            html.P("Wind Speed & Gusts",
                                   style={"color": PALETTE["muted"], "fontSize": "11px",
                                          "letterSpacing": "0.08em", "textTransform": "uppercase",
                                          "margin": "0 0 4px"}),
                            dcc.Graph(id="wind-chart", config={"displayModeBar": False},
                                      style={"height": "260px"}),
                        ]),
                        card([
                            html.P("Daily Activity Recommendations",
                                   style={"color": PALETTE["muted"], "fontSize": "11px",
                                          "letterSpacing": "0.08em", "textTransform": "uppercase",
                                          "margin": "0 0 12px"}),
                            html.Div(id="recs-table", style={"overflowY": "auto", "maxHeight": "240px"}),
                        ]),
                    ]
                ),

                # ── Row 4: Air quality pollutant breakdown ───────────────────
                card(
                    style={"marginBottom": "16px"},
                    children=[
                        html.P("Pollutant Breakdown (μg/m³)",
                               style={"color": PALETTE["muted"], "fontSize": "11px",
                                      "letterSpacing": "0.08em", "textTransform": "uppercase",
                                      "margin": "0 0 4px"}),
                        dcc.Graph(id="pollutant-chart", config={"displayModeBar": False},
                                  style={"height": "240px"}),
                    ]
                ),

                # ── Footer ───────────────────────────────────────────────────
                html.Div(
                    "Data sourced from Open-Meteo API · Louisville, KY (38.25°N, 85.76°W) · "
                    "Environmental Activity & Safety Recommendation Dashboard",
                    style={"color": PALETTE["muted"], "fontSize": "11px",
                           "textAlign": "center", "padding": "16px 0 8px",
                           "borderTop": f"1px solid {PALETTE['border']}",
                           "fontFamily": "'IBM Plex Mono', monospace"}
                ),
            ]
        ),

        # Interval for optional live refresh (every 10 min)
        dcc.Interval(id="refresh-interval", interval=600_000, n_intervals=0),
        # Hidden div that fires once on page load to initialise all charts
        html.Div(id="_init-trigger", **{"data-loaded": "0"}, style={"display": "none"}),
    ]
)

# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@app.callback(
    Output("kpi-row",         "children"),
    Output("temp-chart",      "figure"),
    Output("uv-precip-chart", "figure"),
    Output("aqi-chart",       "figure"),
    Output("condition-pie",   "figure"),
    Output("wind-chart",      "figure"),
    Output("pollutant-chart", "figure"),
    Output("recs-table",      "children"),
    Input("date-filter",      "start_date"),
    Input("date-filter",      "end_date"),
    Input("condition-filter", "value"),
    Input("temp-unit",        "value"),
    Input("refresh-interval", "n_intervals"),
    Input("_init-trigger",    "data-loaded"),
)
def update_all(start_date, end_date, condition, temp_unit, _n, _init):
    # Re-fetch on refresh trigger
    wdf  = fetch_weather()
    adf  = fetch_air_quality()
    rdf  = fetch_recommendations()

    # Apply date filter — DatePickerRange sends ISO strings; fall back to full
    # range when values are None (initial load before user interaction)
    if start_date and end_date:
        sd = pd.to_datetime(start_date).date()
        ed = pd.to_datetime(end_date).date()
    elif not wdf.empty:
        sd = wdf["forecast_date"].dt.date.min()
        ed = wdf["forecast_date"].dt.date.max()
    else:
        sd = ed = None

    if sd and ed:
        wdf = wdf[(wdf["forecast_date"].dt.date >= sd) & (wdf["forecast_date"].dt.date <= ed)]
        adf = adf[(adf["forecast_date"].dt.date >= sd) & (adf["forecast_date"].dt.date <= ed)]
        rdf = rdf[(rdf["forecast_date"].dt.date >= sd) & (rdf["forecast_date"].dt.date <= ed)]

    # Apply condition filter to recommendations only
    rdf_filtered = rdf if condition == "ALL" else rdf[rdf["condition_type"] == condition]

    dates_str = wdf["forecast_date"].dt.strftime("%a %b %d").tolist()

    # ── Temperature chart ────────────────────────────────────────────────────
    y_max_col = "temp_max_f" if temp_unit == "F" else "temperature_2m_max"
    y_min_col = "temp_min_f" if temp_unit == "F" else "temperature_2m_min"
    unit_lbl  = "°F" if temp_unit == "F" else "°C"

    temp_fig = go.Figure()
    temp_fig.add_trace(go.Scatter(
        x=dates_str, y=wdf[y_max_col],
        name=f"High ({unit_lbl})",
        mode="lines+markers",
        line=dict(color=PALETTE["danger"], width=2.5),
        marker=dict(size=8, color=PALETTE["danger"],
                    line=dict(color=PALETTE["bg"], width=2)),
        fill="tonexty" if len(wdf) > 0 else None,
        hovertemplate=f"%{{y}}{unit_lbl}<extra>High</extra>",
    ))
    temp_fig.add_trace(go.Scatter(
        x=dates_str, y=wdf[y_min_col],
        name=f"Low ({unit_lbl})",
        mode="lines+markers",
        line=dict(color=PALETTE["accent2"], width=2.5),
        marker=dict(size=8, color=PALETTE["accent2"],
                    line=dict(color=PALETTE["bg"], width=2)),
        fill="tozeroy",
        fillcolor="rgba(88,166,255,0.06)",
        hovertemplate=f"%{{y}}{unit_lbl}<extra>Low</extra>",
    ))
    temp_fig.update_layout(
        **PLOT_LAYOUT,
        yaxis_title=f"Temperature ({unit_lbl})",
        showlegend=True,
    )

    # ── UV + Precipitation dual-axis chart ───────────────────────────────────
    uv_fig = go.Figure()
    uv_fig.add_trace(go.Bar(
        x=dates_str, y=wdf["precipitation_probability_max"],
        name="Precip Probability (%)",
        marker_color="rgba(88,166,255,0.55)",
        marker_line_color=PALETTE["accent2"],
        marker_line_width=1,
        yaxis="y2",
        hovertemplate="%{y}%<extra>Precip Prob</extra>",
    ))
    uv_fig.add_trace(go.Scatter(
        x=dates_str, y=wdf["uv_index_max"],
        name="UV Index",
        mode="lines+markers",
        line=dict(color=PALETTE["warn"], width=2.5),
        marker=dict(size=8, color=PALETTE["warn"],
                    line=dict(color=PALETTE["bg"], width=2)),
        hovertemplate="%{y}<extra>UV Index</extra>",
    ))
    uv_layout = {k: v for k, v in PLOT_LAYOUT.items() if k != "yaxis"}
    uv_layout["yaxis"] = dict(title="UV Index", gridcolor=PALETTE["border"],
                              linecolor=PALETTE["border"], zeroline=False)
    uv_layout["yaxis2"] = dict(title="Precip Prob (%)", overlaying="y", side="right",
                               showgrid=False, zeroline=False,
                               tickcolor=PALETTE["border"], linecolor=PALETTE["border"])
    uv_layout["barmode"] = "overlay"
    uv_fig.update_layout(**uv_layout)

    # ── AQI trend ────────────────────────────────────────────────────────────
    aqi_dates = adf["forecast_date"].dt.strftime("%a %b %d").tolist()
    aqi_fig = go.Figure()
    # AQI reference bands
    for y0, y1, clr, lbl in [
        (0, 50,  "rgba(46,160,67,0.08)",  "Good"),
        (51, 100, "rgba(210,153,34,0.08)", "Moderate"),
        (101,150, "rgba(248,81,73,0.08)",  "Unhealthy for Sensitive"),
    ]:
        aqi_fig.add_hrect(y0=y0, y1=y1, fillcolor=clr, line_width=0,
                          annotation_text=lbl,
                          annotation_font=dict(color=PALETTE["muted"], size=9),
                          annotation_position="top left")
    aqi_fig.add_trace(go.Scatter(
        x=aqi_dates, y=adf["aqi_us"],
        mode="lines+markers+text",
        text=adf["aqi_us"].round(0).astype(int).astype(str),
        textposition="top center",
        textfont=dict(size=10, color=PALETTE["text"]),
        line=dict(color=PALETTE["accent2"], width=2.5),
        marker=dict(size=9, color=adf["aqi_us"].apply(
            lambda v: PALETTE["danger"] if v > 100
                      else PALETTE["warn"] if v > 50
                      else PALETTE["accent"]
        ).tolist(), line=dict(color=PALETTE["bg"], width=2)),
        hovertemplate="AQI %{y:.0f}<extra></extra>",
        name="US AQI",
    ))
    aqi_fig.update_layout(**PLOT_LAYOUT, yaxis_title="AQI (US)", showlegend=False)

    # ── Condition distribution pie ───────────────────────────────────────────
    cond_counts = rdf["condition_type"].value_counts().reset_index()
    cond_counts.columns = ["condition", "count"]
    pie_colors = [CONDITION_COLORS.get(c, PALETTE["accent2"]) for c in cond_counts["condition"]]
    pie_fig = go.Figure(go.Pie(
        labels=cond_counts["condition"],
        values=cond_counts["count"],
        hole=0.55,
        marker=dict(colors=pie_colors,
                    line=dict(color=PALETTE["bg"], width=3)),
        hovertemplate="%{label}: %{value} day(s)<extra></extra>",
        textfont=dict(family="'IBM Plex Mono', monospace", size=11),
    ))
    pie_fig.update_layout(
        **PLOT_LAYOUT,
        showlegend=True,
        annotations=[dict(text="Conditions", x=0.5, y=0.5,
                          font=dict(size=11, color=PALETTE["muted"],
                                    family="'IBM Plex Mono', monospace"),
                          showarrow=False)],
    )

    # ── Wind chart ───────────────────────────────────────────────────────────
    wind_fig = go.Figure()
    wind_fig.add_trace(go.Bar(
        x=dates_str, y=wdf["wind_speed_10m_max"],
        name="Wind Speed (km/h)",
        marker_color="rgba(46,160,67,0.7)",
        marker_line_color=PALETTE["accent"],
        marker_line_width=1,
        hovertemplate="%{y} km/h<extra>Speed</extra>",
    ))
    wind_fig.add_trace(go.Scatter(
        x=dates_str, y=wdf["wind_gusts_10m_max"],
        name="Gusts (km/h)",
        mode="lines+markers",
        line=dict(color=PALETTE["warn"], width=2, dash="dot"),
        marker=dict(size=7, symbol="diamond",
                    color=PALETTE["warn"],
                    line=dict(color=PALETTE["bg"], width=1.5)),
        hovertemplate="%{y} km/h<extra>Gusts</extra>",
    ))
    wind_fig.update_layout(**PLOT_LAYOUT, yaxis_title="km/h", barmode="overlay")

    # ── Pollutant chart ──────────────────────────────────────────────────────
    poll_dates = adf["forecast_date"].dt.strftime("%a %b %d").tolist()
    poll_cols  = {"PM10": "pm10", "PM2.5": "pm25", "NO₂": "nitrogen_dioxide", "O₃": "ozone"}
    poll_colors = [PALETTE["accent2"], PALETTE["danger"], PALETTE["warn"], PALETTE["accent"]]
    poll_fig = go.Figure()
    for (lbl, col), clr in zip(poll_cols.items(), poll_colors):
        if col in adf.columns:
            poll_fig.add_trace(go.Scatter(
                x=poll_dates, y=adf[col],
                name=lbl,
                mode="lines+markers",
                line=dict(color=clr, width=2),
                marker=dict(size=6, color=clr,
                            line=dict(color=PALETTE["bg"], width=1.5)),
                hovertemplate=f"%{{y:.2f}} μg/m³<extra>{lbl}</extra>",
            ))
    poll_fig.update_layout(**PLOT_LAYOUT, yaxis_title="μg/m³")

    # ── Recommendations table ────────────────────────────────────────────────
    def alert_badge(level):
        color = ALERT_COLORS.get(level, PALETTE["muted"])
        return html.Span(level or "—", style={
            "background": f"{color}22",
            "color": color,
            "border": f"1px solid {color}55",
            "borderRadius": "4px",
            "padding": "2px 8px",
            "fontSize": "10px",
            "fontFamily": "'IBM Plex Mono', monospace",
            "letterSpacing": "0.05em",
            "whiteSpace": "nowrap",
        })

    def cond_badge(ctype):
        color = CONDITION_COLORS.get(ctype, PALETTE["accent2"])
        return html.Span(ctype, style={
            "background": f"{color}22",
            "color": color,
            "border": f"1px solid {color}55",
            "borderRadius": "4px",
            "padding": "2px 8px",
            "fontSize": "10px",
            "fontFamily": "'IBM Plex Mono', monospace",
            "whiteSpace": "nowrap",
        })

    header = html.Div(
        style={
            "display": "grid",
            "gridTemplateColumns": "100px 130px 130px 1fr",
            "gap": "8px",
            "padding": "6px 10px",
            "borderBottom": f"1px solid {PALETTE['border']}",
            "marginBottom": "4px",
        },
        children=[
            html.Span(h, style={"color": PALETTE["muted"], "fontSize": "10px",
                                 "letterSpacing": "0.1em", "textTransform": "uppercase"})
            for h in ["Date", "Condition", "Alert", "Activity / Guidance"]
        ]
    )

    rows_html = [header]
    for _, row in rdf_filtered.iterrows():
        rows_html.append(html.Div(
            style={
                "display": "grid",
                "gridTemplateColumns": "100px 130px 130px 1fr",
                "gap": "8px",
                "padding": "8px 10px",
                "borderBottom": f"1px solid {PALETTE['border']}22",
                "alignItems": "center",
            },
            children=[
                html.Span(
                    row["forecast_date"].strftime("%b %d") if hasattr(row["forecast_date"], "strftime") else str(row["forecast_date"]),
                    style={"fontFamily": "'IBM Plex Mono', monospace",
                           "fontSize": "12px", "color": PALETTE["muted"]}
                ),
                cond_badge(row.get("condition_type", "—")),
                alert_badge(row.get("alert_level", "—")),
                html.Div([
                    html.Span(row.get("activity_name", "—"),
                              style={"fontSize": "12px", "fontWeight": "600",
                                     "display": "block"}),
                    html.Span(row.get("recommendation_reason", ""),
                              style={"fontSize": "11px", "color": PALETTE["muted"]}),
                ]),
            ]
        ))

    if len(rows_html) == 1:
        rows_html.append(html.Div(
            "No recommendations match the selected filters.",
            style={"color": PALETTE["muted"], "fontSize": "12px",
                   "padding": "16px 10px", "fontStyle": "italic"}
        ))

    recs_component = html.Div(rows_html)

    # ── Dynamic KPI cards (reflect current date-filtered data + temp unit) ─────
    temp_kpi_col  = "temp_max_f" if temp_unit == "F" else "temperature_2m_max"
    dyn_avg_temp  = round(wdf[temp_kpi_col].mean(), 1)   if not wdf.empty else "—"
    dyn_max_uv    = wdf["uv_index_max"].max()             if not wdf.empty else "—"
    dyn_avg_aqi   = round(adf["aqi_us"].mean(), 1)        if not adf.empty else "—"
    dyn_rain_days = int((wdf["precipitation_probability_max"] > 50).sum()) if not wdf.empty else "—"
    dyn_top_cond  = rdf["condition_type"].mode()[0]       if not rdf.empty else "—"

    kpi_children = [
        kpi("Avg High Temp",      f"{dyn_avg_temp}{unit_lbl}", "7-day forecast",    PALETTE["warn"]),
        kpi("Peak UV Index",      str(dyn_max_uv),              "max over period",   PALETTE["danger"]),
        kpi("Avg AQI (US)",       str(dyn_avg_aqi),             "air quality index", PALETTE["accent2"]),
        kpi("Rainy Days",         str(dyn_rain_days),           "prob > 50%",        PALETTE["accent2"]),
        kpi("Dominant Condition", dyn_top_cond,                 "most frequent",     PALETTE["accent"]),
    ]

    return kpi_children, temp_fig, uv_fig, aqi_fig, pie_fig, wind_fig, poll_fig, recs_component


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)