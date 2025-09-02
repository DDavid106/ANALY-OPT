import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
import unicodedata

# --- Streamlit Page Config ---
st.set_page_config(page_title="ERA Reliability Monitoring", layout="wide")
st.title("📊 ERA Reliability Monitoring Dashboard")

# --- Authenticate and Load Google Sheet ---
st.info("Connecting to Google Sheets...")

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Load credentials dict from Streamlit secrets and fix private key newlines
creds_dict = dict(st.secrets["gcp_service_account"])
creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(creds)
spreadsheet = client.open("Reliability Monitoring Sheet")

# --- Dummy feeder locations ---
feeder_locations = {
    "Bombo 1": {"lat": 0.600, "lon": 32.550},
    "Kololo": {"lat": 0.335, "lon": 32.590},
    "Bombo Rd Industrial": {"lat": 0.345, "lon": 32.565},
    "Luwero/Kyampisi": {"lat": 0.830, "lon": 32.500},
    "Bombo 33": {"lat": 0.650, "lon": 32.520},
    "China Golden": {"lat": 0.370, "lon": 32.580},
    "Wabigalo": {"lat": 0.330, "lon": 32.610},
    "Matuga 1": {"lat": 0.550, "lon": 32.480},
    "Roofings 1": {"lat": 0.520, "lon": 32.470},
    "Steel and Tube": {"lat": 0.510, "lon": 32.460},
    "Matuga 3": {"lat": 0.555, "lon": 32.490},
    "Ugachic": {"lat": 0.560, "lon": 32.450},
}

# --- Helper Functions ---
def clean_feeder_name(name):
    name = str(name).strip()
    name = unicodedata.normalize("NFKD", name)
    name = name.replace('\xa0', ' ')
    name = ' '.join(name.split())
    return name.title()

def compute_metrics(df, group_cols):
    results = (
        df.groupby(group_cols)
        .apply(lambda g: pd.Series({
            "SAIDI": (g["Duration (hr)"] * g["Customer No"]).sum() / g["Customer No"].sum()
                      if g["Customer No"].sum() > 0 else 0,
            "SAIFI": len(g) / g["Customer No"].nunique()
                      if g["Customer No"].nunique() > 0 else 0,
            "CAIDI": (
                ((g["Duration (hr)"] * g["Customer No"]).sum() / g["Customer No"].sum())
                / (len(g) / g["Customer No"].nunique())
            ) if g["Customer No"].nunique() > 0 and len(g) > 0 else 0
        }))
        .reset_index()
    )
    return results

# --- Load and Process Worksheets ---
all_data = []
for ws in spreadsheet.worksheets():
    month = ws.title
    data = ws.get_all_records()
    if not data:
        continue

    df = pd.DataFrame(data)
    df.columns = df.columns.str.strip()
    df["Month"] = month
    df["Feeder Name"] = df["Feeder Name"].apply(clean_feeder_name)

    # Convert datetime
    df["Interruption Time"] = pd.to_datetime(df["Interruption Time"], errors="coerce", dayfirst=True)
    df["Restoration Time"] = pd.to_datetime(df["Restoration Time"], errors="coerce", dayfirst=True)
    df["Duration (hr)"] = (df["Restoration Time"] - df["Interruption Time"]).dt.total_seconds() / 3600

    # Numeric conversions
    df["Customer No"] = pd.to_numeric(df["Customer No"], errors="coerce")
    df["Elapsed Time"] = pd.to_numeric(df["Elapsed Time"], errors="coerce")

    # Add time columns
    df["Date"] = df["Interruption Time"].dt.date
    df["Week"] = df["Interruption Time"].dt.strftime("%Y-W%U")

    # Add dummy location info
    df["Latitude"] = df["Feeder Name"].map(lambda x: feeder_locations.get(x, {}).get("lat", None))
    df["Longitude"] = df["Feeder Name"].map(lambda x: feeder_locations.get(x, {}).get("lon", None))

    all_data.append(df)

df_all = pd.concat(all_data, ignore_index=True)

# --- Build Metrics ---
daily_metrics = compute_metrics(df_all, ["Feeder Name", "Month", "Date"])
weekly_metrics = compute_metrics(df_all, ["Feeder Name", "Month", "Week"])
monthly_metrics = compute_metrics(df_all, ["Feeder Name", "Month"])

# --- Sidebar Filters ---
st.sidebar.header("🔎 Filters")

period = st.sidebar.radio("Select Period", ["Daily", "Weekly", "Monthly"])
month_options = sorted(df_all["Month"].unique())
selected_month = st.sidebar.selectbox("Select Month", month_options)

