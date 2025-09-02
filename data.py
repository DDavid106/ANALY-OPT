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

# --- Helper Functions ---
def clean_feeder_name(name):
    """Clean feeder name formatting."""
    name = str(name).strip()
    name = unicodedata.normalize("NFKD", name)
    name = name.replace('\xa0', ' ')
    name = ' '.join(name.split())
    return name  # avoid .title() to preserve acronyms

def compute_metrics(df, group_cols):
    """Compute SAIDI, SAIFI, CAIDI given grouping columns."""
    results = (
        df.groupby(group_cols)
        .apply(lambda g: pd.Series({
            "SAIDI": (g["Duration (hr)"] * g["Customer No"]).sum() / g["Customer No"].sum()
                      if g["Customer No"].sum() > 0 else 0,
            "SAIFI": g["Customer No"].sum() / g["Customer No"].sum()
                      if g["Customer No"].sum() > 0 else 0,
            "CAIDI": (
                (g["Duration (hr)"] * g["Customer No"]).sum() / g["Customer No"].sum()
            ) / (g["Customer No"].sum() / g["Customer No"].sum())
                      if g["Customer No"].sum() > 0 else 0
        }))
        .reset_index()
    )
    return results

# --- Load and process all worksheets ---
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

    # Convert to datetime
    df["Interruption Time"] = pd.to_datetime(df["Interruption Time"], errors="coerce", dayfirst=True)
    df["Restoration Time"] = pd.to_datetime(df["Restoration Time"], errors="coerce", dayfirst=True)
    df["Duration (hr)"] = (df["Restoration Time"] - df["Interruption Time"]).dt.total_seconds() / 3600

    # Add daily and weekly grouping fields
    df["Date"] = df["Interruption Time"].dt.date
    df["Week"] = df["Interruption Time"].dt.strftime("%Y-W%U")

    # Ensure numeric
    df["Customer No"] = pd.to_numeric(df["Customer No"], errors="coerce")
    df.dropna(subset=["Customer No", "Duration (hr)", "Fault Category"], inplace=True)

    all_data.append(df)

# Combine all months
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

# Update feeder options dynamically
feeder_options = sorted(df_all[df_all["Month"] == selected_month]["Feeder Name"].unique())
selected_feeder = st.sidebar.selectbox("Select Feeder", feeder_options)

# --- Select dataset based on period ---
if period == "Daily":
    metrics_df = daily_metrics
    group_field = "Date"
elif period == "Weekly":
    metrics_df = weekly_metrics
    group_field = "Week"
else:
    metrics_df = monthly_metrics
    group_field = "Month"

filtered_metrics = metrics_df[
    (metrics_df["Month"] == selected_month) &
    (metrics_df["Feeder Name"] == selected_feeder)
]

# --- Metrics Display ---
st.subheader(f"📊 {period} Reliability Indices for {selected_feeder} in {selected_month}")

if not filtered_metrics.empty:
    latest = filtered_metrics.sort_values(group_field).iloc[-1]
    col1, col2, col3 = st.columns(3)
    col1.metric("SAIFI", round(latest["SAIFI"], 3))
    col2.metric("SAIDI", round(latest["SAIDI"], 3))
    col3.metric("CAIDI", round(latest["CAIDI"], 3))
else:
    st.warning("No metrics available for this selection.")

# --- Plots ---
st.subheader(f"📈 {period} Trends for {selected_feeder}")

if not filtered_metrics.empty:
    fig = px.line(
        filtered_metrics,
        x=group_field,
        y=["SAIDI", "SAIFI"],
        markers=True,
        title=f"{period} SAIDI & SAIFI Trends"
    )
    st.plotly_chart(fig, use_container_width=True)

    fig_caidi = px.bar(
        filtered_metrics,
        x=group_field,
        y="CAIDI",
        title=f"{period} CAIDI Trends"
    )
    st.plotly_chart(fig_caidi, use_container_width=True)
else:
    st.info("No trend data available for the selected filters.")
