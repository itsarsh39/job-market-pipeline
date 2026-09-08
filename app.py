"""
app.py

Interactive Analytics & Pipeline Health Dashboard for the Job Market Pipeline Project.
Uses Streamlit, Plotly, Pandas, and SQLite (jobs.db).

Run via:
    streamlit run app.py
"""

import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timezone

# ---------------------------------------------------------
# Page Configuration
# ---------------------------------------------------------
st.set_page_config(
    page_title="Job Market Pipeline & Analytics",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------
# Custom Styling (CSS Injection)
# ---------------------------------------------------------
st.markdown("""
<style>
    /* Global Container Adjustments */
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 95%;
    }
    
    /* Header Container */
    .header-card {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border-radius: 12px;
        padding: 1.5rem 2rem;
        margin-bottom: 1.5rem;
        border: 1px solid #334155;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    }
    
    .header-title {
        color: #F8FAFC;
        font-size: 2rem;
        font-weight: 800;
        margin-bottom: 0.3rem;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    
    .header-subtitle {
        color: #94A3B8;
        font-size: 1rem;
    }

    /* Metric Cards */
    .metric-card {
        background: #1E293B;
        border-radius: 10px;
        padding: 1.2rem;
        border-left: 4px solid #38BDF8;
        border-top: 1px solid #334155;
        border-right: 1px solid #334155;
        border-bottom: 1px solid #334155;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    
    .metric-card-purple { border-left-color: #A855F7; }
    .metric-card-green { border-left-color: #34D399; }
    .metric-card-amber { border-left-color: #F59E0B; }

    .metric-label {
        color: #94A3B8;
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .metric-value {
        color: #F8FAFC;
        font-size: 1.8rem;
        font-weight: 700;
        margin-top: 0.3rem;
    }

    .metric-subtext {
        color: #64748B;
        font-size: 0.8rem;
        margin-top: 0.2rem;
    }

    /* Badges */
    .status-badge-success {
        background-color: #064E3B;
        color: #34D399;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
    }

    .status-badge-warning {
        background-color: #78350F;
        color: #FBBF24;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
    }
    
    .status-badge-failed {
        background-color: #7F1D1D;
        color: #FCA5A5;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# Country Metadata Mapping & Currency Rates
# ---------------------------------------------------------
COUNTRY_MAP = {
    "in": {"name": "India", "flag": "🇮🇳", "currency": "INR"},
    "us": {"name": "United States", "flag": "🇺🇸", "currency": "USD"},
    "gb": {"name": "United Kingdom", "flag": "🇬🇧", "currency": "GBP"},
    "au": {"name": "Australia", "flag": "🇦🇺", "currency": "AUD"},
    "ca": {"name": "Canada", "flag": "🇨🇦", "currency": "CAD"},
    "sg": {"name": "Singapore", "flag": "🇸🇬", "currency": "SGD"},
}

EXCHANGE_RATES_TO_USD = {
    "USD": 1.0,
    "INR": 0.012,
    "GBP": 1.31,
    "AUD": 0.67,
    "CAD": 0.74,
    "SGD": 0.76,
}

TECH_KEYWORDS = [
    "SQL", "Python", "Power BI", "Tableau", "Excel", "R", "AWS", "Azure",
    "GCP", "Spark", "Hadoop", "Snowflake", "dbt", "ETL", "Airflow",
    "Machine Learning", "AI", "Statistics", "Remote", "Senior", "Lead"
]


def extract_tech_skills(titles: pd.Series) -> pd.DataFrame:
    counts = {kw: 0 for kw in TECH_KEYWORDS}
    for title in titles.dropna():
        title_upper = str(title).upper()
        for kw in TECH_KEYWORDS:
            if kw.upper() in title_upper:
                counts[kw] += 1
    df_skills = pd.DataFrame(list(counts.items()), columns=["Skill / Keyword", "Mentions"])
    return df_skills[df_skills["Mentions"] > 0].sort_values("Mentions", ascending=False)


DB_PATH = "jobs.db"

# ---------------------------------------------------------
# Data Loader Functions (Cached)
# ---------------------------------------------------------
@st.cache_data(ttl=30)
def load_data(db_path: str = DB_PATH):
    try:
        conn = sqlite3.connect(db_path)
        postings_df = pd.read_sql_query("SELECT * FROM postings", conn)
        run_log_df = pd.read_sql_query("SELECT * FROM run_log ORDER BY run_id DESC", conn)
        conn.close()
        
        # Convert date columns to datetime
        if not postings_df.empty:
            postings_df["first_seen_at"] = pd.to_datetime(postings_df["first_seen_at"], errors="coerce")
            postings_df["last_seen_at"] = pd.to_datetime(postings_df["last_seen_at"], errors="coerce")
            postings_df["posted_date"] = pd.to_datetime(postings_df["posted_date"], errors="coerce")
            postings_df["country_label"] = postings_df["country_code"].map(
                lambda c: f"{COUNTRY_MAP.get(c, {}).get('flag', '')} {COUNTRY_MAP.get(c, {}).get('name', c.upper())}"
            )
            # USD Normalization
            postings_df["fx_rate"] = postings_df["currency"].map(lambda curr: EXCHANGE_RATES_TO_USD.get(curr, 1.0))
            postings_df["salary_min_usd"] = postings_df["salary_min"] * postings_df["fx_rate"]
            postings_df["salary_max_usd"] = postings_df["salary_max"] * postings_df["fx_rate"]
            
        if not run_log_df.empty:
            run_log_df["run_timestamp"] = pd.to_datetime(run_log_df["run_timestamp"], errors="coerce")
            run_log_df["country_label"] = run_log_df["country_code"].map(
                lambda c: f"{COUNTRY_MAP.get(c, {}).get('flag', '')} {COUNTRY_MAP.get(c, {}).get('name', c.upper())}"
            )
            
        return postings_df, run_log_df
    except Exception as e:
        st.error(f"Error reading database: {e}")
        return pd.DataFrame(), pd.DataFrame()


postings_df, run_log_df = load_data()

# ---------------------------------------------------------
# Sidebar Controls & Filters
# ---------------------------------------------------------
st.sidebar.markdown("### 🎛️ Dashboard Controls")
st.sidebar.markdown("---")

if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("#### 🔍 Filter Criteria")

# Country Multiselect
available_countries = list(COUNTRY_MAP.keys())
country_options = {f"{COUNTRY_MAP[c]['flag']} {COUNTRY_MAP[c]['name']}": c for c in available_countries}
selected_country_labels = st.sidebar.multiselect(
    "Select Country",
    options=list(country_options.keys()),
    default=list(country_options.keys())
)
selected_countries = [country_options[label] for label in selected_country_labels]

# Keyword Multiselect
available_keywords = sorted(postings_df["keyword_searched"].dropna().unique().tolist()) if not postings_df.empty else []
selected_keywords = st.sidebar.multiselect(
    "Select Job Keyword",
    options=available_keywords,
    default=available_keywords
)

# Status Filter
status_mode = st.sidebar.radio(
    "Posting Status",
    options=["Active Listings Only", "Historical / Expired Only", "All Listings"],
    index=0
)

# Contract Filter
contract_options = ["All"]
if not postings_df.empty and "contract_time" in postings_df.columns:
    contract_options += sorted(postings_df["contract_time"].dropna().unique().tolist())
selected_contract = st.sidebar.selectbox("Contract Type", options=contract_options)

st.sidebar.markdown("---")
st.sidebar.caption("Job Market Data Pipeline | Powered by Adzuna API & SQLite")

# ---------------------------------------------------------
# Apply Filters to Dataframe
# ---------------------------------------------------------
filtered_df = postings_df.copy() if not postings_df.empty else pd.DataFrame()

if not filtered_df.empty:
    if selected_countries:
        filtered_df = filtered_df[filtered_df["country_code"].isin(selected_countries)]
    if selected_keywords:
        filtered_df = filtered_df[filtered_df["keyword_searched"].isin(selected_keywords)]
    
    if status_mode == "Active Listings Only":
        filtered_df = filtered_df[filtered_df["is_active"] == 1]
    elif status_mode == "Historical / Expired Only":
        filtered_df = filtered_df[filtered_df["is_active"] == 0]
        
    if selected_contract != "All":
        filtered_df = filtered_df[filtered_df["contract_time"] == selected_contract]

# ---------------------------------------------------------
# Header & Pipeline Status Banner
# ---------------------------------------------------------
st.markdown("""
<div class="header-card">
    <div class="header-title">
        <span>💼 Global Job Market Intelligence & Pipeline Operations</span>
    </div>
    <div class="header-subtitle">
        Real-time analytics, compensation benchmarks, and data pipeline health monitoring
    </div>
</div>
""", unsafe_allow_html=True)

# Compute Pipeline Health
if not run_log_df.empty:
    latest_run = run_log_df.iloc[0]
    latest_ts = latest_run["run_timestamp"]
    now_utc = pd.Timestamp.now(tz=timezone.utc)
    
    # Calculate staleness
    time_diff_hours = (now_utc - latest_ts.tz_localize(timezone.utc)).total_seconds() / 3600 if latest_ts.tzinfo is None else (now_utc - latest_ts).total_seconds() / 3600
    
    failed_runs_count = len(run_log_df[run_log_df["status"] == "failed"])
    
    col_status1, col_status2 = st.columns([3, 1])
    with col_status1:
        if time_diff_hours > 36:
            st.warning(f"⚠️ **Pipeline Data Staleness Warning**: Last automated ingestion occurred **{time_diff_hours:.1f} hours ago** (exceeds 36h threshold).")
        elif latest_run["status"] == "failed":
            st.error(f"🚨 **Pipeline Run Failure**: Last batch run failed with error: `{latest_run['error_message']}`")
        else:
            st.success(f"🟢 **Pipeline Operational**: System healthy. Last sync run recorded **{time_diff_hours:.1f} hours ago** ({latest_ts.strftime('%Y-%m-%d %H:%M UTC')}).")
    with col_status2:
        st.markdown(f"**Audit Health**: `{len(run_log_df) - failed_runs_count}/{len(run_log_df)} Success Runs`")
st.markdown("<br>", unsafe_allow_html=True)

# ---------------------------------------------------------
# Executive KPI Cards
# ---------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)

total_jobs = len(filtered_df)
active_jobs_count = len(filtered_df[filtered_df["is_active"] == 1]) if not filtered_df.empty else 0
top_company = filtered_df["company"].mode()[0] if not filtered_df.empty and not filtered_df["company"].dropna().empty else "N/A"
top_company_jobs = len(filtered_df[filtered_df["company"] == top_company]) if top_company != "N/A" else 0

# Average Salary calculation
valid_salaries = filtered_df[filtered_df["salary_min"].notnull() & (filtered_df["salary_min"] > 0)] if not filtered_df.empty else pd.DataFrame()
avg_salary_min = valid_salaries["salary_min"].mean() if not valid_salaries.empty else 0

with c1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Filtered Postings</div>
        <div class="metric-value">{total_jobs:,}</div>
        <div class="metric-subtext">Active: {active_jobs_count:,} | Inactive: {total_jobs - active_jobs_count:,}</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="metric-card metric-card-purple">
        <div class="metric-label">Top Employer</div>
        <div class="metric-value" style="font-size: 1.3rem; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">{top_company}</div>
        <div class="metric-subtext">{top_company_jobs} open postings</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="metric-card metric-card-green">
        <div class="metric-label">Avg Salary Min</div>
        <div class="metric-value">{avg_salary_min:,.0f}</div>
        <div class="metric-subtext">{len(valid_salaries)} listings reporting salary</div>
    </div>
    """, unsafe_allow_html=True)

with c4:
    unique_countries = filtered_df["country_code"].nunique() if not filtered_df.empty else 0
    unique_cities = filtered_df["location"].nunique() if not filtered_df.empty else 0
    st.markdown(f"""
    <div class="metric-card metric-card-amber">
        <div class="metric-label">Geographic Coverage</div>
        <div class="metric-value">{unique_countries} Countries</div>
        <div class="metric-subtext">{unique_cities} unique locations</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ---------------------------------------------------------
# Tabbed Main Dashboard Section
# ---------------------------------------------------------
tab1, tab_skills, tab2, tab3, tab4 = st.tabs([
    "📊 Market & Hiring Analysis",
    "🛠️ Tech Stack & Skill Demand",
    "💰 Compensation & USD Benchmarks",
    "⚡ Pipeline Operations & Logs",
    "🔍 Live Data Explorer"
])

# ---------------------------------------------------------
# TAB 1: Market & Hiring Analysis
# ---------------------------------------------------------
with tab1:
    if filtered_df.empty:
        st.info("No postings matched the selected filters.")
    else:
        col_left, col_right = st.columns(2)
        
        with col_left:
            st.markdown("#### 🏢 Top Hiring Companies")
            top_companies = filtered_df["company"].value_counts().head(10).reset_index()
            top_companies.columns = ["Company", "Postings"]
            
            fig_companies = px.bar(
                top_companies,
                x="Postings",
                y="Company",
                orientation="h",
                color="Postings",
                color_continuous_scale="Blues",
                text="Postings",
            )
            fig_companies.update_layout(
                yaxis=dict(autorange="reversed"),
                margin=dict(l=0, r=20, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F8FAFC"),
                coloraxis_showscale=False
            )
            st.plotly_chart(fig_companies, use_container_width=True)
            
        with col_right:
            st.markdown("#### 🌐 Postings Volume by Country")
            country_counts = filtered_df["country_label"].value_counts().reset_index()
            country_counts.columns = ["Country", "Postings"]
            
            fig_countries = px.pie(
                country_counts,
                names="Country",
                values="Postings",
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_countries.update_layout(
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F8FAFC"),
            )
            st.plotly_chart(fig_countries, use_container_width=True)

        st.markdown("---")
        
        c_work1, c_work2 = st.columns(2)
        with c_work1:
            st.markdown("#### ⏱️ Contract Time Distribution")
            contract_time_counts = filtered_df["contract_time"].fillna("unspecified").value_counts().reset_index()
            contract_time_counts.columns = ["Contract Time", "Count"]
            
            fig_ct = px.bar(
                contract_time_counts,
                x="Contract Time",
                y="Count",
                color="Contract Time",
                text="Count",
                color_discrete_sequence=px.colors.qualitative.Set2
            )
            fig_ct.update_layout(
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F8FAFC"),
                showlegend=False
            )
            st.plotly_chart(fig_ct, use_container_width=True)
            
        with c_work2:
            st.markdown("#### 🎯 Role Keyword Demand Comparison")
            kw_counts = filtered_df["keyword_searched"].value_counts().reset_index()
            kw_counts.columns = ["Keyword", "Count"]
            
            fig_kw = px.bar(
                kw_counts,
                x="Keyword",
                y="Count",
                color="Keyword",
                text="Count",
                color_discrete_sequence=["#38BDF8", "#A855F7"]
            )
            fig_kw.update_layout(
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F8FAFC"),
                showlegend=False
            )
            st.plotly_chart(fig_kw, use_container_width=True)

# ---------------------------------------------------------
# TAB: Tech Stack & Skill Demand
# ---------------------------------------------------------
with tab_skills:
    if filtered_df.empty:
        st.info("No postings available for skill analysis.")
    else:
        st.markdown("#### 🛠️ Frequently Demanded Tech Stack & Keywords")
        st.caption("Extracted from job title analysis across active & historical postings.")
        
        skills_df = extract_tech_skills(filtered_df["title"])
        
        if skills_df.empty:
            st.info("No explicit technology keywords identified in current selection.")
        else:
            col_sk1, col_sk2 = st.columns([3, 2])
            with col_sk1:
                fig_skills = px.bar(
                    skills_df,
                    x="Mentions",
                    y="Skill / Keyword",
                    orientation="h",
                    color="Mentions",
                    color_continuous_scale="Purples",
                    text="Mentions",
                    title="Technology & Skill Mention Count"
                )
                fig_skills.update_layout(
                    yaxis=dict(autorange="reversed"),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#F8FAFC"),
                    coloraxis_showscale=False
                )
                st.plotly_chart(fig_skills, use_container_width=True)
                
            with col_sk2:
                st.markdown("#### 📋 Skill Frequency Breakdown")
                st.dataframe(
                    skills_df,
                    column_config={
                        "Skill / Keyword": "Technology / Key Term",
                        "Mentions": st.column_config.NumberColumn("Postings Count", format="%d")
                    },
                    use_container_width=True,
                    hide_index=True
                )

# ---------------------------------------------------------
# TAB 2: Compensation & USD Benchmarks
# ---------------------------------------------------------
with tab2:
    salary_df = filtered_df[filtered_df["salary_min"].notnull() & (filtered_df["salary_min"] > 0)].copy() if not filtered_df.empty else pd.DataFrame()
    
    if salary_df.empty:
        st.info("No salary details available for the currently selected filter subset.")
    else:
        st.markdown("#### 💵 Salary Distribution Benchmarks")
        
        col_mode1, col_mode2 = st.columns([2, 2])
        with col_mode1:
            curr_mode = st.radio("Currency View", ["USD Normalized ($)", "Native Local Currency"], horizontal=True)
            
        sal_col_min = "salary_min_usd" if curr_mode == "USD Normalized ($)" else "salary_min"
        sal_col_max = "salary_max_usd" if curr_mode == "USD Normalized ($)" else "salary_max"
        curr_label = "USD ($)" if curr_mode == "USD Normalized ($)" else "Native Currency"
        
        col_sal1, col_sal2 = st.columns(2)
        
        with col_sal1:
            fig_box = px.box(
                salary_df,
                x="country_label",
                y=sal_col_min,
                color="keyword_searched",
                title=f"Minimum Salary ({curr_label}) by Country",
                labels={sal_col_min: f"Salary Min ({curr_label})", "country_label": "Country", "keyword_searched": "Role"},
                points="outliers"
            )
            fig_box.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F8FAFC")
            )
            st.plotly_chart(fig_box, use_container_width=True)
            
        with col_sal2:
            fig_max_box = px.box(
                salary_df[salary_df[sal_col_max].notnull()],
                x="country_label",
                y=sal_col_max,
                color="keyword_searched",
                title=f"Maximum Salary ({curr_label}) by Country",
                labels={sal_col_max: f"Salary Max ({curr_label})", "country_label": "Country", "keyword_searched": "Role"},
                points="outliers"
            )
            fig_max_box.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F8FAFC")
            )
            st.plotly_chart(fig_max_box, use_container_width=True)

        st.markdown("---")
        st.markdown("#### 🔮 Predicted vs. Explicit Salary Postings")
        
        if "salary_is_predicted" in salary_df.columns:
            pred_counts = salary_df["salary_is_predicted"].map({1: "Predicted Salary", 0: "Explicitly Disclosed"}).value_counts().reset_index()
            pred_counts.columns = ["Salary Source", "Count"]
            
            fig_pred = px.pie(
                pred_counts,
                names="Salary Source",
                values="Count",
                color_discrete_sequence=["#34D399", "#F59E0B"]
            )
            fig_pred.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F8FAFC")
            )
            st.plotly_chart(fig_pred, use_container_width=True)

# ---------------------------------------------------------
# TAB 3: Pipeline Operations & Logs
# ---------------------------------------------------------
with tab3:
    st.markdown("#### ⚡ Pipeline Execution & Data Quality Audit")
    
    if run_log_df.empty:
        st.info("No run logs found in database.")
    else:
        # Run statistics breakdown
        st_c1, st_c2, st_c3, st_c4 = st.columns(4)
        
        total_runs = len(run_log_df)
        success_runs = len(run_log_df[run_log_df["status"] == "success"])
        partial_runs = len(run_log_df[run_log_df["status"] == "partial"])
        failed_runs = len(run_log_df[run_log_df["status"] == "failed"])
        
        with st_c1:
            st.metric("Total Batch Runs", total_runs)
        with st_c2:
            st.metric("Successful Runs", success_runs)
        with st_c3:
            st.metric("Partial Warnings", partial_runs)
        with st_c4:
            st.metric("Failed Runs", failed_runs)
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Ingestion metrics over time
        st.markdown("#### 📈 Data Modification Volume History")
        fig_ingest = px.bar(
            run_log_df,
            x="run_timestamp",
            y=["rows_new", "rows_updated", "rows_deactivated"],
            labels={"value": "Rows Count", "variable": "Operation", "run_timestamp": "Run Timestamp"},
            color_discrete_map={
                "rows_new": "#34D399",
                "rows_updated": "#38BDF8",
                "rows_deactivated": "#F43F5E"
            },
            title="Rows Inserted (New), Refreshed (Updated), & Soft-Deleted (Deactivated)"
        )
        fig_ingest.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#F8FAFC")
        )
        st.plotly_chart(fig_ingest, use_container_width=True)
        
        st.markdown("---")
        st.markdown("#### 📑 Detailed Pipeline `run_log` Table")
        
        # Format display dataframe for run_log
        log_display = run_log_df[[
            "run_id", "run_timestamp", "country_label", "keyword_searched",
            "status", "rows_fetched", "rows_new", "rows_updated", "rows_deactivated", "error_message"
        ]].copy()
        
        st.dataframe(
            log_display,
            column_config={
                "run_id": "ID",
                "run_timestamp": "Timestamp (UTC)",
                "country_label": "Country",
                "keyword_searched": "Keyword",
                "status": "Status",
                "rows_fetched": "Fetched",
                "rows_new": "New",
                "rows_updated": "Updated",
                "rows_deactivated": "Deactivated",
                "error_message": "Error / Quality Warning"
            },
            use_container_width=True,
            hide_index=True
        )

# ---------------------------------------------------------
# TAB 4: Live Data Explorer
# ---------------------------------------------------------
with tab4:
    st.markdown("#### 🔍 Live Job Postings Database Search & Export")
    
    if filtered_df.empty:
        st.info("No postings match the current filter selection.")
    else:
        # Search input
        search_query = st.text_input("🔎 Search Job Titles, Companies, or Locations", "")
        
        display_df = filtered_df.copy()
        if search_query:
            query = search_query.lower()
            display_df = display_df[
                display_df["title"].str.lower().str.contains(query, na=False) |
                display_df["company"].str.lower().str.contains(query, na=False) |
                display_df["location"].str.lower().str.contains(query, na=False)
            ]
            
        st.caption(f"Showing {len(display_df):,} matching postings out of {len(filtered_df):,} filtered results.")
        
        # Export CSV Button
        csv_data = display_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Filtered Results (CSV)",
            data=csv_data,
            file_name=f"job_postings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Dataframe View
        explorer_cols = [
            "posting_id", "country_label", "keyword_searched", "title", "company",
            "location", "salary_min", "salary_max", "currency", "posted_date", "is_active", "redirect_url"
        ]
        available_cols = [c for c in explorer_cols if c in display_df.columns]
        
        st.dataframe(
            display_df[available_cols],
            column_config={
                "posting_id": "ID",
                "country_label": "Country",
                "keyword_searched": "Role Keyword",
                "title": "Job Title",
                "company": "Company",
                "location": "Location",
                "salary_min": st.column_config.NumberColumn("Salary Min", format="%.0f"),
                "salary_max": st.column_config.NumberColumn("Salary Max", format="%.0f"),
                "currency": "Currency",
                "posted_date": "Posted Date",
                "is_active": "Active Status",
                "redirect_url": st.column_config.LinkColumn("Adzuna Job Link")
            },
            use_container_width=True,
            hide_index=True,
            height=600
        )
