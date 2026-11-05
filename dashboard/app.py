import streamlit as st
from google.cloud import bigquery
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# Page configuration
st.set_page_config(
    page_title="Clermont-Ferrand Transit Performance",
    page_icon="🚍",
    layout="wide"
)

# Initialize BigQuery client
@st.cache_resource
def get_bq_client():
    return bigquery.Client()

client = get_bq_client()

# Query data and safely handle null headsigns without losing delay records
@st.cache_data(ttl=600)
def load_data():
    query = """
        SELECT 
            trip_id,
            route_id,
            stop_id,
            stop_sequence,
            trip_headsign,
            route_short_name,
            stop_name,
            delay_seconds,
            delay_minutes,
            punctuality_status,
            service_date,
            hour_of_day,
            day_of_week
        FROM `clermont-transport.t2c_dbt.fct_transit_performance`
        WHERE route_short_name IN ('A', 'B', 'C', 'E1', 'E2', 'E3', 'E4', 'E5', 'E6', 'E7')
    """
    df = client.query(query).to_dataframe()
    df['service_date'] = pd.to_datetime(df['service_date']).dt.date
    
    # Safe fallback for null/empty headsigns
    df["trip_headsign"] = df["trip_headsign"].fillna("").astype(str)
    empty_mask = (df["trip_headsign"].str.strip() == "") | (df["trip_headsign"].str.lower() == "none")
    df.loc[empty_mask, "trip_headsign"] = "Unspecified Destination (Route " + df.loc[empty_mask, "route_short_name"].astype(str) + ")"
    
    return df

# App Header
st.title("🚍 Clermont-Ferrand Transit Performance Dashboard")
st.markdown("Real-time delay tracking, earliness risk, and punctuality metrics powered by your dbt pipeline and BigQuery.")