# Feeder only used for trends/cards
feeder_options = sorted(df_all[df_all["Month"] == selected_month]["Feeder Name"].unique())
selected_feeder = st.sidebar.selectbox("Select Feeder", feeder_options)

# Week filter if weekly
selected_week = None
if period == "Weekly":
    week_options = sorted(df_all[df_all["Month"] == selected_month]["Week"].unique())
    selected_week = st.sidebar.selectbox("Select Week (optional)", ["All Weeks"] + list(week_options))

# --- Select Metrics Based on Period ---
if period == "Daily":
    metrics_df = daily_metrics
    group_field = "Date"
elif period == "Weekly":
    metrics_df = weekly_metrics
    group_field = "Week"
    if selected_week and selected_week != "All Weeks":
        metrics_df = metrics_df[metrics_df["Week"] == selected_week]
else:
    metrics_df = monthly_metrics
    group_field = "Month"

# Filtered metrics for cards/trends (selected feeder only)
filtered_metrics = metrics_df[
    (metrics_df["Month"] == selected_month) &
    (metrics_df["Feeder Name"] == selected_feeder)
]

# --- Display Metrics ---
st.subheader(f"📈 Reliability Indices for {selected_feeder} in {selected_month} ({period})")
if not filtered_metrics.empty:
    latest = filtered_metrics.sort_values(group_field).iloc[-1]
    col1, col2, col3 = st.columns(3)
    col1.metric("SAIFI", round(latest["SAIFI"], 3))
    col2.metric("SAIDI", round(latest["SAIDI"], 3))
    col3.metric("CAIDI", round(latest["CAIDI"], 3))
else:
    st.warning("No metrics available for this selection.")

# =====================================================
# 1) Reliability Indices by Feeder (all feeders)
# =====================================================
st.subheader(f"🪛 Reliability Indices by Feeder in {selected_month}")
feeder_data = metrics_df[metrics_df["Month"] == selected_month]
if period == "Weekly" and selected_week and selected_week != "All Weeks":
    feeder_data = feeder_data[feeder_data["Week"] == selected_week]

fig_metrics = px.bar(
    feeder_data,
    x="Feeder Name",
    y=["SAIFI", "SAIDI", "CAIDI"],
    barmode="group",
    title=f"Feeder Indices ({period})"
)
st.plotly_chart(fig_metrics, use_container_width=True)

# =====================================================
# 2) SAIDI & SAIFI Trends (selected feeder only)
# =====================================================
st.subheader(f"📅 {period} SAIDI and SAIFI Trends for {selected_feeder}")
trend_data = metrics_df[metrics_df["Feeder Name"] == selected_feeder]

fig_trend = px.line(
    trend_data,
    x=group_field,
    y=["SAIDI", "SAIFI"],
    markers=True,
    title=f"{period} Trends for {selected_feeder}"
)
st.plotly_chart(fig_trend, use_container_width=True)

# =====================================================
# 3) Outage Duration by Fault Category
# =====================================================
st.subheader(f"⚡ Outage Duration by Fault Category in {selected_month}")
df_month = df_all[df_all["Month"] == selected_month]
if period == "Weekly" and selected_week and selected_week != "All Weeks":
    df_month = df_month[df_month["Week"] == selected_week]

fig_fault = px.box(
    df_month,
    x="Fault Category",
    y="Elapsed Time",
    title="Outage Duration Distribution"
)
st.plotly_chart(fig_fault, use_container_width=True)

# =====================================================
# 4) Feeder Location Map (All feeders, interactive)
# =====================================================
st.subheader("🗺️ Feeder Locations & Reliability")
map_metrics = metrics_df[metrics_df["Month"] == selected_month]
if period == "Weekly" and selected_week and selected_week != "All Weeks":
    map_metrics = map_metrics[map_metrics["Week"] == selected_week]

latest_metrics = map_metrics.sort_values(group_field).groupby("Feeder Name").tail(1)
map_df = latest_metrics.merge(
    df_all[["Feeder Name", "Latitude", "Longitude"]].drop_duplicates(),
    on="Feeder Name",
    how="left"
).dropna(subset=["Latitude", "Longitude"])

if not map_df.empty:
    fig_map = px.scatter_mapbox(
        map_df,
        lat="Latitude",
        lon="Longitude",
        hover_name="Feeder Name",
        hover_data={"SAIFI": ":.3f", "SAIDI": ":.3f", "CAIDI": ":.3f"},
        color="SAIFI",
        size="SAIDI",
        zoom=9,
        height=600
    )
    fig_map.update_layout(mapbox_style="open-street-map")
    st.plotly_chart(fig_map, use_container_width=True)
else:
    st.warning("No location data available.")
