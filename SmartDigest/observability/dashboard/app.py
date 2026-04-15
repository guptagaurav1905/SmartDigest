"""
observability/dashboard/app.py — Plotly Dash real-time observability dashboard.

Run from SmartDigest root:
    python observability/dashboard/app.py

Then open: http://localhost:8050
"""

import json
import sys
from pathlib import Path
# Ensure SmartDigest root is on sys.path so `observability` package resolves
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, callback
from observability.store import TraceStore

LAST_RUN_PATH = Path(__file__).parent.parent.parent / "state" / "last_run.json"

# ---------------------------------------------------------------------------
# Init — point at SmartDigest's db/ folder
# ---------------------------------------------------------------------------
DB_PATH = str(Path(__file__).parent.parent.parent / "db" / "genai_traces.db")
store = TraceStore(DB_PATH)

app = Dash(
    __name__,
    title="SmartDigest — GenAI Observability",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
C_PURPLE  = "#7F77DD"
C_TEAL    = "#1D9E75"
C_AMBER   = "#BA7517"
C_CORAL   = "#D85A30"
C_BLUE    = "#378ADD"
C_GRAY    = "#888780"
C_RED     = "#E24B4A"
C_GREEN   = "#639922"
BG        = "#F8F8F6"
CARD_BG   = "#FFFFFF"
BORDER    = "#E0DED6"

CARD_STYLE = {
    "background": CARD_BG,
    "border": f"1px solid {BORDER}",
    "borderRadius": "12px",
    "padding": "20px 24px",
    "boxShadow": "0 1px 3px rgba(0,0,0,0.06)",
}

METRIC_CARD = {
    **CARD_STYLE,
    "textAlign": "center",
    "flex": "1",
    "minWidth": "140px",
}


def metric_card(label: str, value, color: str = C_PURPLE):
    return html.Div([
        html.P(label, style={"margin": "0 0 4px", "fontSize": "13px", "color": C_GRAY}),
        html.P(str(value), style={"margin": 0, "fontSize": "28px", "fontWeight": "600", "color": color}),
    ], style=METRIC_CARD)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
app.layout = html.Div([

    # Header
    html.Div([
        html.H1("SmartDigest — GenAI Observability", style={"margin": 0, "fontSize": "22px", "fontWeight": "600"}),
        html.P("Groq scorer trace dashboard — auto-refreshes every 10s",
               style={"margin": "4px 0 0", "color": C_GRAY, "fontSize": "13px"}),
    ], style={"marginBottom": "24px"}),

    # Auto-refresh interval
    dcc.Interval(id="interval", interval=10_000, n_intervals=0),

    # Pipeline health panel
    html.Div([
        html.H3("Pipeline health", style={"margin": "0 0 12px", "fontSize": "15px", "fontWeight": "500"}),
        html.Div(id="pipeline-health"),
    ], style={**CARD_STYLE, "marginBottom": "24px"}),

    # Metric cards row
    html.Div(id="metric-cards", style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "24px"}),

    # Charts row 1
    html.Div([
        html.Div([
            html.H3("Scoring calls over time", style={"margin": "0 0 12px", "fontSize": "15px", "fontWeight": "500"}),
            dcc.Graph(id="calls-over-time", config={"displayModeBar": False}),
        ], style={**CARD_STYLE, "flex": "1", "minWidth": "280px"}),

        html.Div([
            html.H3("Latency distribution (ms)", style={"margin": "0 0 12px", "fontSize": "15px", "fontWeight": "500"}),
            dcc.Graph(id="latency-hist", config={"displayModeBar": False}),
        ], style={**CARD_STYLE, "flex": "1", "minWidth": "280px"}),
    ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "marginBottom": "24px"}),

    # Charts row 2
    html.Div([
        html.Div([
            html.H3("Token usage by usecase", style={"margin": "0 0 12px", "fontSize": "15px", "fontWeight": "500"}),
            dcc.Graph(id="token-bar", config={"displayModeBar": False}),
        ], style={**CARD_STYLE, "flex": "1", "minWidth": "280px"}),

        html.Div([
            html.H3("Cumulative cost (USD)", style={"margin": "0 0 12px", "fontSize": "15px", "fontWeight": "500"}),
            dcc.Graph(id="cost-line", config={"displayModeBar": False}),
        ], style={**CARD_STYLE, "flex": "1", "minWidth": "280px"}),
    ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "marginBottom": "24px"}),

    # Charts row 3
    html.Div([
        html.Div([
            html.H3("Error rate by model", style={"margin": "0 0 12px", "fontSize": "15px", "fontWeight": "500"}),
            dcc.Graph(id="error-bar", config={"displayModeBar": False}),
        ], style={**CARD_STYLE, "flex": "1", "minWidth": "280px"}),

        html.Div([
            html.H3("Status breakdown", style={"margin": "0 0 12px", "fontSize": "15px", "fontWeight": "500"}),
            dcc.Graph(id="status-pie", config={"displayModeBar": False}),
        ], style={**CARD_STYLE, "flex": "1", "minWidth": "280px"}),
    ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "marginBottom": "24px"}),

    # Recent traces table
    html.Div([
        html.H3("Recent traces", style={"margin": "0 0 12px", "fontSize": "15px", "fontWeight": "500"}),
        html.Div(id="trace-table"),
    ], style={**CARD_STYLE, "marginBottom": "24px"}),

], style={"maxWidth": "1200px", "margin": "0 auto", "padding": "24px", "background": BG, "minHeight": "100vh", "fontFamily": "system-ui, sans-serif"})


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------
CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=8, r=8, t=8, b=8),
    font=dict(family="system-ui, sans-serif", size=12, color=C_GRAY),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    xaxis=dict(gridcolor=BORDER, linecolor=BORDER),
    yaxis=dict(gridcolor=BORDER, linecolor=BORDER),
)