try:
    df = load_data()

    if df.empty:
        st.warning("No data found in `fct_transit_performance` yet. Make sure your ingestion and `dbt run` have populated data!")
    else:
        # Streamlined Sidebar (Only global date & status filters remaining)
        st.sidebar.header("Global Filters")
        
        min_date = df["service_date"].min()
        max_date = df["service_date"].max()
        date_range = st.sidebar.date_input(
            "Service Date Range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )

        selected_status = st.sidebar.multiselect(
            "Punctuality Status",
            options=df["punctuality_status"].unique(),
            default=df["punctuality_status"].unique()
        )

        # Apply basic sidebar filters first
        base_filtered_df = df.copy()
        if len(date_range) == 2:
            start_date, end_date = date_range
            base_filtered_df = base_filtered_df[
                (base_filtered_df["service_date"] >= start_date) & 
                (base_filtered_df["service_date"] <= end_date)
            ]
        
        base_filtered_df = base_filtered_df[
            base_filtered_df["punctuality_status"].isin(selected_status)
        ]

        st.markdown("---")

        # ==========================================
        # TOP SECTION: Master Itinerary Map & Selectors
        # ==========================================
        st.subheader("📍 Line Itinerary Congestion & Early Arrival Map")
        
        available_routes = sorted(base_filtered_df["route_short_name"].unique().astype(str).tolist())
        
        if not available_routes:
            st.warning("No data available for the selected date range and status filters.")
        else:
            col_route, col_headsign = st.columns(2)
            with col_route:
                chosen_route = st.selectbox("Select Route (Master Filter)", options=available_routes)
            
            route_df = base_filtered_df[base_filtered_df["route_short_name"] == chosen_route]
            available_headsigns = sorted(route_df["trip_headsign"].dropna().unique().tolist())
            
            with col_headsign:
                chosen_headsign = st.selectbox(
                    "Select Destination / Headsign (Master Filter)", 
                    options=available_headsigns if available_headsigns else ["No destinations available"]
                )
            
            # Master Filtered DataFrame for the rest of the dashboard
            filtered_df = route_df[route_df["trip_headsign"] == chosen_headsign]
            
            # Aggregate stats grouped ONLY by stop_name, taking the min stop_sequence for sorting
            route_itinerary_df = filtered_df.groupby("stop_name").agg(
                stop_sequence=('stop_sequence', 'mean'),  # Keeps the aveerage sequence for ordering
                avg_net_delay=('delay_minutes', 'median'), # Net delay is calculated as the median of all delays (positive and negative)
                avg_delay_pos=('delay_minutes', lambda x: x[x > 0].mean() if (x > 0).any() else 0.0),
                avg_earliness_neg=('delay_minutes', lambda x: x[x < 0].abs().mean() if (x < 0).any() else 0.0),
                early_count=('punctuality_status', lambda x: (x == 'Early').sum()),
                total_count=('punctuality_status', 'count')
            ).reset_index()

            # Prevent NaN values from breaking Plotly marker sizes and colors
            route_itinerary_df["avg_net_delay"] = route_itinerary_df["avg_net_delay"].fillna(0.0)
            route_itinerary_df["avg_delay_pos"] = route_itinerary_df["avg_delay_pos"].fillna(0.0)
            route_itinerary_df["avg_earliness_neg"] = route_itinerary_df["avg_earliness_neg"].fillna(0.0)
            route_itinerary_df["early_pct"] = (route_itinerary_df["early_count"] / route_itinerary_df["total_count"]).fillna(0.0) * 100

            # Sort strictly by the stop sequence order along the line
            route_itinerary_df = route_itinerary_df.sort_values(by="stop_sequence").reset_index(drop=True)
            route_itinerary_df["itinerary_position"] = range(len(route_itinerary_df))
            
            route_itinerary_df["abs_delay"] = route_itinerary_df["avg_net_delay"].abs()
            route_itinerary_df["marker_size"] = (route_itinerary_df["abs_delay"] * 6).clip(lower=10, upper=45)
            route_itinerary_df["marker_color"] = route_itinerary_df["avg_net_delay"].apply(
                lambda x: "#a72225" if x >= 0 else "#2E8B57"
            )

            fig_itinerary = go.Figure()

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
                        "Net Delay: %{customdata[0]:.2f} min<br>"
                        "Avg Delay (Late): +%{customdata[1]:.2f} min<br>"
                        "Avg Earliness (Early): -%{customdata[2]:.2f} min<br>"
                        "Early Risk: %{customdata[3]:.1f}%<extra></extra>"
                    ),
                    customdata=route_itinerary_df[
                        ["avg_net_delay", "avg_delay_pos", "avg_earliness_neg", "early_pct"]
                    ]
                ))

            fig_itinerary.update_layout(
                title=f"Route {chosen_route} → {chosen_headsign} (Green = Early, Red = Late)",
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-1.5, 1.5]),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                height=280,
                margin=dict(t=40, b=20, l=20, r=20)
            )
            st.plotly_chart(fig_itinerary, use_container_width=True)

        stop_options = sorted(filtered_df["stop_name"].dropna().unique().tolist())
        hour_options = sorted(filtered_df["hour_of_day"].dropna().unique().tolist())
        filter_col_stop, filter_col_hour = st.columns(2)

        with filter_col_stop:
            selected_stop = st.selectbox(
                "Filter visuals by stop",
                options=["All"] + stop_options
            )

        with filter_col_hour:
            selected_hour = st.selectbox(
                "Filter visuals by hour",
                options=["All"] + hour_options
            )

        stop_mask = (
            filtered_df["stop_name"].eq(selected_stop)
            if selected_stop != "All"
            else pd.Series(True, index=filtered_df.index)
        )
        hour_mask = (
            filtered_df["hour_of_day"].eq(selected_hour)
            if selected_hour != "All"
            else pd.Series(True, index=filtered_df.index)
        )
        visuals_filtered_df = filtered_df[stop_mask & hour_mask]

        st.markdown("---")

        # ==========================================
        # LOWER SECTION: KPIs & Visuals (Filtered by Route, Headsign, Stop & Hour)
        # ==========================================
        # Metric Calculations
        late_trips = visuals_filtered_df[visuals_filtered_df["delay_minutes"] > 0]
        early_trips = visuals_filtered_df[visuals_filtered_df["delay_minutes"] < 0]

        avg_lateness = late_trips["delay_minutes"].mean() if not late_trips.empty else 0.0
        avg_earliness = early_trips["delay_minutes"].abs().mean() if not early_trips.empty else 0.0
        early_risk_pct = (
            len(early_trips) / len(visuals_filtered_df) * 100
            if len(visuals_filtered_df) > 0
            else 0.0
        )

        # Split Top-level Metrics
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric(label="Total Tracked Records", value=len(visuals_filtered_df))
        with m2:
            st.metric(label="Avg Lateness (Delayed Trips)", value=f"+{avg_lateness:.2f} min")
        with m3:
            st.metric(label="Avg Earliness (Early Trips)", value=f"-{avg_earliness:.2f} min")
        with m4:
            st.metric(label="Risk of Early Departure", value=f"{early_risk_pct:.1f}%")

        st.markdown("---")

        # Charts Section
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Punctuality Status Breakdown")
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
            st.subheader("Hourly Distribution: Earliness vs. Delays")
            fig_box = px.box(
                visuals_filtered_df,
                x="hour_of_day",
                y="delay_minutes",
                points=False,
                labels={"hour_of_day": "Hour of Day", "delay_minutes": "Delay / Earliness (minutes)"},
                title="Spread of Arrival Times relative to Schedule (0 = On-Time)"
            )
            fig_box.update_traces(marker_color="#a72225", line_color="#a72225")
            fig_box.add_hline(y=0, line_dash="dash", line_color="#2E8B57", annotation_text="Scheduled Time (0 min)")
            st.plotly_chart(fig_box, use_container_width=True)

        # Raw Data Section
        with st.expander("🔍 View Raw Mart Data"):
            st.dataframe(visuals_filtered_df[['trip_id', 'route_short_name', 'trip_headsign', 'stop_name', 'service_date', 'hour_of_day', 'delay_minutes', 'punctuality_status']])

except Exception as e:
    st.error(f"Error connecting to BigQuery or loading data: {e}")