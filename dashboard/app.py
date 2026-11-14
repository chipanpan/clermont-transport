"""T2C • Observatoire du réseau — passenger-first punctuality dashboard.

Requires Streamlit >= 1.40 (st.segmented_control).
Recommended .streamlit/config.toml:

    [theme]
    primaryColor = "#ab161a"
    backgroundColor = "#f6f4f2"
    secondaryBackgroundColor = "#ffffff"
    textColor = "#1d2329"
"""
import base64
import math
from datetime import timedelta
from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.cloud import bigquery

# ----------------------------------------------------------------------------
# Config & design tokens
# ----------------------------------------------------------------------------
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
_icon = ASSET_DIR / "logo_t2c.svg"

st.set_page_config(
    page_title="T2C • Observatoire",
    page_icon=str(_icon) if _icon.exists() else "🚋",
    layout="wide",
)

ACCENT = "#ab161a"
INK = "#1d2329"
MUTED = "#5a646e"
LATE = "#ab161a"   # delay
EARLY = "#1f5fa8"  # advance (blue rather than green: color-blind friendly)
DOT_OPACITY = 0.85  # shared by the stop dots and their leader lines so they always match

PERIODS = {"7 jours": 7, "14 jours": 14, "30 jours": 30}
ALL_STOPS = "Toute la ligne"
MIN_CELL = 5  # minimum records for a heatmap cell to be shown
LABEL_ALL_MAX = 10  # lines with more stops only name their key stops in the overview
LABEL_TOP_N = 3     # number of most-delayed stops named in the overview

