"""

Louisville ENV Dashboard — Dash app

Run: python dash_app.py  →  http://127.0.0.1:8050

"""

from __future__ import annotations

 

import importlib.util

import os

import pathlib

import sys

import threading

from datetime import date

 

import dash

import pandas as pd

import plotly.graph_objects as go

from dash import Input, Output, dcc, html

from dotenv import load_dotenv

from sqlalchemy import create_engine, text

 

# ---------------------------------------------------------------------------

# Config

# ---------------------------------------------------------------------------

load_dotenv()

 

DB_URL = (

    f"postgresql+psycopg2://"

    f"{os.getenv('DB_USER','postgres')}:{os.getenv('DB_PASSWORD','')}@"

    f"{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT','5432')}/"

    f"{os.getenv('DB_NAME','postgres')}"

    f"?sslmode={os.getenv('DB_SSLMODE','require')}"

)

engine = create_engine(DB_URL, pool_pre_ping=True)

 

# ---------------------------------------------------------------------------

# Palette & shared styles

# ---------------------------------------------------------------------------

P = {

    "bg":      "#0D1117", "surface": "#161B22", "border":  "#30363D",

    "accent":  "#2EA043", "accent2": "#58A6FF", "warn":    "#D29922",

    "danger":  "#F85149", "text":    "#E6EDF3", "muted":   "#7D8590",

    "card":    "#1C2128",

}

 

ALERT_CLR   = {"Low": P["accent"], "Moderate": P["warn"], "High": P["danger"], "Extreme": "#FF4C8B"}

COND_CLR    = {

    "Favorable Conditions": P["accent"],  "High UV":            P["warn"],

    "High Temperature":     "#FF7A45",    "High Precipitation":  P["accent2"],

    "Poor Air Quality":     P["danger"],

}

MONO        = "'IBM Plex Mono', monospace"

PLOT_BASE   = dict(

    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",

    font=dict(family=MONO, color=P["text"], size=12),

    margin=dict(l=48, r=24, t=36, b=48),

    xaxis=dict(gridcolor=P["border"], linecolor=P["border"], tickcolor=P["border"], zeroline=False),

    yaxis=dict(gridcolor=P["border"], linecolor=P["border"], tickcolor=P["border"], zeroline=False),

    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=P["border"], borderwidth=1),

    hoverlabel=dict(bgcolor=P["surface"], bordercolor=P["border"], font_family=MONO),

)

BTN_BASE    = dict(background=P["surface"], borderRadius="6px", padding="6px 16px",

                   fontSize="12px", fontFamily=MONO, letterSpacing="0.06em",

                   cursor="pointer", textTransform="uppercase", transition="opacity 0.2s")

BTN_READY   = {**BTN_BASE, "color": P["accent"],  "border": f"1px solid {P['accent']}"}

BTN_RUNNING = {**BTN_BASE, "color": P["muted"],   "border": f"1px solid {P['muted']}",

               "cursor": "not-allowed", "opacity": "0.5"}

 

# ---------------------------------------------------------------------------

# UI helpers

# ---------------------------------------------------------------------------

def _lbl(text, extra=None):

    s = {"color": P["muted"], "fontSize": "10px", "letterSpacing": "0.12em",

         "display": "block", "marginBottom": "6px", "textTransform": "uppercase"}

    if extra: s.update(extra)

    return html.Label(text, style=s)

 

def card(children, style=None):

    s = {"background": P["card"], "border": f"1px solid {P['border']}",

         "borderRadius": "8px", "padding": "20px"}

    if style: s.update(style)

    return html.Div(children, style=s)

 

def chart_card(title, graph_id, height):

    return card([

        html.P(title, style={"color": P["muted"], "fontSize": "11px",

                             "letterSpacing": "0.08em", "textTransform": "uppercase",

                             "margin": "0 0 4px"}),

        dcc.Graph(id=graph_id, config={"displayModeBar": False}, style={"height": f"{height}px"}),

    ])

 

