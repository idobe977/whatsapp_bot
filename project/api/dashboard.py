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
import logging
from collections import Counter
from fastapi import APIRouter, HTTPException
from typing import Dict, List
from ..services.airtable_service import AirtableService
from ..utils.logger import logger

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Debug mode flag
DEBUG_MODE = os.getenv('DEBUG_MODE', 'false').lower() == 'true'

def debug_print(message):
    """Helper function to print debug messages"""
    if DEBUG_MODE:
        st.write(f"🔍 דיבאג: {message}")
    logger.debug(message)

# Load environment variables
load_dotenv()

# Configure Airtable
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
SURVEY_TABLE_IDS = {
    "סקר עסקי": os.getenv("AIRTABLE_BUSINESS_SURVEY_TABLE_ID"),
    "סקר מחקר": os.getenv("AIRTABLE_RESEARCH_SURVEY_TABLE_ID")
}

# Validate environment variables
if not all([AIRTABLE_API_KEY, AIRTABLE_BASE_ID] + list(SURVEY_TABLE_IDS.values())):
    st.error("חסרים משתני סביבה. אנא וודא שכל המשתנים מוגדרים ב-.env")
    st.code("""
    נדרשים המשתנים הבאים:
    AIRTABLE_API_KEY=your_api_key
    AIRTABLE_BASE_ID=your_base_id
    AIRTABLE_BUSINESS_SURVEY_TABLE_ID=your_table_id
    AIRTABLE_RESEARCH_SURVEY_TABLE_ID=your_table_id
    """)
    st.stop()

# Initialize Airtable client
airtable = Api(AIRTABLE_API_KEY)

# Set page config
st.set_page_config(
    page_title="דשבורד בוט סקרים בוואטסאפ",
    page_icon="📊",
    layout="wide"
)

# Custom CSS for RTL support
st.markdown("""
<style>
    .stMetric .metric-label { font-size: 16px !important; direction: rtl; }
    .stMetric .metric-value { font-size: 24px !important; }
    div[data-testid="stMetricValue"] > div { font-size: 24px !important; }
    .hebrew { direction: rtl; text-align: right; }
    div.row-widget.stRadio > div { direction: rtl; }
    div.row-widget.stSelectbox > div { direction: rtl; }
    .stMarkdown { direction: rtl; text-align: right; }
    h1, h2, h3, h4, h5, h6 { direction: rtl; text-align: right; }
    .element-container { direction: rtl; }
    .stDataFrame { direction: rtl; }
    button { direction: rtl; }
</style>
""", unsafe_allow_html=True)