STATUS_ORDER = ["Early", "On Time", "Slight Delay", "Severe Delay"]
STATUS_LABELS = {
    "Early": "En avance",
    "On Time": "À l’heure",
    "Slight Delay": "Retard",
    "Severe Delay": "Retard important",
}
# Display-only: these MUST mirror the CASE expression in the dbt model fct_transit_performance (seconds).
EARLY_MAX_S = 60     # earlier than -1 min   -> Early
ON_TIME_MAX_S = 300  # up to +5 min          -> On Time
SLIGHT_MAX_S = 600   # up to +10 min         -> Slight Delay, beyond -> Severe Delay
STATUS_RANGES = {
    "Early": f"plus de {EARLY_MAX_S // 60} min d’avance",
    "On Time": f"de −{EARLY_MAX_S // 60} à +{ON_TIME_MAX_S // 60} min",
    "Slight Delay": f"{ON_TIME_MAX_S // 60} à {SLIGHT_MAX_S // 60} min de retard",
    "Severe Delay": f"plus de {SLIGHT_MAX_S // 60} min de retard",
}
STATUS_COLORS = {
    "Early": "#1f5fa8",
    "On Time": "#5f8f7d",
    "Slight Delay": "#e3a53a",
    "Severe Delay": "#7d1014",
}
DAYS_SHORT = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
DAYS_LONG = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
:root{--accent:#ab161a;--ink:#1d2329;--muted:#5a646e;--line:#e3dedb;--bg:#f6f4f2;}
html, body, .stApp, .stApp button, .stApp input, .stApp label, .stApp p, .stApp li
  {font-family:'DM Sans',sans-serif;}
.stApp{background:var(--bg);color:var(--ink);}
.block-container{max-width:1280px;padding:0 2rem 4rem;}
[data-testid="stHeader"]{background:transparent;}
[data-testid="stVerticalBlockBorderWrapper"]{
  background:#fff;border-color:var(--line)!important;border-radius:20px;padding:.8rem .9rem 1.4rem;}
[data-testid="stSelectbox"] label p, [data-testid="stSlider"] label p,
[data-testid="stSegmentedControl"] label p{color:var(--muted);font-size:.8rem;font-weight:600;}
[data-baseweb="select"] > div{border-radius:12px;border-color:var(--line);}
[data-baseweb="select"] > div:focus-within{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent);}
[data-testid="stExpander"]{background:#fff;border:1px solid var(--line);border-radius:16px;}

.topbar{display:flex;align-items:center;gap:16px;padding:22px 0 14px;}
.topbar .grow{flex:1;}
.eyebrow{color:var(--accent);font-size:.75rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;}
.tagline{color:var(--muted);font-size:.95rem;}
.pill-note{border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 14px;
  font-size:.8rem;color:var(--muted);}
.logo-fallback{width:44px;height:44px;border-radius:12px;background:var(--accent);color:#fff;
  font-weight:700;display:flex;align-items:center;justify-content:center;}

.verdict{background:var(--accent);color:#fff;border-radius:20px;padding:32px;min-height:352px;
  position:relative;overflow:hidden;display:flex;flex-direction:column;justify-content:space-between;gap:14px;box-sizing:border-box;}
.verdict .kicker{display:flex;align-items:center;gap:14px;font-size:.95rem;font-weight:700;
  letter-spacing:.08em;text-transform:uppercase;}
.verdict .headline{font-size:2.6rem;line-height:1.1;font-weight:700;letter-spacing:-.03em;}
.verdict .detail{font-size:1rem;line-height:1.5;}
.verdict .foot{font-size:.8rem;border-top:1px solid rgba(255,255,255,.4);padding-top:12px;}
.route-badge{display:inline-flex;align-items:center;justify-content:center;min-width:44px;height:44px;
  padding:0 10px;border-radius:10px;font-weight:700;font-size:1.3rem;letter-spacing:0;
  border:2px solid #fff;box-sizing:border-box;}

.kpi{background:#fff;border:1px solid var(--line);border-radius:20px;padding:20px;
  min-height:164px;margin-bottom:1rem;box-sizing:border-box;position:relative;}
.kpi .label{font-size:.82rem;font-weight:600;color:var(--muted);}
.info{position:static;display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;
  margin-left:8px;border-radius:50%;border:1.5px solid var(--muted);color:var(--muted);font-size:.7rem;
  font-weight:700;cursor:help;vertical-align:middle;outline:none;}
.info:hover,.info:focus{border-color:var(--accent);color:var(--accent);}
.info .tip{visibility:hidden;opacity:0;position:absolute;top:62px;left:12px;right:12px;
  background:var(--ink);color:#fff;font-size:.82rem;font-weight:400;line-height:1.45;padding:10px 12px;
  border-radius:10px;z-index:20;transition:opacity .15s;box-shadow:0 6px 20px rgba(0,0,0,.18);text-align:left;}
.info:hover .tip,.info:focus .tip{visibility:visible;opacity:1;}
.kpi .value{font-size:2.4rem;font-weight:700;letter-spacing:-.03em;margin:6px 0;}
.kpi .foot{font-size:.82rem;color:var(--muted);}
.kpi .foot.good{color:#1f5a3f;font-weight:600;}
.kpi .foot.bad{color:#8e1216;font-weight:600;}

.sec-title{font-size:1.4rem;font-weight:700;letter-spacing:-.02em;margin:.2rem 0 .1rem;}
.sec-sub{font-size:.88rem;color:var(--muted);margin-bottom:.6rem;}
.legend{display:flex;flex-wrap:wrap;align-items:center;gap:4px 20px;}
.legend-item{display:inline-flex;align-items:center;gap:8px;}
.legend-dot{display:inline-block;width:14px;height:14px;border-radius:50%;}
.insight{background:var(--bg);border-radius:12px;padding:12px 16px;font-size:.95rem;margin:.5rem 0 1rem;}

.dist-bar{display:flex;height:40px;border-radius:12px;overflow:hidden;margin:12px 0 16px;}
.dist-row{display:flex;justify-content:space-between;font-size:.95rem;padding:5px 0;}
.range{color:var(--muted);font-size:.8rem;margin-left:8px;}
.swatch{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:8px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def render(markup: str) -> None:
    """Render HTML; whitespace is collapsed so Markdown never sees indented code blocks."""
    st.markdown(" ".join(markup.split()), unsafe_allow_html=True)


def fr(value: float, decimals: int = 1) -> str:
    """French number format (decimal comma)."""
    return f"{value:.{decimals}f}".replace(".", ",")


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


@st.cache_resource
def get_bq_client():
    return bigquery.Client()


@st.cache_data(ttl=86400)
def load_data() -> pd.DataFrame:
    # 60 days = the selected period + the previous one, for "vs période précédente".
    query = """
        SELECT
            trip_id, stop_sequence, trip_headsign, route_short_name, stop_name,
            delay_seconds, delay_minutes, punctuality_status, service_date,
            hour_of_day, actual_arrival_time
        FROM `clermont-transport.t2c_dbt.fct_transit_performance`
        WHERE route_short_name IN ('A', 'B', 'C', 'E1', 'E2')
        AND service_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    """
    df = get_bq_client().query(query).to_dataframe()
    dates = pd.to_datetime(df["service_date"])
    df["service_date"] = dates.dt.date
    df["weekday"] = dates.dt.dayofweek  # 0 = Monday, derived from service_date
    df["hour_of_day"] = pd.to_numeric(df["hour_of_day"], errors="coerce")

    df["trip_headsign"] = df["trip_headsign"].fillna("").astype(str)
    empty = (df["trip_headsign"].str.strip() == "") | (df["trip_headsign"].str.lower() == "none")
    df.loc[empty, "trip_headsign"] = (
        "Destination non précisée (ligne " + df.loc[empty, "route_short_name"].astype(str) + ")"
    )
    return df


@st.cache_data
def load_route_styles() -> dict:
    try:
        routes = pd.read_csv(ASSET_DIR / "routes.txt")
        routes["route_color"] = "#" + routes["route_color"].astype(str).str.strip()
        routes["route_text_color"] = "#" + routes["route_text_color"].astype(str).str.strip()
        return routes.set_index("route_short_name")[["route_color", "route_text_color"]].to_dict("index")
    except Exception:
        return {}


@st.cache_data
def logo_data_uri():
    path = ASSET_DIR / "logo_t2c.svg"
    if not path.exists():
        return None
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()


def route_style(route_styles: dict, route: str) -> dict:
    return route_styles.get(route, {"route_color": ACCENT, "route_text_color": "#ffffff"})


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def compute_kpis(d: pd.DataFrame):
    if d.empty:
        return None
    delay = d["delay_minutes"]
    late = delay[d["punctuality_status"].isin(["Slight Delay", "Severe Delay"])]  # beyond the on-time window
    early = delay[d["punctuality_status"] == "Early"]
    return {
        "n": len(d),
        "p80": delay.quantile(0.8),  # "8 trips out of 10"
        "on_time": (d["punctuality_status"] == "On Time").mean() * 100,
        "avg_late": late.mean() if not late.empty else 0.0,
        "early_pct": (d["punctuality_status"] == "Early").mean() * 100,
        "avg_early": early.abs().mean() if not early.empty else 0.0,
    }


def delta_text(cur, prev, unit, higher_is_better, decimals=0):
    """Returns (text, tone). Arrows + words, so meaning never relies on color alone."""
    if prev is None:
        return "", "muted"
    diff = cur - prev
    if abs(diff) < (0.5 if decimals == 0 else 0.05):
        return "= stable vs période précédente", "muted"
    arrow = "▲" if diff > 0 else "▼"
    tone = "good" if (diff > 0) == higher_is_better else "bad"
    return f"{arrow} {fr(abs(diff), decimals)} {unit} vs période précédente", tone


# ----------------------------------------------------------------------------
# Rendering blocks
# ----------------------------------------------------------------------------
def render_header(last_date):
    logo = logo_data_uri()
    logo_html = (
        f'<img src="{logo}" alt="T2C" style="height:44px;width:auto">'
        if logo
        else '<div class="logo-fallback">T2C</div>'
    )
    render(
        f"""
        <div class="topbar">
          {logo_html}
          <div class="grow">
            <div class="eyebrow">Observatoire du réseau T2C</div>
            <div class="tagline">La ponctualité des lignes fortes et essentielles</div>
          </div>
          <div class="pill-note">Données jusqu’au {last_date.strftime('%d/%m/%Y')}</div>
        </div>
        """
    )


def render_verdict(k, route, headsign, stop, hours, full_hours, style):
    p80 = k["p80"]
    if p80 > 0.5:
        m = math.ceil(p80)
        headline = f"Prévoyez {plural(m, 'minute')} de marge."
        detail = f"Dans 8 trajets sur 10, le bus arrive avec au plus {plural(m, 'minute')} de retard"
    elif p80 < -0.5:
        m = math.ceil(abs(p80))
        headline = "Le bus passe souvent en avance."
        detail = f"Dans 8 trajets sur 10, le bus passe avec au moins {plural(m, 'minute')} d’avance : soyez à l’arrêt en avance"
    else:
        headline = "Le bus est en général à l’heure."
        detail = "Dans 8 trajets sur 10, l’écart à l’horaire est inférieur à 30 secondes"

    where = "sur l’ensemble de la ligne" if stop == ALL_STOPS else f"à l’arrêt {escape(stop)}"
    when = "sur toute la journée" if hours == full_hours else f"de {hours[0]} h à {hours[1]} h"
    render(
        f"""
        <div class="verdict">
          <div class="kicker">
            <span class="route-badge" style="background:{style['route_color']};color:{style['route_text_color']}">{escape(route)}</span>
            <span>{escape(headsign)}</span>
          </div>
          <div class="headline">{headline}</div>
          <div class="detail">{detail}, {where}, {when}.</div>
          <div class="foot">Basé sur les passages réels enregistrés.</div>
        </div>
        """
    )


def kpi_card(label, value, foot, tone="muted", info=None):
    # `info`: plain-text explanation shown in a pop-up on hover, keyboard focus or tap.
    icon = (
        f'<span class="info" tabindex="0" role="note" aria-label="{escape(info)}">i'
        f'<span class="tip" aria-hidden="true">{escape(info)}</span></span>'
        if info else ""
    )
    render(
        f"""
        <div class="kpi">
          <div class="label">{label}{icon}</div>
          <div class="value">{value}</div>
          <div class="foot {tone}">{foot}</div>
        </div>
        """
    )


INFO_ON_TIME = (
    f"Le bus passe entre {EARLY_MAX_S // 60} min avant et {ON_TIME_MAX_S // 60} min après l’horaire prévu. "    
)
INFO_LATE = (
    f"Le bus passe plus de {ON_TIME_MAX_S // 60} min après l’horaire prévu. "
    "Le chiffre est le retard moyen de ces seuls passages."
)
INFO_EARLY = (
    f"Le bus passe plus de {EARLY_MAX_S // 60} min avant l’horaire prévu. "
)


def render_kpis(k, prev):
    p = prev or {}
    c1, c2 = st.columns(2)
    with c1:
        foot, tone = delta_text(k["on_time"], p.get("on_time"), "pts", True, 0)
        kpi_card("À l’heure", f"{fr(k['on_time'], 0)}&nbsp;%", foot or "Part des passages à l’heure", tone, INFO_ON_TIME)
    with c2:
        foot, tone = delta_text(k["avg_late"], p.get("avg_late"), "min", False, 1)
        kpi_card("Retard moyen, quand le bus est en retard", f"+{fr(k['avg_late'])}&nbsp;min", foot or f"Au-delà de {ON_TIME_MAX_S // 60} min de retard", tone, INFO_LATE)
    c3, c4 = st.columns(2)
    with c3:
        kpi_card(
            "Bus partis en avance",
            f"{fr(k['early_pct'], 0)}&nbsp;%",
            f"En moyenne {fr(k['avg_early'])} min avant l’horaire" if k["early_pct"] > 0 else "Aucun passage en avance",
            info=INFO_EARLY,
        )
    with c4:
        warn = "Peu de données : à interpréter avec prudence" if k["n"] < 30 else "Plus il est élevé, plus c’est fiable"
        kpi_card("Passages analysés", f"{k['n']:,}".replace(",", "&nbsp;"), warn)


def itinerary_stats(d: pd.DataFrame) -> pd.DataFrame:
    g = d.groupby("stop_name").agg(
        stop_sequence=("stop_sequence", "mean"),
        p80=("delay_minutes", lambda x: x.quantile(0.8)),
        n=("delay_minutes", "size"),
    ).reset_index()
    g = g.sort_values("stop_sequence").reset_index(drop=True)
    g["pos"] = range(len(g))
    g["p80"] = g["p80"].fillna(0.0)
    return g


def itinerary_figure(stops: pd.DataFrame, selected: str) -> go.Figure:
    n = len(stops)
    colors = [LATE if v >= 0 else EARLY for v in stops["p80"]]
    sizes = (stops["p80"].abs() * 7).clip(lower=11, upper=38)

    # Which stops get a name. Zoomed view or short line: all of them. Overview of a
    # long line: first, last and the most-delayed stops only (others: hover).
    thinned = selected == ALL_STOPS and n > LABEL_ALL_MAX
    if thinned:
        top = stops[stops["p80"] > 0].nlargest(LABEL_TOP_N, "p80")["pos"]
        labeled = stops[stops["pos"].isin({0, n - 1} | set(top))]
    else:
        labeled = stops
    labeled = labeled.reset_index(drop=True)
    labeled["color"] = labeled["p80"].map(lambda v: LATE if v >= 0 else EARLY)
    labels = labeled["stop_name"].astype(str)
    if thinned:  # fewer names, so there is room to show the delay too
        values = labeled["p80"].map(lambda v: f"{v:+.1f}".replace(".", ",") + " min")
        labels = labels + "<br>" + values

    label_y = 0.32  # names alternate above (+) / below (-) the line to limit overlaps
    side = labeled.index.map(lambda i: 1 if i % 2 == 0 else -1)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=stops["pos"], y=[0] * n, mode="lines",
        line=dict(color="#d9d3cf", width=6), hoverinfo="skip", showlegend=False,
    ))

    # Leader lines from each dot to its name, in the overview of a long line only
    # (drawn before the dots, so they sit underneath).
    for color in (LATE, EARLY) if thinned else ():  # only needed when names are sparse
        sub = labeled[labeled["color"] == color]
        if sub.empty:
            continue
        xs, ys = [], []
        for idx, pos, p80 in zip(sub.index, sub["pos"], sub["p80"]):
            # Start at the dot's edge (not its centre) so the line doesn't show through the translucent dot.
            edge = (row_size(p80) / 2) / 113.0  # ~113 px per y-unit at height=270
            xs += [pos, pos, None]
            ys += [side[idx] * edge, side[idx] * (label_y - 0.02), None]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", line=dict(color=color, width=2),
            opacity=DOT_OPACITY, hoverinfo="skip", showlegend=False,
        ))

    fig.add_trace(go.Scatter(
        x=stops["pos"], y=[0] * n, mode="markers", showlegend=False,
        marker=dict(size=sizes, color=colors, opacity=DOT_OPACITY, line=dict(color="#ffffff", width=2)),
        customdata=stops[["stop_name", "p80"]].to_numpy(),
        hovertemplate="<b>%{customdata[0]}</b><br>Retard 8 fois sur 10 : %{customdata[1]:+.1f} min<extra></extra>",
    ))

    # Names. The terminus labels are anchored inward (first -> grows right, last -> grows left)
    # so they are never cut off at the chart edges.
    anchor = labeled["pos"].map(lambda p: "right" if p == 0 else ("left" if p == n - 1 else "center"))
    for vert, sgn in (("top", 1), ("bottom", -1)):
        for horiz in ("center", "right", "left"):
            mask = (side == sgn) & (anchor == horiz).to_numpy()
            if not mask.any():
                continue
            fig.add_trace(go.Scatter(
                x=labeled.loc[mask, "pos"], y=[sgn * label_y] * int(mask.sum()), mode="text",
                text=labels[mask], textposition=f"{vert} {horiz}",
                textfont=dict(size=12, color=INK), cliponaxis=False,
                hoverinfo="skip", showlegend=False,
            ))

    x_range = [-0.7, n - 0.3]
    if selected != ALL_STOPS and (stops["stop_name"] == selected).any():
        row = stops[stops["stop_name"] == selected].iloc[0]
        fig.add_trace(go.Scatter(
            x=[row["pos"]], y=[0], mode="markers", hoverinfo="skip", showlegend=False,
            marker=dict(size=min(row_size(row["p80"]) + 14, 56), color="rgba(0,0,0,0)",
                        line=dict(color=INK, width=3)),
        ))
        x_range = [max(-0.7, row["pos"] - 3.5), min(n - 0.3, row["pos"] + 3.5)]

    fig.update_layout(
        height=270, margin=dict(t=10, b=10, l=24, r=24),
        xaxis=dict(visible=False, range=x_range, fixedrange=True),
        yaxis=dict(visible=False, range=[-1.1, 1.1], fixedrange=True),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif"),
        hoverlabel=dict(font_family="DM Sans, sans-serif"),
    )
    return fig


def row_size(p80: float) -> float:
    return min(max(abs(p80) * 7, 11), 38)


def build_up_sentence(stops: pd.DataFrame):
    if len(stops) < 2:
        return None
    diffs = stops["p80"].diff()
    if diffs.dropna().empty:
        return None
    i = diffs.idxmax()
    if diffs[i] < 0.5:
        return None
    a, b = escape(stops.loc[i - 1, "stop_name"]), escape(stops.loc[i, "stop_name"])
    return f"Le retard se forme surtout entre <b>{a}</b> et <b>{b}</b> (+{fr(diffs[i])} min)."


def heatmap(d: pd.DataFrame):
    g = d.dropna(subset=["hour_of_day"]).copy()
    g["hour_of_day"] = g["hour_of_day"].astype(int)
    g = g.groupby(["weekday", "hour_of_day"]).agg(
        p80=("delay_minutes", lambda x: x.quantile(0.8)),
        n=("delay_minutes", "size"),
    ).reset_index()
    g.loc[g["n"] < MIN_CELL, "p80"] = float("nan")  # too few records to be meaningful
    pivot = g.pivot(index="weekday", columns="hour_of_day", values="p80").reindex(range(7))
    # Plotly sizes a numeric-axis cell by the gap to its neighbours, so a missing hour
    # (e.g. no service 2 h-3 h) made the neighbouring cells twice as wide. One column per hour fixes that.
    pivot = pivot.reindex(columns=range(int(pivot.columns.min()), int(pivot.columns.max()) + 1))
    if pivot.dropna(how="all").empty:
        return None, None

    hours = list(pivot.columns)
    zmax = max(2.0, float(pivot.max().max()))
    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=hours, y=DAYS_SHORT, xgap=3, ygap=3, zmin=0, zmax=zmax,
        colorscale=[[0, "#f4e6e6"], [0.25, "#e6bcbd"], [0.5, "#d38588"], [0.75, "#b8484d"], [1, "#8e1216"]],
        showscale=False, hoverongaps=False,
        hovertemplate="%{y} %{x}<br>Retard 8 fois sur 10 : %{z:+.1f} min<extra></extra>",
    ))
    fig.update_layout(
        height=330, margin=dict(t=10, b=10, l=10, r=10),
        xaxis=dict(tickmode="array", tickvals=hours, ticktext=[f"{h} h" for h in hours],
                   tickangle=-45, automargin=True, side="bottom", fixedrange=True),
        yaxis=dict(autorange="reversed", fixedrange=True),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", color=INK),
    )

    valid = g.dropna(subset=["p80"])
    sentence = None
    if len(valid) >= 4:
        worst = valid.loc[valid["p80"].idxmax()]
        best_hour = int(valid.groupby("hour_of_day")["p80"].mean().idxmin())
        if worst["p80"] > 0.5:
            sentence = (
                f"<b>À retenir :</b> évitez le {DAYS_LONG[int(worst['weekday'])]} vers "
                f"{int(worst['hour_of_day'])} h (retard typique +{fr(worst['p80'])} min). "
                f"{best_hour} h est l’heure la plus régulière."
            )
        else:
            sentence = f"<b>À retenir :</b> aucun créneau particulièrement difficile ; {best_hour} h est le plus régulier."
    return fig, sentence


