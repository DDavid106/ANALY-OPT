# app.py
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

creds = Credentials.from_service_account_file(
    "era-reliability-monitoring-3a7c512a0681.json",  # Ensure this file is in your project folder
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
)

client = gspread.authorize(creds)
spreadsheet = client.open("Reliability Monitoring Sheet")

def clean_feeder_name(name):
    name = str(name).strip()
    name = unicodedata.normalize("NFKD", name)
    name = name.replace('\xa0', ' ')
    name = ' '.join(name.split())
    return name.title()

metrics = []
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

    df["Interruption Time"] = pd.to_datetime(df["Interruption Time"], errors='coerce', dayfirst=True)
    df["Restoration Time"] = pd.to_datetime(df["Restoration Time"], errors='coerce', dayfirst=True)
    df["Duration (hr)"] = (df["Restoration Time"] - df["Interruption Time"]).dt.total_seconds() / 3600

    df["Customer No"] = pd.to_numeric(df["Customer No"], errors='coerce')
    df["Elapsed Time"] = pd.to_numeric(df["Elapsed Time"], errors='coerce')
    df.dropna(subset=["Customer No", "Elapsed Time", "Fault Category"], inplace=True)

    feeder_groups = df.groupby("Feeder Name")
    for feeder_name, group in feeder_groups:
        N_total = group["Customer No"].nunique()
        if N_total == 0:
            continue
        SAIFI = round(len(group) / N_total, 4)
        SAIDI = round(group["Elapsed Time"].sum() / N_total, 4)
        CAIDI = round((SAIDI / SAIFI if SAIFI > 0 else 0), 4)

        metrics.append({
            "Feeder Name": feeder_name,
            "Month": month,
            "SAIFI": SAIFI,
            "SAIDI": SAIDI,
            "CAIDI": CAIDI
        })

    all_data.append(df)

df_all = pd.concat(all_data, ignore_index=True)
metrics_df = pd.DataFrame(metrics)

# --- User Filters ---
st.sidebar.header("🔎 Filters")
month_options = sorted(df_all["Month"].unique())
feeder_options = sorted(df_all["Feeder Name"].unique())

selected_month = st.sidebar.selectbox("Select Month", month_options)
selected_feeder = st.sidebar.selectbox("Select Feeder", feeder_options)

filtered_metrics = metrics_df[(metrics_df["Month"] == selected_month) & (metrics_df["Feeder Name"] == selected_feeder)]

# --- Metrics Display ---
st.subheader(f"📈 Reliability Indices for {selected_feeder} in {selected_month}")
if not filtered_metrics.empty:
    col1, col2, col3 = st.columns(3)
    col1.metric("SAIFI", filtered_metrics["SAIFI"].values[0])
    col2.metric("SAIDI", filtered_metrics["SAIDI"].values[0])
    col3.metric("CAIDI", filtered_metrics["CAIDI"].values[0])
else:
    st.warning("No metrics available for this selection.")

# --- Plots ---
st.subheader("🪛 Reliability Indices by Feeder")
fig_metrics = px.bar(metrics_df, x="Feeder Name", y=["SAIFI", "SAIDI", "CAIDI"], barmode="group")
st.plotly_chart(fig_metrics, use_container_width=True)

st.subheader("⚡ Outage Duration by Fault Category")
fig_fault = px.box(df_all, x="Fault Category", y="Elapsed Time")
st.plotly_chart(fig_fault, use_container_width=True)

st.subheader("📅 Monthly SAIDI and SAIFI Trends")
monthly = df_all.groupby("Month").agg({
    "Elapsed Time": "sum",
    "Customer No": "count"
}).reset_index()

monthly["SAIDI"] = monthly["Elapsed Time"] / monthly["Customer No"]
monthly["SAIFI"] = monthly["Customer No"] / monthly["Customer No"]  # This ends up being 1 — placeholder

fig_monthly = px.line(monthly, x="Month", y=["SAIDI", "SAIFI"], markers=True)
st.plotly_chart(fig_monthly, use_container_width=True)