def kpi(label, value, sub="", color=None):

    color = color or P["accent2"]

    return card([

        html.P(label, style={"color": P["muted"], "fontSize": "11px",

                             "letterSpacing": "0.1em", "textTransform": "uppercase", "margin": "0 0 6px"}),

        html.P(value, style={"color": color, "fontSize": "28px", "fontWeight": "700",

                             "margin": "0 0 4px", "fontFamily": MONO, "letterSpacing": "-0.02em"}),

        html.P(sub,   style={"color": P["muted"], "fontSize": "11px", "margin": "0"}),

    ])

 

def badge(text, color, alpha_bg="22", alpha_border="55"):

    return html.Span(text or "—", style={

        "background": f"{color}{alpha_bg}", "color": color,

        "border": f"1px solid {color}{alpha_border}", "borderRadius": "4px",

        "padding": "2px 8px", "fontSize": "10px", "fontFamily": MONO,

        "letterSpacing": "0.05em", "whiteSpace": "nowrap",

    })

 

def factor_pill(label, value, color):

    return html.Div([

        html.Span(label, style={"fontSize": "9px", "color": P["muted"], "letterSpacing": "0.1em",

                                "textTransform": "uppercase", "display": "block", "marginBottom": "2px"}),

        html.Span(value, style={"fontSize": "13px", "fontWeight": "700",

                                "color": color, "fontFamily": MONO}),

    ], style={"background": f"{color}18", "border": f"1px solid {color}44",

              "borderRadius": "6px", "padding": "6px 10px", "minWidth": "64px", "textAlign": "center"})

 

def mono_span(text, color=None, size="12px", weight="400"):

    return html.Span(text, style={"fontFamily": MONO, "fontSize": size,

                                  "color": color or P["text"], "fontWeight": weight})

 

# ---------------------------------------------------------------------------

# Threshold colour helpers

# ---------------------------------------------------------------------------

def uv_color(v):

    if v is None: return P["muted"]

    return P["danger"] if v >= 8 else P["warn"] if v >= 6 else P["accent"]

 

def aqi_color(v):

    if v is None: return P["muted"]

    return P["danger"] if v > 100 else P["warn"] if v > 50 else P["accent"]

 

def precip_color(v):

    if v is None: return P["muted"]

    return P["danger"] if v >= 70 else P["warn"] if v >= 40 else P["accent2"]

 

def fmt(v, fmt_str, fallback="—"):

    try: return fmt_str.format(v) if v is not None else fallback

    except: return fallback

 

# ---------------------------------------------------------------------------

# Data fetchers

# ---------------------------------------------------------------------------

def _sql(q):

    with engine.connect() as c:

        return pd.read_sql(text(q), c, parse_dates=["forecast_date"])

 

def fetch_weather():      return _sql("SELECT * FROM public.v_weather_daily       ORDER BY forecast_date")

def fetch_recs():         return _sql("SELECT * FROM public.v_recommendations_full ORDER BY forecast_date, alert_level")

def fetch_summary():      return _sql("SELECT * FROM public.v_daily_summary        ORDER BY forecast_date")

 

# Startup load

weather_df = fetch_weather()

recs_df    = fetch_recs()

summary_df = fetch_summary()

 

# ---------------------------------------------------------------------------

# ETL background runner

# ---------------------------------------------------------------------------

_etl_state = {"status": "idle", "message": ""}

_etl_lock  = threading.Lock()

 

def _run_etl():

    with _etl_lock:

        _etl_state.update(status="running", message="")

    try:

        load_dotenv()

        env = os.getenv("ETL_SCRIPT_PATH", "").strip()

        if env:

            p = pathlib.Path(env)

            if not p.exists():

                raise FileNotFoundError(f"ETL_SCRIPT_PATH not found: {p}")

        else:

            names = ["etl_main_script.py", "etl_main.py", "etl.py"]

            dirs  = list(dict.fromkeys([

                pathlib.Path(os.getcwd()),

                pathlib.Path(__file__).resolve().parent,

                pathlib.Path(sys.argv[0]).resolve().parent,

            ]))

            p = next((d/n for d in dirs for n in names if (d/n).exists()), None)

            if p is None:

                raise FileNotFoundError(

                    "ETL script not found. Set ETL_SCRIPT_PATH in your .env file.")

        spec = importlib.util.spec_from_file_location("etl_main", p)

        mod  = importlib.util.module_from_spec(spec)

        spec.loader.exec_module(mod)

        mod.main()

        with _etl_lock:

            _etl_state.update(status="done", message="ETL completed successfully.")

    except Exception as e:

        with _etl_lock:

            _etl_state.update(status="error", message=str(e))

 

