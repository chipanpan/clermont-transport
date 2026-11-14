import streamlit as st
from google.cloud import bigquery
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
from html import escape

# Page configuration
st.set_page_config(
    page_title="T2C • Observatoire",
    page_icon="assets/logo_t2c.svg",
    layout="wide"
)

ACCENT = "#ab161a"
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');

    :root {{
        --accent: {ACCENT};
        --ink: #1d2329;
        --muted: #68727d;
        --line: #e8ebee;
        --soft: #f7f8f9;
    }}
    .stApp {{ background: #fff; color: var(--ink); }}
    .block-container {{ max-width: 1440px; padding: 2.5rem 3.5rem 4rem; }}
    html, body, [class*="css"] {{ font-family: 'DM Sans', sans-serif; }}
    h1, h2, h3, h4 {{ color: var(--ink); letter-spacing: -0.035em; }}
    h1 {{ font-size: 2.5rem !important; font-weight: 700 !important; margin-top: .2rem !important; }}
    h2 {{ font-size: 1.45rem !important; }}
    h3 {{ font-size: 1.1rem !important; }}
    [data-testid="stMetric"] {{
        background: var(--soft); border: 1px solid var(--line);
        border-radius: 14px; padding: 1rem 1.1rem;
    }}
    [data-testid="stMetricLabel"] {{ color: var(--muted); font-size: .78rem; }}
    [data-testid="stMetricValue"] {{ color: var(--ink); font-weight: 700; }}
    [data-testid="stSelectbox"] label, [data-testid="stDateInput"] label,
    [data-testid="stSlider"] label {{ color: var(--muted); font-size: .78rem; font-weight: 600; }}
    [data-baseweb="select"] > div, [data-testid="stDateInput"] input {{
        border-color: var(--line); border-radius: 10px; background: #fff;
    }}
    [data-baseweb="select"] > div:focus-within {{ border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }}
    [data-testid="stExpander"] {{ border: 1px solid var(--line); border-radius: 12px; }}
    hr {{ border: 0; border-top: 1px solid var(--line); margin: 2rem 0; }}
    .eyebrow {{ color: var(--accent); font-size: .72rem; font-weight: 700; letter-spacing: .14em; line-height: 1.4; padding-top: .15rem; text-transform: uppercase; }}
    [data-testid="stImage"] {{
        align-items: center; display: flex; justify-content: center;
        overflow: visible; width: 100%;
    }}
    [data-testid="stImage"] img {{
        display: block; height: auto; max-height: none; max-width: 100%;
        object-fit: contain; object-position: center; width: auto;
    }}
    .subtitle {{ color: var(--muted); font-size: 1rem; margin-top: -.8rem; }}
    .route-panel {{ background: var(--soft); border: 1px solid var(--line); border-radius: 18px; padding: 1.2rem 1.35rem .35rem; margin: 1rem 0 1.5rem; }}
    .route-label {{ color: var(--ink); font-size: .8rem; font-weight: 700; margin-bottom: .75rem; }}
    .route-grid {{ display: flex; flex-wrap: wrap; gap: .55rem; margin-bottom: .8rem; }}
    .route-chip {{ align-items: center; display: inline-flex; gap: .5rem; color: #68727d; font-size: .78rem; font-weight: 600; }}
    .route-icon {{ align-items: center; border-radius: 6px; display: inline-flex; font-size: .73rem; font-weight: 700; height: 28px; justify-content: center; min-width: 28px; padding: 0 5px; }}
    .section-kicker {{ color: var(--muted); font-size: .75rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize BigQuery client
@st.cache_resource
def get_bq_client():
    return bigquery.Client()

client = get_bq_client()

# Query data and safely handle null headsigns without losing delay records
@st.cache_data(ttl=86400)
def load_data():
    query = """
        SELECT 
            trip_id,
            stop_sequence,
            trip_headsign,
            route_short_name,
            stop_name,
            delay_seconds,
            delay_minutes,
            punctuality_status,
            service_date,
            hour_of_day,
            day_of_week,
            actual_arrival_time,
        FROM `clermont-transport.t2c_dbt.fct_transit_performance`
        WHERE route_short_name IN ('A', 'B', 'C', 'E1', 'E2')
        AND service_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    """
    df = client.query(query).to_dataframe()
    df['service_date'] = pd.to_datetime(df['service_date']).dt.date
    
    # Safe fallback for null/empty headsigns
    df["trip_headsign"] = df["trip_headsign"].fillna("").astype(str)
    empty_mask = (df["trip_headsign"].str.strip() == "") | (df["trip_headsign"].str.lower() == "none")
    df.loc[empty_mask, "trip_headsign"] = "Unspecified Destination (Route " + df.loc[empty_mask, "route_short_name"].astype(str) + ")"
    
    return df

@st.cache_data
def load_route_styles():
    routes = pd.read_csv(ASSET_DIR / "routes.txt")
    routes["route_color"] = "#" + routes["route_color"].astype(str).str.strip()
    routes["route_text_color"] = "#" + routes["route_text_color"].astype(str).str.strip()
    return routes.set_index("route_short_name")[["route_color", "route_text_color"]].to_dict("index")

# App Header
header_logo, header_copy = st.columns([1, 5], vertical_alignment="center")
with header_logo:
    st.image(str(ASSET_DIR / "logo_t2c.svg"), width=68)
with header_copy:
    st.markdown('<div class="eyebrow">Mobilité • Clermont Auvergne</div>', unsafe_allow_html=True)
    st.title("Observatoire du réseau")
    st.markdown('<div class="subtitle">La ponctualité des lignes T2C, en un coup d’œil.</div>', unsafe_allow_html=True)

try:
    df = load_data()
    route_styles = load_route_styles()

    if df.empty:
        st.warning("No data found in `fct_transit_performance` yet. Make sure your ingestion and `dbt run` have populated data!")
    else:
        min_date = df["service_date"].min()
        max_date = df["service_date"].max()

        st.markdown("---")

        # ==========================================
        # TOP SECTION: Master Itinerary Map & Selectors
        # ==========================================
        date_range = st.date_input(
            "Date Range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )
        hour_filter_placeholder = st.empty()

        base_filtered_df = df.copy()
        if len(date_range) == 2:
            start_date, end_date = date_range
            base_filtered_df = base_filtered_df[
                (base_filtered_df["service_date"] >= start_date) & 
                (base_filtered_df["service_date"] <= end_date)
            ]

        st.markdown('<div class="section-kicker">Explorer le réseau</div>', unsafe_allow_html=True)
        st.subheader("Itinéraire et ponctualité")
        
        available_routes = sorted(base_filtered_df["route_short_name"].unique().astype(str).tolist())
        
        if not available_routes:
            st.warning("No data available for the selected date range and status filters.")
        else:
            route_chips = []
            for route in available_routes:
                style = route_styles.get(route, {"route_color": ACCENT, "route_text_color": "#ffffff"})
                route_chips.append(
                    f'<span class="route-chip"><span class="route-icon" '
                    f'style="background:{style["route_color"]};color:{style["route_text_color"]}">'
                    f'{escape(route)}</span></span>'
                )
            st.markdown(
                '<div class="route-panel"><div class="route-label">Lignes disponibles</div>'
                f'<div class="route-grid">{"".join(route_chips)}</div></div>',
                unsafe_allow_html=True,
            )
            col_route, col_headsign = st.columns(2)
            with col_route:
                chosen_route = st.selectbox(
                    "Sélectionner une ligne",
                    options=available_routes,
                    format_func=lambda route: f"{route}",
                )
            
            route_df = base_filtered_df[base_filtered_df["route_short_name"] == chosen_route]
            available_headsigns = sorted(route_df["trip_headsign"].dropna().unique().tolist())
            
            with col_headsign:
                chosen_headsign = st.selectbox(
                    "Sélectionner une destination",
                    options=available_headsigns if available_headsigns else ["No destinations available"]
                )
            
            # Master Filtered DataFrame for the rest of the dashboard
            filtered_df = route_df[route_df["trip_headsign"] == chosen_headsign]
            stop_options = sorted(filtered_df["stop_name"].dropna().unique().tolist())
            selected_stop = st.selectbox(
                "Sélectionner un arrêt",
                options=["All"] + stop_options,
            )
            
            # Aggregate stats grouped ONLY by stop_name, taking the avg stop_sequence for sorting
            route_itinerary_df = filtered_df.groupby("stop_name").agg(
                stop_sequence=('stop_sequence', 'mean'),  # Keeps the aveerage sequence for ordering
                delay_main_kpi=('delay_minutes', lambda x: x.quantile(0.8)), # Net delay is calculated as the median of all delays (positive and negative)
                avg_delay_pos=('delay_minutes', lambda x: x[x > 0].mean() if (x > 0).any() else 0.0),
                avg_earliness_neg=('delay_minutes', lambda x: x[x < 0].abs().mean() if (x < 0).any() else 0.0),
                early_count=('punctuality_status', lambda x: (x == 'Early').sum()),
                total_count=('punctuality_status', 'size')
            ).reset_index()

            # Prevent NaN values from breaking Plotly marker sizes and colors
            route_itinerary_df["delay_main_kpi"] = route_itinerary_df["delay_main_kpi"].fillna(0.0)
            route_itinerary_df["avg_delay_pos"] = route_itinerary_df["avg_delay_pos"].fillna(0.0)
            route_itinerary_df["avg_earliness_neg"] = route_itinerary_df["avg_earliness_neg"].fillna(0.0)
            route_itinerary_df["early_pct"] = (route_itinerary_df["early_count"] / route_itinerary_df["total_count"]).fillna(0.0) * 100

            # Sort strictly by the stop sequence order along the line
            route_itinerary_df = route_itinerary_df.sort_values(by="stop_sequence").reset_index(drop=True)
            route_itinerary_df["itinerary_position"] = range(len(route_itinerary_df))
            
            route_itinerary_df["abs_delay"] = route_itinerary_df["delay_main_kpi"].abs()
            route_itinerary_df["marker_size"] = (route_itinerary_df["abs_delay"] * 6).clip(lower=10, upper=45)
            route_itinerary_df["marker_color"] = route_itinerary_df["delay_main_kpi"].apply(
                lambda x: "#a72225" if x >= 0 else "#2E8B57"
            )

            fig_itinerary = go.Figure()
            selected_route_style = route_styles.get(
                chosen_route,
                {"route_color": ACCENT, "route_text_color": "#ffffff"},
            )

            if not route_itinerary_df.empty:
                fig_itinerary.add_trace(go.Scatter(
                    x=route_itinerary_df["itinerary_position"],
                    y=[0] * len(route_itinerary_df),
                    mode="lines",
                    line=dict(color="#cccccc", width=4),
                    showlegend=False,
                    hoverinfo="skip"
                ))

                fig_itinerary.add_trace(go.Scatter(
                    x=route_itinerary_df["itinerary_position"],
                    y=[0] * len(route_itinerary_df),
                    mode="markers+text",
                    showlegend=False,
                    marker=dict(
                        size=route_itinerary_df["marker_size"],
                        color=route_itinerary_df["marker_color"],
                        opacity=0.85,
                        line=dict(color="#ffffff", width=1.5)
                    ),
                    text=route_itinerary_df["stop_name"],
                    textposition="top center",
                    hovertemplate=(
                        "<b>%{text}</b><br>"
                        #"Sequence: %{x}<br>" 
                        "Delay Trend: %{customdata[0]:.2f} min<br>"
                        "Avg Delay (Late): +%{customdata[1]:.2f} min<br>"
                        "Avg Earliness (Early): -%{customdata[2]:.2f} min<br>"
                        "Early Risk: %{customdata[3]:.1f}%<extra></extra>"
                    ),
                    customdata=route_itinerary_df[
                        ["delay_main_kpi", "avg_delay_pos", "avg_earliness_neg", "early_pct"]
                    ]
                ))

                if selected_stop != "All":
                    selected_stop_df = route_itinerary_df[
                        route_itinerary_df["stop_name"] == selected_stop
                    ]
                    if not selected_stop_df.empty:
                        selected_position = int(
                            selected_stop_df["itinerary_position"].iloc[0]
                        )
                        fig_itinerary.add_trace(go.Scatter(
                            x=[selected_position],
                            y=[0],
                            mode="markers",
                            marker=dict(
                                size=selected_stop_df["marker_size"].iloc[0],
                                color=selected_stop_df["marker_color"].iloc[0],
                                line=dict(
                                    color="#F0D315",
                                    width=3,
                                ),
                            ),
                            name=selected_stop,
                            hoverinfo="skip",
                            showlegend=False,
                        ))

                fig_itinerary.add_trace(go.Scatter(
                    x=[None],
                    y=[None],
                    mode="markers",
                    marker=dict(size=10, color="#a72225"),
                    name="Late tendency"
                ))
                fig_itinerary.add_trace(go.Scatter(
                    x=[None],
                    y=[None],
                    mode="markers",
                    marker=dict(size=10, color="#2E8B57"),
                    name="Early tendency"
                ))

            fig_itinerary.update_layout(
                title="",
                xaxis=dict(
                    showgrid=False,
                    zeroline=False,
                    showticklabels=False,
                    range=(
                        [
                            max(0, selected_position - 3),
                            min(
                                len(route_itinerary_df) - 1,
                                selected_position + 3,
                            ),
                        ]
                        if selected_stop != "All"
                        and not route_itinerary_df[
                            route_itinerary_df["stop_name"] == selected_stop
                        ].empty
                        else None
                    ),
                ),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-1.5, 1.5]),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                height=280,
                margin=dict(t=55, b=20, l=20, r=20),
                annotations=[
                    dict(
                        x=0,
                        y=1.14,
                        xref="paper",
                        yref="paper",
                        xanchor="left",
                        yanchor="middle",
                        text=f"<b>{escape(chosen_route)}</b>",
                        showarrow=False,
                        bgcolor=selected_route_style["route_color"],
                        bordercolor=selected_route_style["route_color"],
                        borderpad=6,
                        font=dict(
                            color=selected_route_style["route_text_color"],
                            size=13,
                        ),
                    ),
                    dict(
                        x=0,
                        y=1.14,
                        xref="paper",
                        yref="paper",
                        xanchor="left",
                        yanchor="middle",
                        xshift=42,
                        text=f"<b>{escape(chosen_headsign)}</b>",
                        showarrow=False,
                        font=dict(color="#1d2329", size=16),
                    ),
                ],
            )
            st.plotly_chart(fig_itinerary, use_container_width=True)

            delayed_stops = route_itinerary_df.nlargest(3, "delay_main_kpi")
            early_stops = route_itinerary_df.nsmallest(3, "delay_main_kpi")
            callout_col_late, callout_col_early = st.columns(2)


            if selected_stop == "All":
                alert_delay_main_kpi = filtered_df["delay_minutes"].quantile(0.8)
                alert_location = "on this line"
            else:
                selected_stop_kpi = route_itinerary_df[
                    route_itinerary_df["stop_name"] == selected_stop
                ]["delay_main_kpi"]
                alert_delay_main_kpi = (
                    selected_stop_kpi.iloc[0] if not selected_stop_kpi.empty else None
                )
                alert_location = f"at {selected_stop}"

            if pd.notna(alert_delay_main_kpi):
                if alert_delay_main_kpi > 0:
                    alert_text = (
                        f"80% of the time, passengers experience a delay of "
                        f"+{alert_delay_main_kpi:.2f} minutes {alert_location}."
                    )
                elif alert_delay_main_kpi < 0:
                    alert_text = (
                        f"80% of the time, passengers experience an advance of "
                        f"{abs(alert_delay_main_kpi):.2f} minutes {alert_location}."
                    )
                else:
                    alert_text = (
                        "80% of the time, passengers experience no delay "
                        f"{alert_location}."
                    )
                st.info(alert_text)

        hour_options = sorted(filtered_df["hour_of_day"].dropna().unique().tolist())
        with hour_filter_placeholder.container():
            if hour_options:
                hour_min = int(min(hour_options))
                hour_max = int(max(hour_options))
                selected_hour_range = st.slider(
                    "Plage horaire",
                    min_value=hour_min,
                    max_value=hour_max,
                    value=(hour_min, hour_max),
                    step=1
                )
            else:
                st.info("No hour data available for the selected line and destination.")
                selected_hour_range = None

        stop_mask = (
            filtered_df["stop_name"].eq(selected_stop)
            if selected_stop != "All"
            else pd.Series(True, index=filtered_df.index)
        )
        hour_mask = (
            filtered_df["hour_of_day"].between(
                selected_hour_range[0],
                selected_hour_range[1]
            )
            if selected_hour_range is not None
            else pd.Series(False, index=filtered_df.index)
        )
        visuals_filtered_df = filtered_df[stop_mask & hour_mask]

        st.markdown("---")

        # ==========================================
        # LOWER SECTION: KPIs & Visuals (Filtered by Route, Headsign, Stop & Hour)
        # ==========================================
        # Metric Calculations
        late_trips = visuals_filtered_df[visuals_filtered_df["delay_minutes"] > 0]
        early_trips = visuals_filtered_df[
            visuals_filtered_df["punctuality_status"] == "Early"
        ]

        avg_lateness = late_trips["delay_minutes"].mean() if not late_trips.empty else 0.0
        avg_earliness = early_trips["delay_minutes"].abs().mean() if not early_trips.empty else 0.0
        delay_main_kpi = (
            visuals_filtered_df["delay_minutes"].quantile(0.8)
            if not visuals_filtered_df.empty
            else 0.0
        )
        early_risk_pct = (
            len(early_trips) / len(visuals_filtered_df) * 100
            if len(visuals_filtered_df) > 0
            else 0.0
        )

        # Split Top-level Metrics
        m1, m2, m3, m4, m5 = st.columns(5)
        with m1:
            st.metric(
                label="Total Records",
                value=len(visuals_filtered_df),
                help="Number of records matching the selected route, destination, stop, and hour filters."
            )
        with m2:
            st.metric(
                label="Delay Trend",
                value=f"{delay_main_kpi:+.2f} min",
                help="Punctuality in 80% of the cases"
            )
        with m3:
            st.metric(
                label="Avg Delay in Late Trips",
                value=f"+{avg_lateness:.2f} min",
                help="Average delay in minutes, calculated only from trips with a positive delay."
            )
        with m4:
            st.metric(
                label="Avg Advance in Early Trips",
                value=f"-{avg_earliness:.2f} min",
                help="Average earliness in minutes, calculated only from trips arriving before schedule."
            )
        with m5:
            st.metric(
                label="Risk of Early Departure",
                value=f"{early_risk_pct:.1f}%",
                help="Percentage of filtered records classified as Early."
            )

        st.markdown("---")

        # Charts Section
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Répartition de la ponctualité")
            status_counts = visuals_filtered_df["punctuality_status"].value_counts().reset_index()
            status_counts.columns = ["status", "count"]
            
            color_map = {
                "Early": "#2E8B57",
                "On Time": "#3cb44b",
                "Slight Delay": "#f0ad4e",
                "Severe Delay": "#a72225"
            }
            
            fig_pie = px.pie(
                status_counts, 
                names="status", 
                values="count", 
                hole=0.4, 
                color="status",
                color_discrete_map=color_map
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_right:
            st.subheader("Distribution par heure")
            fig_box = px.box(
                visuals_filtered_df,
                x="hour_of_day",
                y="delay_minutes",
                points=False,
                labels={"hour_of_day": "Hour of Day", "delay_minutes": "Delay / Earliness (minutes)"}
            )
            fig_box.update_traces(marker_color="#a72225", line_color="#a72225")
            fig_box.add_hline(y=0, line_dash="dash", line_color="#2E8B57", annotation_text="Scheduled Time (0 min)")
            st.plotly_chart(fig_box, use_container_width=True)

        # Raw Data Section
        with st.expander("Voir les données brutes"):
            st.dataframe(visuals_filtered_df[['route_short_name', 'trip_headsign', 'stop_name', 'service_date', 'actual_arrival_time', 'delay_minutes', 'punctuality_status']])

except Exception as e:
    st.error(f"Error connecting to BigQuery or loading data: {e}")