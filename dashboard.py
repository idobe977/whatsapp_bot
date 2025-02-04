import streamlit as st
import pandas as pd
from pyairtable import Api
from dotenv import load_dotenv
import os
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import requests
from collections import Counter

# Load environment variables
load_dotenv()

# Configure Airtable
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
SURVEY_TABLE_IDS = {
    "business_survey": os.getenv("AIRTABLE_BUSINESS_SURVEY_TABLE_ID"),
    "research_survey": os.getenv("AIRTABLE_RESEARCH_SURVEY_TABLE_ID"),
    "satisfaction_survey": os.getenv("AIRTABLE_SATISFACTION_SURVEY_TABLE_ID")
}

# Initialize Airtable client
airtable = Api(AIRTABLE_API_KEY)

# Set page config
st.set_page_config(
    page_title="WhatsApp Survey Bot Dashboard",
    page_icon="📊",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    .stMetric .metric-label { font-size: 16px !important; }
    .stMetric .metric-value { font-size: 24px !important; }
    div[data-testid="stMetricValue"] > div { font-size: 24px !important; }
    .hebrew { direction: rtl; text-align: right; }
</style>
""", unsafe_allow_html=True)

# Title and description
st.title("📱 WhatsApp Survey Bot Dashboard")
st.markdown("""
This dashboard provides insights and management capabilities for the WhatsApp Survey Bot.
""")

# Sidebar
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Overview", "Survey Responses", "Analytics", "Bot Settings"])

if page == "Overview":
    # Overview metrics
    st.header("📈 Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    
    # Get data from all tables
    total_responses = 0
    responses_today = 0
    completion_rate = 0
    active_surveys = 0
    all_records = []
    
    try:
        for survey_name, table_id in SURVEY_TABLE_IDS.items():
            table = airtable.table(AIRTABLE_BASE_ID, table_id)
            records = table.all()
            all_records.extend(records)
            
            total_responses += len(records)
            
            # Count today's responses
            today = datetime.now().date()
            today_records = [r for r in records if r['fields'].get('תאריך מילוי', '').startswith(str(today))]
            responses_today += len(today_records)
            
            # Calculate completion rate
            completed = len([r for r in records if r['fields'].get('סטטוס') == 'הושלם'])
            if records:
                completion_rate += (completed / len(records)) * 100
                
            # Count active surveys
            active = len([r for r in records if r['fields'].get('סטטוס') in ['חדש', 'בטיפול']])
            active_surveys += active
        
        if SURVEY_TABLE_IDS:
            completion_rate /= len(SURVEY_TABLE_IDS)
        
        with col1:
            st.metric("Total Responses", total_responses)
        with col2:
            st.metric("Responses Today", responses_today)
        with col3:
            st.metric("Active Surveys", active_surveys)
        with col4:
            st.metric("Completion Rate", f"{completion_rate:.1f}%")
            
        # Response Trend
        st.subheader("📊 Response Trend")
        if all_records:
            df = pd.DataFrame([{
                'Date': r['fields'].get('תאריך מילוי', ''),
                'Survey Type': r['fields'].get('סוג שאלון', ''),
                'Status': r['fields'].get('סטטוס', '')
            } for r in all_records])
            
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date')
            
            # Daily responses trend
            daily_responses = df.groupby('Date').size().reset_index(name='Count')
            fig = px.line(daily_responses, x='Date', y='Count', 
                         title='Daily Survey Responses',
                         labels={'Count': 'Number of Responses', 'Date': 'Date'})
            st.plotly_chart(fig, use_container_width=True)
            
        # Recent Activity
        st.subheader("📅 Recent Activity")
        
        recent_records = []
        for survey_name, table_id in SURVEY_TABLE_IDS.items():
            table = airtable.table(AIRTABLE_BASE_ID, table_id)
            records = table.all()
            for record in records:
                recent_records.append({
                    'Survey Type': survey_name,
                    'Date': record['fields'].get('תאריך מילוי', ''),
                    'Name': record['fields'].get('שם מלא', ''),
                    'Status': record['fields'].get('סטטוס', ''),
                    'Meeting Interest': record['fields'].get('מעוניין לקבוע פגישה', 'לא צוין')
                })
        
        if recent_records:
            df = pd.DataFrame(recent_records)
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date', ascending=False).head(10)
            st.dataframe(df, hide_index=True)
        
    except Exception as e:
        st.error(f"Error loading overview data: {str(e)}")

elif page == "Survey Responses":
    st.header("📝 Survey Responses")
    
    # Survey type selector
    survey_type = st.selectbox(
        "Select Survey Type",
        list(SURVEY_TABLE_IDS.keys()),
        format_func=lambda x: x.replace('_', ' ').title()
    )
    
    try:
        table = airtable.table(AIRTABLE_BASE_ID, SURVEY_TABLE_IDS[survey_type])
        records = table.all()
        
        if records:
            # Convert to DataFrame
            df = pd.DataFrame([r['fields'] for r in records])
            
            # Display filters
            col1, col2, col3 = st.columns(3)
            with col1:
                status_filter = st.multiselect(
                    "Filter by Status",
                    df['סטטוס'].unique()
                )
            with col2:
                date_range = st.date_input(
                    "Date Range",
                    value=(
                        datetime.now().date() - timedelta(days=30),
                        datetime.now().date()
                    )
                )
            with col3:
                search_term = st.text_input("Search by Name", "")
            
            # Apply filters
            if status_filter:
                df = df[df['סטטוס'].isin(status_filter)]
            if len(date_range) == 2:
                df['תאריך מילוי'] = pd.to_datetime(df['תאריך מילוי'])
                df = df[
                    (df['תאריך מילוי'].dt.date >= date_range[0]) &
                    (df['תאריך מילוי'].dt.date <= date_range[1])
                ]
            if search_term:
                df = df[df['שם מלא'].str.contains(search_term, case=False, na=False)]
            
            # Display data
            st.dataframe(df, hide_index=True)
            
            # Export options
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Export to CSV"):
                    csv = df.to_csv(index=False)
                    st.download_button(
                        "Download CSV",
                        csv,
                        f"{survey_type}_responses.csv",
                        "text/csv"
                    )
            with col2:
                if st.button("Export to Excel"):
                    excel_file = df.to_excel(index=False)
                    st.download_button(
                        "Download Excel",
                        excel_file,
                        f"{survey_type}_responses.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
        else:
            st.info("No responses found for this survey type.")
            
    except Exception as e:
        st.error(f"Error loading survey responses: {str(e)}")

elif page == "Analytics":
    st.header("📊 Analytics")
    
    try:
        # Collect all data
        all_data = []
        for survey_name, table_id in SURVEY_TABLE_IDS.items():
            table = airtable.table(AIRTABLE_BASE_ID, table_id)
            records = table.all()
            for record in records:
                record['fields']['Survey Type'] = survey_name
                all_data.append(record['fields'])
        
        if all_data:
            df = pd.DataFrame(all_data)
            
            # Survey Distribution
            st.subheader("Survey Type Distribution")
            survey_counts = df['Survey Type'].value_counts()
            fig = px.pie(values=survey_counts.values, 
                        names=survey_counts.index,
                        title='Distribution of Survey Types')
            st.plotly_chart(fig)
            
            # Status Distribution
            st.subheader("Survey Status Distribution")
            status_counts = df['סטטוס'].value_counts()
            fig = px.bar(x=status_counts.index, 
                        y=status_counts.values,
                        title='Survey Status Distribution',
                        labels={'x': 'Status', 'y': 'Count'})
            st.plotly_chart(fig)
            
            # Meeting Interest Analysis
            if 'מעוניין לקבוע פגישה' in df.columns:
                st.subheader("Meeting Interest Analysis")
                meeting_interest = df['מעוניין לקבוע פגישה'].value_counts()
                fig = px.pie(values=meeting_interest.values,
                            names=meeting_interest.index,
                            title='Meeting Interest Distribution')
                st.plotly_chart(fig)
            
            # Response Time Analysis
            st.subheader("Response Time Analysis")
            df['תאריך מילוי'] = pd.to_datetime(df['תאריך מילוי'])
            df['Hour'] = df['תאריך מילוי'].dt.hour
            hourly_responses = df['Hour'].value_counts().sort_index()
            fig = px.line(x=hourly_responses.index,
                         y=hourly_responses.values,
                         title='Response Distribution by Hour',
                         labels={'x': 'Hour of Day', 'y': 'Number of Responses'})
            st.plotly_chart(fig)
            
    except Exception as e:
        st.error(f"Error loading analytics: {str(e)}")

elif page == "Bot Settings":
    st.header("⚙️ Bot Settings")
    
    # Display current environment variables
    st.subheader("Environment Variables")
    env_vars = {
        "ID_INSTANCE": os.getenv("ID_INSTANCE"),
        "API_TOKEN_INSTANCE": "***" + os.getenv("API_TOKEN_INSTANCE")[-4:] if os.getenv("API_TOKEN_INSTANCE") else None,
        "GEMINI_API_KEY": "***" + os.getenv("GEMINI_API_KEY")[-4:] if os.getenv("GEMINI_API_KEY") else None,
        "AIRTABLE_API_KEY": "***" + os.getenv("AIRTABLE_API_KEY")[-4:] if os.getenv("AIRTABLE_API_KEY") else None,
    }
    
    st.json(json.dumps(env_vars, indent=2))
    
    # Bot Status and Controls
    st.subheader("Bot Status and Controls")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("Check Bot Status"):
            try:
                response = requests.get("http://localhost:8000/health")
                if response.status_code == 200:
                    st.success("Bot is running and healthy! 🟢")
                else:
                    st.error("Bot is not responding correctly 🔴")
            except Exception as e:
                st.error(f"Could not connect to bot: {str(e)}")
    
    with col2:
        if st.button("View Logs"):
            try:
                with open("whatsapp_bot.log", "r", encoding="utf-8") as f:
                    logs = f.readlines()[-50:]  # Last 50 lines
                    st.code("".join(logs))
            except Exception as e:
                st.error(f"Could not read logs: {str(e)}")
    
    # Webhook Configuration
    st.subheader("Webhook Configuration")
    webhook_url = st.text_input("Webhook URL", "http://your-domain.com/webhook")
    if st.button("Update Webhook"):
        st.info("This feature will be implemented soon")
    
    # System Information
    st.subheader("System Information")
    system_info = {
        "Python Version": os.sys.version.split()[0],
        "Operating System": os.name,
        "Current Directory": os.getcwd(),
        "Available CPU Cores": os.cpu_count()
    }
    st.json(json.dumps(system_info, indent=2))

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("Made with ❤️ by Your Name")
st.sidebar.markdown(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}") 