# ---------------------------------------------------------------------------

# Layout

# ---------------------------------------------------------------------------

date_range = (

    f"{summary_df['forecast_date'].min().strftime('%b %d')} – "

    f"{summary_df['forecast_date'].max().strftime('%b %d, %Y')}"

) if not summary_df.empty else "No data"

 

app = dash.Dash(__name__, title="Louisville ENV Dashboard",

                meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}])

server = app.server

 

app.layout = html.Div(style={"background": P["bg"], "minHeight": "100vh",

                              "fontFamily": "'IBM Plex Sans', sans-serif", "color": P["text"]},

    children=[

        html.Link(rel="stylesheet", href=(

            "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700"

            "&family=IBM+Plex+Sans:wght@300;400;600&display=swap"

        )),

 

        # Header

        html.Div(style={"background": P["surface"], "borderBottom": f"1px solid {P['border']}",

                        "padding": "16px 32px", "display": "flex",

                        "alignItems": "center", "justifyContent": "space-between"},

            children=[

                html.Div([

                    html.Span("◈ ", style={"color": P["accent"], "fontSize": "20px"}),

                    html.Span("Louisville ENV Dashboard",

                              style={"fontFamily": MONO, "fontSize": "18px",

                                     "fontWeight": "700", "letterSpacing": "-0.02em"}),

                ]),

                html.Div(date_range, style={"color": P["muted"], "fontSize": "12px", "fontFamily": MONO}),

                html.Div(style={"display": "flex", "alignItems": "center", "gap": "12px"}, children=[

                    html.Span(id="etl-status-label",

                              style={"color": P["muted"], "fontSize": "11px", "fontFamily": MONO}),

                    html.Button(id="btn-refresh-etl", n_clicks=0, style=BTN_READY,

                                children=[html.Span("↻ ", style={"fontSize": "15px"}), "Refresh Data"]),

                ]),

            ]),

 

        # Main

        html.Div(style={"maxWidth": "1400px", "margin": "0 auto", "padding": "28px 24px"},

            children=[

 

                # KPI row

                html.Div(id="kpi-row", style={"display": "grid",

                    "gridTemplateColumns": "repeat(5, 1fr)", "gap": "14px", "marginBottom": "24px"}),

 

                # Day summary cards

                card(style={"marginBottom": "24px"}, children=[

                    html.P("Daily Forecast & Recommendations",

                           style={"color": P["muted"], "fontSize": "11px", "letterSpacing": "0.08em",

                                  "textTransform": "uppercase", "margin": "0 0 16px"}),

                    html.Div(id="day-summary-row",

                             style={"display": "flex", "gap": "12px",

                                    "overflowX": "auto", "paddingBottom": "4px"}),

                ]),

 

                # Filters

                card(style={"marginBottom": "24px", "padding": "16px 20px"}, children=[

                    html.Div(style={"display": "flex", "alignItems": "center",

                                   "gap": "32px", "flexWrap": "wrap"}, children=[

                        html.Div([

                            _lbl("Date Range"),

                            html.Div(style={"display": "flex", "gap": "8px", "marginBottom": "8px"},

                                children=[

                                    html.Button("Today", id="btn-today", n_clicks=0,

                                        style={**BTN_BASE, "background": "transparent",

                                               "color": P["accent2"], "border": f"1px solid {P['accent2']}",

                                               "padding": "4px 14px", "fontSize": "11px"}),

                                    html.Button("7-Day Forecast", id="btn-7day", n_clicks=0,

                                        style={**BTN_BASE, "background": "transparent",

                                               "color": P["accent"], "border": f"1px solid {P['accent']}",

                                               "padding": "4px 14px", "fontSize": "11px"}),

                                ]),

                            dcc.DatePickerRange(id="date-filter", display_format="MMM DD",

                                               style={"fontFamily": MONO}),

                        ]),

                        html.Div([

                            _lbl("Condition Type"),

                            dcc.Dropdown(id="condition-filter", clearable=False,

                                value="ALL",

                                options=[{"label": "All Conditions", "value": "ALL"}] +

                                        [{"label": c, "value": c}

                                         for c in sorted(summary_df["condition_type"].dropna().unique())],

                                style={"width": "220px", "fontFamily": MONO, "fontSize": "13px",

                                       "backgroundColor": P["bg"], "color": P["text"],

                                       "border": f"1px solid {P['border']}", "borderRadius": "6px"}),

                        ]),

                        html.Div([

                            _lbl("Temperature Unit"),

                            dcc.RadioItems(id="temp-unit", value="F", inline=True,

                                options=[{"label": " °F", "value": "F"}, {"label": " °C", "value": "C"}],

                                inputStyle={"marginRight": "4px"},

                                labelStyle={"marginRight": "18px", "fontSize": "13px",

                                            "fontFamily": MONO, "color": P["text"]}),

                        ]),

                    ]),

                ]),

 

                # Charts row 1

                html.Div(style={"display": "grid", "gridTemplateColumns": "1.6fr 1fr",

                                "gap": "16px", "marginBottom": "16px"}, children=[

                    chart_card("7-Day Temperature Forecast",    "temp-chart",      280),

                    chart_card("UV Index & Precipitation Prob", "uv-precip-chart", 280),

                ]),

 

                # Charts row 2

                html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr",

                                "gap": "16px", "marginBottom": "16px"}, children=[

                    chart_card("Air Quality Index Trend (US AQI)", "aqi-chart",      260),

                    chart_card("Condition Distribution",           "condition-pie",  260),

                ]),

 

                # Charts row 3

                html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1.4fr",

                                "gap": "16px", "marginBottom": "16px"}, children=[

                    chart_card("Wind Speed & Gusts", "wind-chart", 260),

                    card([

                        html.P("Daily Activity Recommendations",

                               style={"color": P["muted"], "fontSize": "11px", "letterSpacing": "0.08em",

                                      "textTransform": "uppercase", "margin": "0 0 12px"}),

                        html.Div(id="recs-table", style={"overflowY": "auto", "maxHeight": "240px"}),

                    ]),

                ]),

 

                # Charts row 4

                chart_card("Pollutant Breakdown (μg/m³)", "pollutant-chart", 240),

 

                # Footer

                html.Div("Data sourced from Open-Meteo API · Louisville, KY (38.25°N, 85.76°W)",

                         style={"color": P["muted"], "fontSize": "11px", "textAlign": "center",

                                "padding": "16px 0 8px", "borderTop": f"1px solid {P['border']}",

                                "fontFamily": MONO}),

            ]),

 

        dcc.Interval(id="refresh-interval",  interval=600_000, n_intervals=0),

        dcc.Interval(id="etl-poll-interval", interval=2_000,   n_intervals=0, disabled=True),

        html.Div(id="_init-trigger", **{"data-loaded": "0"}, style={"display": "none"}),

    ])

 