# Title and description
st.title("📱 דשבורד בוט סקרים בוואטסאפ")
st.markdown("""
<div class='hebrew'>
דשבורד זה מספק תובנות ויכולות ניהול עבור בוט הסקרים בוואטסאפ.
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.title("ניווט")
    page = st.radio("עבור אל", ["סקירה כללית", "תגובות סקר", "אנליטיקה", "הגדרות בוט"])

if page == "סקירה כללית":
    st.header("📈 סקירה כללית")
    
    col1, col2, col3, col4 = st.columns(4)
    
    # Get data from all tables
    total_responses = 0
    responses_today = 0
    completion_rate = 0
    active_surveys = 0
    all_records = []
    
    try:
        for survey_name, table_id in SURVEY_TABLE_IDS.items():
            try:
                # Add debug logging
                debug_print(f"מנסה להתחבר לטבלה {survey_name} עם מזהה {table_id}")
                table = airtable.table(AIRTABLE_BASE_ID, table_id)
                
                # Test connection and permissions
                try:
                    test_records = table.all()
                    debug_print(f"התחברות לטבלה {survey_name} הצליחה. מספר רשומות: {len(test_records)}")
                except Exception as api_error:
                    error_details = str(api_error)
                    if "INVALID_PERMISSIONS" in error_details:
                        st.error(f"""
                        שגיאת הרשאות בטבלה {survey_name}:
                        - מזהה בסיס: {AIRTABLE_BASE_ID}
                        - מזהה טבלה: {table_id}
                        - פרטי שגיאה: {error_details}
                        
                        אנא וודא:
                        1. שמזהה הטבלה נכון (Table ID)
                        2. שיש לך הרשאות צפייה לטבלה
                        3. שה-API key שלך פעיל ובעל הרשאות מתאימות
                        """)
                    else:
                        st.error(f"שגיאה בהתחברות לטבלה {survey_name}: {error_details}")
                    continue

                records = table.all()
                all_records.extend(records)
                
                total_responses += len(records)
                
                # Count today's responses
                today = datetime.now().date()
                today_records = [r for r in records if r['fields'].get('תאריך יצירה', '').startswith(str(today))]
                responses_today += len(today_records)
                
                # Calculate completion rate
                completed = len([r for r in records if r['fields'].get('סטטוס') == 'הושלם'])
                if records:
                    completion_rate += (completed / len(records)) * 100
                    
                # Count active surveys
                active = len([r for r in records if r['fields'].get('סטטוס') in ['חדש', 'בטיפול']])
                active_surveys += active
                
            except Exception as table_error:
                st.warning(f"שגיאה בטעינת נתונים מטבלה {survey_name}: {str(table_error)}")
                continue
        
        if SURVEY_TABLE_IDS:
            completion_rate /= len(SURVEY_TABLE_IDS)
        
        with col1:
            st.metric("סך הכל תגובות", total_responses)
        with col2:
            st.metric("תגובות היום", responses_today)
        with col3:
            st.metric("סקרים פעילים", active_surveys)
        with col4:
            st.metric("שיעור השלמה", f"{completion_rate:.1f}%")
            
        # Response Trend
        st.subheader("📊 מגמת תגובות")
        if all_records:
            df = pd.DataFrame([{
                'תאריך': r['fields'].get('תאריך יצירה', ''),
                'סוג סקר': r['fields'].get('סוג שאלון', ''),
                'סטטוס': r['fields'].get('סטטוס', '')
            } for r in all_records])
            
            df['תאריך'] = pd.to_datetime(df['תאריך'])
            df = df.sort_values('תאריך')
            
            # Daily responses trend
            daily_responses = df.groupby('תאריך').size().reset_index(name='כמות')
            fig = px.line(daily_responses, x='תאריך', y='כמות', 
                         title='תגובות יומיות לסקר',
                         labels={'כמות': 'מספר תגובות', 'תאריך': 'תאריך'})
            
            # Fix RTL support for charts
            fig.update_layout(
                title_x=0.5,
                title_xanchor='center',
                font_family="Arial",
                font=dict(size=14),
                title_font=dict(size=20),
                xaxis=dict(side='bottom', title_standoff=25),
                yaxis=dict(side='right', title_standoff=25)
            )
            st.plotly_chart(fig, use_container_width=True)
            
        # Recent Activity
        st.subheader("📅 פעילות אחרונה")
        
        recent_records = []
        for survey_name, table_id in SURVEY_TABLE_IDS.items():
            try:
                table = airtable.table(AIRTABLE_BASE_ID, table_id)
                records = table.all()
                for record in records:
                    recent_records.append({
                        'סוג סקר': survey_name,
                        'תאריך': record['fields'].get('תאריך יצירה', ''),
                        'שם': record['fields'].get('שם מלא', ''),
                        'סטטוס': record['fields'].get('סטטוס', ''),
                        'מעוניין בפגישה': record['fields'].get('מעוניין לקבוע פגישה', 'לא צוין')
                    })
            except Exception as table_error:
                continue
        
        if recent_records:
            df = pd.DataFrame(recent_records)
            df['תאריך'] = pd.to_datetime(df['תאריך'])
            df = df.sort_values('תאריך', ascending=False).head(10)
            st.dataframe(df, hide_index=True)
        
    except Exception as e:
        st.error(f"שגיאה בטעינת נתוני סקירה: {str(e)}")
        if "INVALID_PERMISSIONS" in str(e):
            st.warning("""
            נראה שיש בעיה עם הרשאות Airtable. אנא וודא:
            1. מפתח ה-API תקין ופעיל
            2. יש לך גישה לבסיס הנתונים
            3. מזהי הטבלאות נכונים
            """)

elif page == "תגובות סקר":
    st.header("📝 תגובות סקר")
    
    # Survey type selector
    survey_type = st.selectbox(
        "בחר סוג סקר",
        list(SURVEY_TABLE_IDS.keys())
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
                    "סנן לפי סטטוס",
                    df['סטטוס'].unique()
                )
            with col2:
                date_range = st.date_input(
                    "טווח תאריכים",
                    value=(
                        datetime.now().date() - timedelta(days=30),
                        datetime.now().date()
                    )
                )
            with col3:
                search_term = st.text_input("חיפוש לפי שם", "")
            
            # Apply filters
            if status_filter:
                df = df[df['סטטוס'].isin(status_filter)]
            if len(date_range) == 2:
                df['תאריך יצירה'] = pd.to_datetime(df['תאריך יצירה'])
                df = df[
                    (df['תאריך יצירה'].dt.date >= date_range[0]) &
                    (df['תאריך יצירה'].dt.date <= date_range[1])
                ]
            if search_term:
                df = df[df['שם מלא'].str.contains(search_term, case=False, na=False)]
            
            # Display data
            st.dataframe(df, hide_index=True)
            
            # Export options
            col1, col2 = st.columns(2)
            with col1:
                if st.button("ייצא ל-CSV"):
                    csv = df.to_csv(index=False)
                    st.download_button(
                        "הורד CSV",
                        csv,
                        f"{survey_type}_responses.csv",
                        "text/csv"
                    )
            with col2:
                if st.button("ייצא ל-Excel"):
                    excel_file = df.to_excel(index=False)
                    st.download_button(
                        "הורד Excel",
                        excel_file,
                        f"{survey_type}_responses.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
        else:
            st.info("לא נמצאו תגובות לסוג סקר זה.")
            
    except Exception as e:
        st.error(f"שגיאה בטעינת תגובות הסקר: {str(e)}")

elif page == "אנליטיקה":
    st.header("📊 אנליטיקה")
    
    try:
        # Collect all data
        all_data = []
        for survey_name, table_id in SURVEY_TABLE_IDS.items():
            try:
                table = airtable.table(AIRTABLE_BASE_ID, table_id)
                records = table.all()
                for record in records:
                    record['fields']['סוג סקר'] = survey_name
                    all_data.append(record['fields'])
            except Exception as table_error:
                st.warning(f"שגיאה בטעינת נתונים מטבלה {survey_name}: {str(table_error)}")
                continue
        
        if all_data:
            df = pd.DataFrame(all_data)
            
            # Survey Distribution
            st.subheader("התפלגות סוגי סקרים")
            survey_counts = df['סוג סקר'].value_counts()
            fig = px.pie(values=survey_counts.values, 
                        names=survey_counts.index,
                        title='התפלגות סוגי סקרים')
            fig.update_layout(
                title_x=0.5,
                title_xanchor='center',
                font_family="Arial",
                font=dict(size=14),
                title_font=dict(size=20)
            )
            st.plotly_chart(fig)
            
            # Status Distribution
            st.subheader("התפלגות סטטוס")
            status_counts = df['סטטוס'].value_counts()
            fig = px.bar(x=status_counts.index, 
                        y=status_counts.values,
                        title='התפלגות סטטוס סקרים',
                        labels={'x': 'סטטוס', 'y': 'כמות'})
            fig.update_layout(
                title_x=0.5,
                title_xanchor='center',
                font_family="Arial",
                font=dict(size=14),
                title_font=dict(size=20),
                xaxis=dict(side='bottom', title_standoff=25),
                yaxis=dict(side='right', title_standoff=25)
            )
            st.plotly_chart(fig)
            
            # Meeting Interest Analysis
            if 'מעוניין לקבוע פגישה' in df.columns:
                st.subheader("ניתוח העדפות פגישה")
                meeting_interest = df['מעוניין לקבוע פגישה'].value_counts()
                fig = px.pie(values=meeting_interest.values,
                            names=meeting_interest.index,
                            title='התפלגות העדפות פגישה')
                fig.update_layout(
                    title_x=0.5,
                    title_xanchor='center',
                    font_family="Arial",
                    font=dict(size=14),
                    title_font=dict(size=20)
                )
                st.plotly_chart(fig)
            
            # Response Time Analysis
            st.subheader("ניתוח זמני תגובה")
            df['תאריך יצירה'] = pd.to_datetime(df['תאריך יצירה'])
            df['שעה'] = df['תאריך יצירה'].dt.hour
            hourly_responses = df['שעה'].value_counts().sort_index()
            fig = px.line(x=hourly_responses.index,
                         y=hourly_responses.values,
                         title='התפלגות תגובות לפי שעה',
                         labels={'x': 'שעה ביום', 'y': 'מספר תגובות'})
            fig.update_layout(
                title_x=0.5,
                title_xanchor='center',
                font_family="Arial",
                font=dict(size=14),
                title_font=dict(size=20),
                xaxis=dict(side='bottom', title_standoff=25),
                yaxis=dict(side='right', title_standoff=25)
            )
            st.plotly_chart(fig)
            
    except Exception as e:
        st.error(f"שגיאה בטעינת נתוני אנליטיקה: {str(e)}")

elif page == "הגדרות בוט":
    st.header("⚙️ הגדרות בוט")
    
    # Display current environment variables
    st.subheader("משתני סביבה")
    env_vars = {
        "ID_INSTANCE": os.getenv("ID_INSTANCE"),
        "API_TOKEN_INSTANCE": "***" + os.getenv("API_TOKEN_INSTANCE")[-4:] if os.getenv("API_TOKEN_INSTANCE") else None,
        "GEMINI_API_KEY": "***" + os.getenv("GEMINI_API_KEY")[-4:] if os.getenv("GEMINI_API_KEY") else None,
        "AIRTABLE_API_KEY": "***" + os.getenv("AIRTABLE_API_KEY")[-4:] if os.getenv("AIRTABLE_API_KEY") else None,
    }
    
    st.json(json.dumps(env_vars, indent=2))
    
    # Bot Status and Controls
    st.subheader("סטטוס ובקרת בוט")
    col1, col2 = st.columns(2)
    
    # Get the bot URL from environment variable or use default
    BOT_URL = os.getenv("BOT_URL", "https://your-bot-url.onrender.com")
    
    with col1:
        if st.button("בדוק סטטוס בוט"):
            try:
                # Add timeout to prevent long waits
                response = requests.get(f"{BOT_URL}/health", timeout=5)
                if response.status_code == 200:
                    st.success("הבוט פעיל ותקין! 🟢")
                else:
                    st.error(f"הבוט אינו מגיב כראוי 🔴 (קוד {response.status_code})")
            except requests.exceptions.ConnectionError:
                st.error(f"""
                לא ניתן להתחבר לבוט בכתובת {BOT_URL}
                
                אנא וודא:
                1. שהבוט רץ ופעיל
                2. שהכתובת נכונה (הגדר משתנה BOT_URL בקובץ .env)
                3. שיש גישה לשרת
                """)
            except requests.exceptions.Timeout:
                st.error("תם הזמן המוקצב לתשובה מהבוט")
            except Exception as e:
                st.error(f"שגיאה בבדיקת סטטוס הבוט: {str(e)}")
    
    with col2:
        if st.button("הצג לוגים"):
            try:
                with open("whatsapp_bot.log", "r", encoding="utf-8") as f:
                    logs = f.readlines()[-50:]  # Last 50 lines
                    st.code("".join(logs))
            except Exception as e:
                st.error(f"לא ניתן לקרוא לוגים: {str(e)}")
    
    # Webhook Configuration
    st.subheader("הגדרות Webhook")
    webhook_url = st.text_input("כתובת Webhook", "http://your-domain.com/webhook")
    if st.button("עדכן Webhook"):
        st.info("תכונה זו תהיה זמינה בקרוב")
    
    # System Information
    st.subheader("מידע מערכת")
    system_info = {
        "גרסת Python": os.sys.version.split()[0],
        "מערכת הפעלה": os.name,
        "תיקייה נוכחית": os.getcwd(),
        "מספר ליבות מעבד זמינות": os.cpu_count()
    }
    st.json(json.dumps(system_info, indent=2))

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("נוצר באהבה ❤️")
st.sidebar.markdown(f"עודכן לאחרונה: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

router = APIRouter()
airtable_service = AirtableService(
    api_key=os.getenv("AIRTABLE_API_KEY"),
    base_id=os.getenv("AIRTABLE_BASE_ID")
)

@router.get("/surveys/stats")
async def get_surveys_stats() -> Dict:
    """Get statistics for all surveys"""
    try:
        # Implementation of your existing dashboard logic here
        return {"status": "Not implemented yet"}
    except Exception as e:
        logger.error(f"Error getting survey stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/surveys/{survey_id}/responses")
async def get_survey_responses(survey_id: str) -> List[Dict]:
    """Get all responses for a specific survey"""
    try:
        # Implementation of your existing dashboard logic here
        return []
    except Exception as e:
        logger.error(f"Error getting survey responses: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 