def _empty_fig(msg="No data yet — run groq_scorer.py to generate traces"):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                       font=dict(color=C_GRAY, size=13))
    fig.update_layout(**CHART_LAYOUT, height=220, showlegend=False)
    return fig


def _pipeline_health_panel():
    """Read state/last_run.json and render a status row per stage."""
    if not LAST_RUN_PATH.exists():
        return html.P("No pipeline run found yet.", style={"color": C_GRAY, "fontSize": "13px"})

    try:
        data = json.loads(LAST_RUN_PATH.read_text())
    except Exception:
        return html.P("Could not read last_run.json.", style={"color": C_RED, "fontSize": "13px"})

    STAGE_LABELS = {
        "fetch-weather":           "Weather",
        "fetch-calendar":          "Calendar",
        "fetch-gmail":             "Gmail",
        "source-collector-github": "GitHub",
        "source-collector-hn":     "HackerNews",
        "source-collector-rss":    "RSS",
        "source-collector-arxiv":  "arXiv",
        "relevance-scorer":        "Groq Scorer",
        "compose-sod":             "SOD Compose",
        "briefing-composer":       "Briefing",
        "whatsapp-sod":            "WhatsApp",
    }

    rows = []
    for key, label in STAGE_LABELS.items():
        entry = data.get(key)
        if entry is None:
            icon, color, detail = "—", C_GRAY, "not run"
        elif entry.get("status") == "success":
            icon, color, detail = "✅", C_GREEN, entry.get("detail", "")
        elif entry.get("status") == "skipped":
            icon, color, detail = "⏭", C_AMBER, entry.get("detail", "")
        else:
            icon, color, detail = "❌", C_RED, entry.get("detail", "")

        ts = (entry or {}).get("timestamp", "")[:19].replace("T", " ") if entry else ""

        rows.append(html.Tr([
            html.Td(icon,   style={"padding": "5px 10px", "fontSize": "14px"}),
            html.Td(label,  style={"padding": "5px 10px", "fontSize": "13px", "fontWeight": "500"}),
            html.Td(detail, style={"padding": "5px 10px", "fontSize": "12px", "color": color, "maxWidth": "480px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            html.Td(ts,     style={"padding": "5px 10px", "fontSize": "11px", "color": C_GRAY}),
        ], style={"borderBottom": f"0.5px solid {BORDER}"}))

    return html.Table(
        html.Tbody(rows),
        style={"width": "100%", "borderCollapse": "collapse"},
    )


@callback(
    Output("pipeline-health",  "children"),
    Output("metric-cards",    "children"),
    Output("calls-over-time", "figure"),
    Output("latency-hist",    "figure"),
    Output("token-bar",       "figure"),
    Output("cost-line",       "figure"),
    Output("error-bar",       "figure"),
    Output("status-pie",      "figure"),
    Output("trace-table",     "children"),
    Input("interval",         "n_intervals"),
)
def update_dashboard(_):
    stats = store.summary_stats()
    df = store.to_dataframe()

    # ---- metric cards ----
    total      = stats.get("total_calls") or 0
    errors     = stats.get("error_calls") or 0
    avg_lat    = round(stats.get("avg_latency_ms") or 0, 1)
    total_tok  = int(stats.get("total_tokens") or 0)
    total_cost = round(stats.get("total_cost_usd") or 0, 4)
    error_rate = f"{round(errors / total * 100, 1)}%" if total else "0%"

    cards = [
        metric_card("Total calls",  total,            C_PURPLE),
        metric_card("Errors",       errors,           C_RED),
        metric_card("Error rate",   error_rate,       C_CORAL),
        metric_card("Avg latency",  f"{avg_lat}ms",   C_TEAL),
        metric_card("Total tokens", f"{total_tok:,}", C_BLUE),
        metric_card("Total cost",   f"${total_cost}", C_AMBER),
    ]

    health = _pipeline_health_panel()

    if df.empty:
        empty = _empty_fig()
        table = html.P("No traces yet. Run: python scripts/groq_scorer.py",
                       style={"color": C_GRAY, "fontSize": "13px"})
        return health, cards, empty, empty, empty, empty, empty, empty, table

    # ---- calls over time ----
    df_time = df.set_index("created_at").resample("1min").size().reset_index(name="calls")
    fig_calls = px.area(df_time, x="created_at", y="calls",
                        color_discrete_sequence=[C_PURPLE])
    fig_calls.update_layout(**CHART_LAYOUT, height=220, showlegend=False)

    # ---- latency histogram ----
    fig_lat = px.histogram(df, x="latency_ms", nbins=20, color="usecase",
                           color_discrete_sequence=[C_TEAL, C_BLUE, C_AMBER, C_CORAL])
    fig_lat.update_layout(**CHART_LAYOUT, height=220, showlegend=True)

    # ---- token bar ----
    tok_by_uc = df.groupby("usecase")[["prompt_tokens", "completion_tokens"]].sum().reset_index()
    fig_tok = go.Figure()
    fig_tok.add_bar(x=tok_by_uc["usecase"], y=tok_by_uc["prompt_tokens"],
                    name="Prompt", marker_color=C_BLUE)
    fig_tok.add_bar(x=tok_by_uc["usecase"], y=tok_by_uc["completion_tokens"],
                    name="Completion", marker_color=C_TEAL)
    fig_tok.update_layout(**CHART_LAYOUT, height=220, barmode="stack", showlegend=True)

    # ---- cumulative cost ----
    df_cost = df.sort_values("created_at").copy()
    df_cost["cumulative_cost"] = df_cost["cost_usd"].cumsum()
    fig_cost = px.line(df_cost, x="created_at", y="cumulative_cost",
                       color="usecase", color_discrete_sequence=[C_AMBER, C_CORAL, C_PURPLE, C_TEAL])
    fig_cost.update_layout(**CHART_LAYOUT, height=220, showlegend=True)

    # ---- error rate by model ----
    err_df = df.groupby("model").apply(
        lambda g: pd.Series({
            "error_rate": (g["status"] == "error").mean() * 100,
            "calls": len(g),
        }),
        include_groups=False,
    ).reset_index()
    fig_err = px.bar(err_df, x="model", y="error_rate",
                     color_discrete_sequence=[C_RED])
    fig_err.update_layout(**CHART_LAYOUT, height=220, showlegend=False,
                           yaxis_title="Error rate (%)")

    # ---- status pie ----
    status_counts = df["status"].value_counts().reset_index()
    status_counts.columns = ["status", "count"]
    STATUS_COLORS = {"ok": C_GREEN, "error": C_RED, "validation_fail": C_AMBER, "timeout": C_CORAL}
    colors = [STATUS_COLORS.get(s, C_GRAY) for s in status_counts["status"]]
    fig_pie = px.pie(status_counts, names="status", values="count",
                     color_discrete_sequence=colors, hole=0.4)
    fig_pie.update_layout(**CHART_LAYOUT, height=220, showlegend=True)

    # ---- recent traces table ----
    cols = ["trace_id", "usecase", "model", "status", "latency_ms", "total_tokens", "cost_usd", "created_at", "error_message"]
    recent = df[cols].head(20)
    COL_HEADERS = {
        "trace_id": "Trace", "usecase": "Usecase", "model": "Model",
        "status": "Status", "latency_ms": "Latency", "total_tokens": "Tokens",
        "cost_usd": "Cost", "created_at": "Time", "error_message": "Error",
    }
    header_cells = [html.Th(COL_HEADERS.get(c, c), style={"textAlign": "left", "padding": "6px 12px",
                                       "fontSize": "12px", "color": C_GRAY,
                                       "borderBottom": f"1px solid {BORDER}"}) for c in cols]
    rows_html = []
    for _, row in recent.iterrows():
        status_color = {"ok": C_GREEN, "error": C_RED}.get(row["status"], C_AMBER)
        cells = []
        for c in cols:
            val = row[c]
            cell_style = {"padding": "6px 12px", "fontSize": "12px"}
            if c == "trace_id":
                val = str(val)[:8] + "…"
            elif c == "latency_ms":
                val = f"{round(val, 1)}ms"
            elif c == "cost_usd":
                val = f"${round(val, 6)}"
            elif c == "created_at":
                val = str(val)[:19]
            elif c == "status":
                cell_style["color"] = status_color
            elif c == "error_message":
                val = str(val)[:80] + "…" if val and len(str(val)) > 80 else (val or "—")
                cell_style.update({"color": C_RED if val and val != "—" else C_GRAY,
                                   "maxWidth": "300px", "overflow": "hidden",
                                   "textOverflow": "ellipsis", "whiteSpace": "nowrap"})
            cells.append(html.Td(str(val), style=cell_style))
        rows_html.append(html.Tr(cells, style={"borderBottom": f"0.5px solid {BORDER}"}))

    table = html.Table([
        html.Thead(html.Tr(header_cells)),
        html.Tbody(rows_html),
    ], style={"width": "100%", "borderCollapse": "collapse", "overflowX": "auto"})

    return health, cards, fig_calls, fig_lat, fig_tok, fig_cost, fig_err, fig_pie, table


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Dashboard → http://localhost:8050")
    print(f"Reading traces from: {DB_PATH}")
    app.run(debug=True, port=8050)