# ---------------------------------------------------------------------------

# Callbacks — ETL

# ---------------------------------------------------------------------------

@app.callback(

    Output("btn-refresh-etl",   "disabled"),

    Output("btn-refresh-etl",   "style"),

    Output("etl-poll-interval", "disabled"),

    Output("etl-status-label",  "children"),

    Input("btn-refresh-etl",    "n_clicks"),

    prevent_initial_call=True,

)

def launch_etl(_):

    with _etl_lock:

        if _etl_state["status"] == "running":

            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    threading.Thread(target=_run_etl, daemon=True).start()

    return True, BTN_RUNNING, False, "⟳ Running ETL…"

 

 

@app.callback(

    Output("btn-refresh-etl",   "disabled",  allow_duplicate=True),

    Output("btn-refresh-etl",   "style",     allow_duplicate=True),

    Output("etl-poll-interval", "disabled",  allow_duplicate=True),

    Output("etl-status-label",  "children",  allow_duplicate=True),

    Output("refresh-interval",  "n_intervals"),

    Input("etl-poll-interval",  "n_intervals"),

    prevent_initial_call=True,

)

def poll_etl(n):

    with _etl_lock:

        status, message = _etl_state["status"], _etl_state["message"]

    if status == "running":

        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    with _etl_lock:

        _etl_state["status"] = "idle"

    label = "✓ Data refreshed" if status == "done" else f"✗ {message[:70]}"

    return False, BTN_READY, True, label, n

 

 