def render_distribution(d: pd.DataFrame):
    shares = d["punctuality_status"].value_counts(normalize=True) * 100
    segments, rows = "", ""
    for status in STATUS_ORDER:
        pct = float(shares.get(status, 0.0))
        color, label = STATUS_COLORS[status], STATUS_LABELS[status]
        if pct > 0:
            segments += f'<div style="width:{pct:.2f}%;background:{color}"></div>'
        rows += (
            f'<div class="dist-row"><span><span class="swatch" style="background:{color}"></span>{label}'
            f'<span class="range">{STATUS_RANGES[status]}</span></span>'
            f"<b>{fr(pct, 0)}&nbsp;%</b></div>"
        )
    summary = ", ".join(f"{fr(float(shares.get(s, 0.0)), 0)} % {STATUS_LABELS[s].lower()}" for s in STATUS_ORDER)
    render(f'<div class="dist-bar" role="img" aria-label="{summary}">{segments}</div>{rows}')


# ----------------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------------
def main():
    df = load_data()
    route_styles = load_route_styles()
    if df.empty:
        st.warning("Aucune donnée dans `fct_transit_performance` pour le moment. Vérifiez l’ingestion et `dbt run`.")
        return

    min_date, max_date = df["service_date"].min(), df["service_date"].max()
    render_header(max_date)

    # ---- Journey picker (one card). Widgets run top-to-bottom, so dependent
    # filters (route -> direction -> stop -> hours) are created in that order,
    # while `line_box` keeps the line selector visually first.
    with st.container(border=True):
        line_box = st.container()
        c_period, c_dir, c_stop, c_hours = st.columns([1.3, 1.3, 1.3, 1.3])

        with c_period:
            period_label = st.segmented_control(
                "Période", list(PERIODS), default="30 jours", key="period"
            ) or "30 jours"
        n_days = PERIODS[period_label]
        start = max_date - timedelta(days=n_days - 1)
        prev_start, prev_end = start - timedelta(days=n_days), start - timedelta(days=1)
        period_df = df[(df["service_date"] >= start) & (df["service_date"] <= max_date)]
        prev_df = df[(df["service_date"] >= prev_start) & (df["service_date"] <= prev_end)]
        has_prev = prev_start >= min_date  # only compare when the previous period is fully covered

        # Widget options come from ALL loaded data, not the selected period: Streamlit
        # treats a widget whose options change as a new widget and resets it, which is
        # what used to wipe direction/stop/hours when switching period.
        routes = sorted(df["route_short_name"].astype(str).unique().tolist())
        if not routes:
            st.warning("Aucune donnée disponible.")
            return
        with line_box:
            route = st.segmented_control("Ligne", routes, default=routes[0], key="route") or routes[0]
        all_route_df = df[df["route_short_name"] == route]  # full history, for stable options

        with c_dir:
            headsigns = sorted(all_route_df["trip_headsign"].dropna().unique().tolist())
            headsign = st.selectbox("Direction", headsigns or ["—"])
        all_base_df = all_route_df[all_route_df["trip_headsign"] == headsign]
        base_df = period_df[(period_df["route_short_name"] == route) & (period_df["trip_headsign"] == headsign)]
        prev_base = prev_df[(prev_df["route_short_name"] == route) & (prev_df["trip_headsign"] == headsign)]

        with c_stop:
            # Stops ordered along the line rather than alphabetically.
            stop_order = all_base_df.groupby("stop_name")["stop_sequence"].mean().sort_values().index.tolist()
            stop = st.selectbox("Mon arrêt", [ALL_STOPS] + stop_order)

        with c_hours:
            hour_vals = all_base_df["hour_of_day"].dropna().astype(int)
            if hour_vals.empty:
                st.caption("Pas de données horaires.")
                return
            # The slider works in clock times: 7 -> 9 means 7:00 up to (not including) 9:00,
            # i.e. the 7 h and 8 h buckets. So the upper bound goes one hour past the last bucket.
            h_start, h_end = int(hour_vals.min()), int(hour_vals.max()) + 1
            full_hours = (h_start, h_end)
            hours = st.slider("Plage horaire", h_start, h_end, full_hours, step=1, format="%d h")

    if hours[0] == hours[1]:
        st.info("Choisissez une plage horaire d’au moins une heure.")
        return

    # ---- Filtered frames
    def in_hours(d):
        return d[(d["hour_of_day"] >= hours[0]) & (d["hour_of_day"] < hours[1])]

    def at_stop(d):
        return d if stop == ALL_STOPS else d[d["stop_name"] == stop]

    line_df = in_hours(base_df)                   # whole line, selected hours
    visual_df = at_stop(line_df)                  # + selected stop
    heat_df = at_stop(base_df)                    # all hours, so riders can pick the best time
    prev_visual = at_stop(in_hours(prev_base)) if has_prev else pd.DataFrame()

    kpis = compute_kpis(visual_df)
    if kpis is None:
        st.info("Aucun passage pour cette sélection sur la période choisie. Essayez une période plus longue, une plage horaire plus large ou un autre arrêt.")
        return
    prev_kpis = compute_kpis(prev_visual) if has_prev else None

    st.write("")  # breathing room

    # ---- Verdict + KPIs
    col_verdict, col_kpis = st.columns([5, 7], gap="medium")
    with col_verdict:
        render_verdict(kpis, route, headsign, stop, hours, full_hours, route_style(route_styles, route))
    with col_kpis:
        render_kpis(kpis, prev_kpis)

    # ---- Where delay builds up along the line
    render('<div style="height:1.25rem"></div>')
    stops = itinerary_stats(line_df)
    with st.container(border=True):
        render(
            f'''
            <div class="sec-title">Où le retard se crée sur la ligne</div>
            <div class="sec-sub legend">
              <span class="legend-item"><span class="legend-dot" style="background:{LATE};opacity:{DOT_OPACITY}"></span>Retard</span>
              <span class="legend-item"><span class="legend-dot" style="background:{EARLY};opacity:{DOT_OPACITY}"></span>Avance</span>
              <span>Plus le point est gros, plus l’écart est marqué.</span>
            </div>
            '''
        )
        st.plotly_chart(itinerary_figure(stops, stop), use_container_width=True,
                        config={"displayModeBar": False})
        if stop == ALL_STOPS and len(stops) > LABEL_ALL_MAX:
            st.caption("Seuls les arrêts clés sont nommés (terminus et plus forts retards). "
                       "Survolez un point pour voir les autres, ou choisissez « Mon arrêt » pour zoomer.")
        sentence = build_up_sentence(stops)
        if sentence:
            render(f'<div class="insight"><b>À retenir :</b> {sentence}</div>')

    # ---- Heatmap + distribution
    col_heat, col_dist = st.columns([7, 5], gap="medium")
    with col_heat:
        with st.container(border=True):
            render('<div class="sec-title">Quel est le meilleur moment pour voyager ?</div>'
                   '<div class="sec-sub">Retard typique (8 fois sur 10) selon le jour et l’heure. Plus foncé = plus de retard.</div>')
            fig_heat, takeaway = heatmap(heat_df)
            if fig_heat is None:
                st.info("Pas assez de données pour afficher ce graphique.")
            else:
                st.plotly_chart(fig_heat, use_container_width=True, config={"displayModeBar": False})
                if takeaway:
                    render(f'<div class="insight">{takeaway}</div>')
    with col_dist:
        with st.container(border=True):
            render('<div class="sec-title">Comment se passent vos trajets</div>'
                   '<div class="sec-sub">Répartition des passages selon leur ponctualité.</div>')
            render_distribution(visual_df)

    # ---- Details
    with st.expander("Voir les données détaillées et la méthode de calcul"):
        st.markdown(
            "- **8 trajets sur 10** : 80ᵉ centile du retard.\n"
            f"- **Retard moyen** : calculé sur les passages au-delà de {ON_TIME_MAX_S // 60} min de retard.\n"
            f"- **Comparaison** : avec les {n_days} jours précédents, uniquement si cette période est entièrement couverte.\n"
            f"- **Carte thermique** : les créneaux de moins de {MIN_CELL} passages sont masqués."
        )
        st.dataframe(
            visual_df[["route_short_name", "trip_headsign", "stop_name",
                       "actual_arrival_time", "delay_minutes", "punctuality_status"]]
            .sort_values("actual_arrival_time", ascending=True)
            .assign(punctuality_status=lambda x: x["punctuality_status"].replace(STATUS_LABELS))
            .rename(columns={
                "route_short_name": "Ligne", "trip_headsign": "Direction", "stop_name": "Arrêt",
                "actual_arrival_time": "Heure réelle",
                "delay_minutes": "Écart (min)", "punctuality_status": "Statut",
            }),
            hide_index=True, use_container_width=True,
        )


try:
    main()
except Exception as e:
    st.error(f"Impossible de charger les données depuis BigQuery : {e}")