# ---------------------------------------------------------------------------

# Callbacks — date picker

# ---------------------------------------------------------------------------

@app.callback(

    Output("date-filter", "min_date_allowed"),

    Output("date-filter", "max_date_allowed"),

    Output("date-filter", "start_date"),

    Output("date-filter", "end_date"),

    Input("btn-today",        "n_clicks"),

    Input("btn-7day",         "n_clicks"),

    Input("refresh-interval", "n_intervals"),

    Input("_init-trigger",    "data-loaded"),

)

def sync_date_picker(*_):

    triggered = dash.ctx.triggered_id

    wdf  = fetch_weather()

    dmin = wdf["forecast_date"].dt.date.min() if not wdf.empty else date.today()

    dmax = wdf["forecast_date"].dt.date.max() if not wdf.empty else date.today()

    if triggered == "btn-today":

        sel = max(dmin, min(date.today(), dmax))

        return str(dmin), str(dmax), str(sel), str(sel)

    return str(dmin), str(dmax), str(dmin), str(dmax)

 

 

# ---------------------------------------------------------------------------

# Callbacks — main charts

# ---------------------------------------------------------------------------

@app.callback(

    Output("kpi-row",         "children"),

    Output("day-summary-row", "children"),

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

    wdf = fetch_weather()

    rdf = fetch_recs()

    anf = fetch_summary()

 

    # Date filter

    if start_date and end_date:

        sd, ed = pd.to_datetime(start_date).date(), pd.to_datetime(end_date).date()

    elif not wdf.empty:

        sd, ed = wdf["forecast_date"].dt.date.min(), wdf["forecast_date"].dt.date.max()

    else:

        sd = ed = None

 

    if sd and ed:

        mask = lambda df: (df["forecast_date"].dt.date >= sd) & (df["forecast_date"].dt.date <= ed)

        wdf, rdf, anf = wdf[mask(wdf)], rdf[mask(rdf)], anf[mask(anf)]

 

    rdf_f    = rdf if condition == "ALL" else rdf[rdf["condition_type"] == condition]

    dates_s  = wdf["forecast_date"].dt.strftime("%a %b %d").tolist()

    unit_lbl = "°F" if temp_unit == "F" else "°C"

 

    # ── Temperature chart ────────────────────────────────────────────────────

    ymax = "temp_max_f" if temp_unit == "F" else "temp_max_c"

    ymin = "temp_min_f" if temp_unit == "F" else "temp_min_c"

    temp_fig = go.Figure([

        go.Scatter(x=dates_s, y=wdf[ymax], name=f"High ({unit_lbl})",

            mode="lines+markers", line=dict(color=P["danger"], width=2.5),

            marker=dict(size=8, color=P["danger"], line=dict(color=P["bg"], width=2)),

            hovertemplate=f"%{{y}}{unit_lbl}<extra>High</extra>"),

        go.Scatter(x=dates_s, y=wdf[ymin], name=f"Low ({unit_lbl})",

            mode="lines+markers", line=dict(color=P["accent2"], width=2.5),

            marker=dict(size=8, color=P["accent2"], line=dict(color=P["bg"], width=2)),

            fill="tozeroy", fillcolor="rgba(88,166,255,0.06)",

            hovertemplate=f"%{{y}}{unit_lbl}<extra>Low</extra>"),

    ])

    temp_fig.update_layout(**PLOT_BASE, yaxis_title=f"Temperature ({unit_lbl})", showlegend=True)

 

    # ── UV + Precipitation ───────────────────────────────────────────────────

    uv_fig = go.Figure([

        go.Bar(x=dates_s, y=wdf["precipitation_probability_max"],

            name="Precip Probability (%)", yaxis="y2",

            marker_color="rgba(88,166,255,0.55)",

            marker_line_color=P["accent2"], marker_line_width=1,

            hovertemplate="%{y}%<extra>Precip Prob</extra>"),

        go.Scatter(x=dates_s, y=wdf["uv_index_max"], name="UV Index",

            mode="lines+markers", line=dict(color=P["warn"], width=2.5),

            marker=dict(size=8, color=P["warn"], line=dict(color=P["bg"], width=2)),

            hovertemplate="%{y}<extra>UV Index</extra>"),

    ])

    uv_layout = {**PLOT_BASE,

        "yaxis":  dict(title="UV Index",        gridcolor=P["border"], linecolor=P["border"], zeroline=False),

        "yaxis2": dict(title="Precip Prob (%)", overlaying="y", side="right",

                       showgrid=False, zeroline=False, tickcolor=P["border"], linecolor=P["border"]),

        "barmode": "overlay"}

    uv_fig.update_layout(**uv_layout)

 

    # ── AQI trend ────────────────────────────────────────────────────────────

    aqi_fig = go.Figure()

    for y0, y1, clr, lbl in [

        (0,   50,  "rgba(46,160,67,0.08)",  "Good"),

        (51,  100, "rgba(210,153,34,0.08)", "Moderate"),

        (101, 150, "rgba(248,81,73,0.08)",  "Unhealthy for Sensitive"),

    ]:

        aqi_fig.add_hrect(y0=y0, y1=y1, fillcolor=clr, line_width=0,

                          annotation_text=lbl,

                          annotation_font=dict(color=P["muted"], size=9),

                          annotation_position="top left")

    aqi_fig.add_trace(go.Scatter(

        x=dates_s, y=wdf["aqi_us"], name="US AQI",

        mode="lines+markers+text",

        text=wdf["aqi_us"].fillna(0).round(0).astype(int).astype(str),

        textposition="top center", textfont=dict(size=10, color=P["text"]),

        line=dict(color=P["accent2"], width=2.5),

        marker=dict(size=9, line=dict(color=P["bg"], width=2),

                    color=wdf["aqi_us"].apply(aqi_color).tolist()),

        hovertemplate="AQI %{y:.0f}<extra></extra>"))

    aqi_fig.update_layout(**PLOT_BASE, yaxis_title="AQI (US)", showlegend=False)

 

    # ── Condition pie ────────────────────────────────────────────────────────

    cc = rdf["condition_type"].value_counts().reset_index()

    cc.columns = ["condition", "count"]

    pie_fig = go.Figure(go.Pie(

        labels=cc["condition"], values=cc["count"], hole=0.55,

        marker=dict(colors=[COND_CLR.get(c, P["accent2"]) for c in cc["condition"]],

                    line=dict(color=P["bg"], width=3)),

        hovertemplate="%{label}: %{value} day(s)<extra></extra>",

        textfont=dict(family=MONO, size=11)))

    pie_fig.update_layout(**PLOT_BASE, showlegend=True,

        annotations=[dict(text="Conditions", x=0.5, y=0.5, showarrow=False,

                          font=dict(size=11, color=P["muted"], family=MONO))])

 

    # ── Wind ─────────────────────────────────────────────────────────────────

    wind_fig = go.Figure([

        go.Bar(x=dates_s, y=wdf["wind_speed_10m_max"], name="Wind Speed (km/h)",

            marker_color="rgba(46,160,67,0.7)",

            marker_line_color=P["accent"], marker_line_width=1,

            hovertemplate="%{y} km/h<extra>Speed</extra>"),

        go.Scatter(x=dates_s, y=wdf["wind_gusts_10m_max"], name="Gusts (km/h)",

            mode="lines+markers", line=dict(color=P["warn"], width=2, dash="dot"),

            marker=dict(size=7, symbol="diamond", color=P["warn"],

                        line=dict(color=P["bg"], width=1.5)),

            hovertemplate="%{y} km/h<extra>Gusts</extra>"),

    ])

    wind_fig.update_layout(**PLOT_BASE, yaxis_title="km/h", barmode="overlay")

 

    # ── Pollutants ───────────────────────────────────────────────────────────

    poll_fig = go.Figure()

    for (lbl, col), clr in zip(

        {"PM10": "pm10", "PM2.5": "pm25", "NO₂": "nitrogen_dioxide", "O₃": "ozone"}.items(),

        [P["accent2"], P["danger"], P["warn"], P["accent"]],

    ):

        if col in wdf.columns:

            poll_fig.add_trace(go.Scatter(x=dates_s, y=wdf[col], name=lbl,

                mode="lines+markers", line=dict(color=clr, width=2),

                marker=dict(size=6, color=clr, line=dict(color=P["bg"], width=1.5)),

                hovertemplate=f"%{{y:.2f}} μg/m³<extra>{lbl}</extra>"))

    poll_fig.update_layout(**PLOT_BASE, yaxis_title="μg/m³")

 

    # ── Day summary cards ────────────────────────────────────────────────────

    day_cards = []

    for _, row in anf.iterrows():

        al  = row.get("alert_level") or "—"

        con = row.get("condition_type") or "—"

        alc = ALERT_CLR.get(al, P["muted"])

        coc = COND_CLR.get(con, P["accent2"])

        tf, tm = row.get("temp_max_f"), row.get("temp_min_f")

        uv, pr = row.get("uv_index_max"), row.get("precipitation_probability_max")

        wi, aq = row.get("wind_speed_10m_max"), row.get("aqi_us")

 

        day_cards.append(html.Div([

            html.Div([

                html.Span(row["forecast_date"].strftime("%a"),

                          style={"fontFamily": MONO, "fontWeight": "700", "fontSize": "14px"}),

                html.Span(row["forecast_date"].strftime("%b %d"),

                          style={"fontSize": "10px", "color": P["muted"], "marginLeft": "6px"}),

            ], style={"marginBottom": "10px"}),

            html.Div([

                factor_pill("High", fmt(tf,  "{:.0f}°F"), P["warn"]),

                factor_pill("Low",  fmt(tm,  "{:.0f}°F"), P["accent2"]),

                factor_pill("UV",   fmt(uv,  "{:.1f}"),   uv_color(uv)),

                factor_pill("Rain", fmt(pr,  "{:.0f}%"),  precip_color(pr)),

                factor_pill("Wind", fmt(wi,  "{:.0f}"),   P["muted"]),

                factor_pill("AQI",  fmt(aq,  "{:.0f}"),   aqi_color(aq)),

            ], style={"display": "flex", "gap": "6px", "flexWrap": "wrap", "marginBottom": "10px"}),

            html.Hr(style={"border": "none", "borderTop": f"1px solid {P['border']}", "margin": "0 0 10px"}),

            html.Div([

                html.Span("RISK  ", style={"fontSize": "9px", "color": P["muted"], "letterSpacing": "0.1em"}),

                badge(al, alc),

            ], style={"marginBottom": "6px"}),

            html.Div(badge(con, coc, "18", "44"), style={"marginBottom": "8px"}),

            html.Div([

                html.Span("▶ ", style={"color": alc, "fontSize": "10px"}),

                html.Span(row.get("activity_name") or "—",

                          style={"fontSize": "12px", "fontWeight": "600"}),

            ], style={"marginBottom": "4px"}),

            html.P(row.get("recommendation_reason") or "",

                   style={"fontSize": "10px", "color": P["muted"], "margin": "0", "lineHeight": "1.5"}),

        ], style={

            "background": P["surface"], "borderRadius": "8px", "padding": "14px",

            "minWidth": "220px", "flex": "0 0 220px",

            "border": f"1px solid {alc}44", "borderTop": f"3px solid {alc}",

        }))

 

    if not day_cards:

        day_cards = [html.P("No forecast data for selected range.",

                            style={"color": P["muted"], "fontSize": "12px", "fontStyle": "italic"})]

 

    # ── Recommendations table ────────────────────────────────────────────────

    GRID = "90px 140px 90px 80px 80px 80px 1fr"

    HDR  = ["Date", "Condition", "Alert", "Temp Hi", "UV", "Rain %", "Activity / Recommendation"]

 

    def tbl_row(row):

        t  = row.get("temp_max_f")

        uv = row.get("uv_index_max")

        pr = row.get("precipitation_probability_max")

        fd = row["forecast_date"]

        return html.Div(style={"display": "grid", "gridTemplateColumns": GRID,

                               "gap": "8px", "padding": "8px 10px", "alignItems": "center",

                               "borderBottom": f"1px solid {P['border']}22"}, children=[

            mono_span(fd.strftime("%b %d") if hasattr(fd, "strftime") else str(fd), P["muted"]),

            badge(row.get("condition_type", "—"), COND_CLR.get(row.get("condition_type",""), P["accent2"])),

            badge(row.get("alert_level", "—"),    ALERT_CLR.get(row.get("alert_level",""),   P["muted"])),

            mono_span(fmt(t,  "{:.0f}°F"), P["warn"],     weight="600"),

            mono_span(fmt(uv, "{:.1f}"),   uv_color(uv),  weight="600"),

            mono_span(fmt(pr, "{:.0f}%"),  precip_color(pr), weight="600"),

            html.Div([

                html.Span(row.get("activity_name", "—"),

                          style={"fontSize": "12px", "fontWeight": "600", "display": "block"}),

                html.Span(row.get("recommendation_reason", ""),

                          style={"fontSize": "11px", "color": P["muted"]}),

            ]),

        ])

 

    tbl_header = html.Div(style={"display": "grid", "gridTemplateColumns": GRID,

                                 "gap": "8px", "padding": "6px 10px",

                                 "borderBottom": f"1px solid {P['border']}", "marginBottom": "4px"},

        children=[html.Span(h, style={"color": P["muted"], "fontSize": "10px",

                                      "letterSpacing": "0.1em", "textTransform": "uppercase"})

                  for h in HDR])

 

    tbl_rows = [tbl_header] + [tbl_row(r) for _, r in rdf_f.iterrows()]

    if len(tbl_rows) == 1:

        tbl_rows.append(html.Div("No recommendations match the selected filters.",

            style={"color": P["muted"], "fontSize": "12px",

                   "padding": "16px 10px", "fontStyle": "italic"}))

 

    # ── KPIs ─────────────────────────────────────────────────────────────────

    tc = "temp_max_f" if temp_unit == "F" else "temp_max_c"

    kpis = [

        kpi("Avg High Temp",      f"{round(wdf[tc].mean(), 1)}{unit_lbl}"       if not wdf.empty else "—",

            "7-day forecast",    P["warn"]),

        kpi("Peak UV Index",      str(round(float(wdf['uv_index_max'].max()), 1)) if not wdf.empty else "—",

            "max over period",   P["danger"]),

        kpi("Avg AQI (US)",       str(round(wdf['aqi_us'].mean(), 1))             if not wdf.empty else "No data",

            "air quality index", P["accent2"]),

        kpi("Rainy Days",         str(int((wdf['precipitation_probability_max'] > 50).sum())) if not wdf.empty else "—",

            "prob > 50%",        P["accent2"]),

        kpi("Dominant Condition", rdf["condition_type"].mode()[0]                 if not rdf.empty else "—",

            "most frequent",     P["accent"]),

    ]

 

    return kpis, day_cards, temp_fig, uv_fig, aqi_fig, pie_fig, wind_fig, poll_fig, html.Div(tbl_rows)

 

 

if __name__ == "__main__":

    app.run(debug=True, host="127.0.0.1", port=8050)