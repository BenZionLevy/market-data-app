import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
from io import BytesIO
import warnings
import re

warnings.filterwarnings('ignore')

st.set_page_config(page_title="מחולל נתוני שוק", page_icon="📊", layout="centered")

st.markdown("""
<style>
    .stApp {
        background-image: url("https://images.unsplash.com/photo-1579532537598-459ecdaf39cc?q=80&w=2000&auto=format&fit=crop");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }
    .block-container { 
        background-color: rgba(255, 255, 255, 0.95);
        padding: 3rem; border-radius: 15px; margin-top: 2rem;
        box-shadow: 0 8px 16px rgba(0,0,0,0.1);
    }
    .block-container, p, h1, h2, h3, h4, h5, h6, label, .stAlert, div[data-testid="stForm"] {
        direction: rtl !important; text-align: right !important;
    }
    .stTextInput input {
        direction: rtl !important; text-align: right !important;
        border: 2px solid #007BFF !important; border-radius: 10px !important;
        padding: 15px !important; font-size: 18px !important;
        box-shadow: 0 0 15px rgba(0, 123, 255, 0.2) !important;
        background-color: #f4f9ff !important; transition: all 0.3s ease-in-out;
    }
</style>
""", unsafe_allow_html=True)

if 'excel_file' not in st.session_state:
    st.session_state.excel_file = None
    st.session_state.success_message = ""
    st.session_state.interval_info = ""

st.title("מחולל נתוני שוק אוטומטי")
st.info("🕒 **שימו לב:** נתונים שעתיים מתורגמים תמיד ל**שעון ישראל**. המערכת מבצעת מילוי אוטומטי לשעות ללא מסחר.")

with st.form(key='search_form'):
    user_input = st.text_input("הקלד את בקשתך כאן ולחץ אנטר (Enter):")
    submit_button = st.form_submit_button("🚀 נתח והפק אקסל")

if submit_button:
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=api_key, transport='rest')
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""
        Analyze the user request: "{user_input}"
        Return ONLY a valid JSON.
        Israeli Dictionary: ת"א 35=TA35.TA, דולר/שקל=ILS=X, S&P 500=ES=F, לאומי=LUMI.TA, פועלים=POLI.TA.
        Mode: "compare_hours" (specific hours), "all_hours" (continuous), or "daily".
        """
        
        response = model.generate_content(prompt)
        data = json.loads(response.text.replace('```json', '').replace('```', '').strip())
        
        tickers = [t for t in data.get("tickers", []) if not re.search(r'[\u0590-\u05FF]', t)]
        period = data.get("period", "1y")
        mode = data.get("mode", "daily")
        start_hour, end_hour = data.get("start_hour", 11), data.get("end_hour", 14)
        interval = "1h" if mode in ["compare_hours", "all_hours"] else "1d"

        all_results = {}
        for sym in tickers:
            df = yf.download(sym, period=period, interval=interval, auto_adjust=False, progress=False)
            if df.empty: continue
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            if interval == "1h":
                if df.index.tz is None:
                    df.index = df.index.tz_localize('UTC').tz_convert('Asia/Jerusalem')
                else:
                    df.index = df.index.tz_convert('Asia/Jerusalem')
                
                # תיקון קריטי: מילוי ללא הגבלת זמן (מסיר את ה'חורים')
                df = df[~df.index.duplicated(keep='first')].resample('h').ffill()
                
                if mode == "compare_hours":
                    df_start = df[df.index.hour == start_hour][['Close']].copy()
                    df_end = df[df.index.hour == end_hour][['Close']].copy()
                    df_start['Date_obj'], df_end['Date_obj'] = df_start.index.date, df_end.index.date
                    merged = pd.merge(df_start, df_end, on='Date_obj', how='outer', suffixes=('_start', '_end'))
                    merged.dropna(subset=['Close_start', 'Close_end'], inplace=True)
                    merged['Date'] = pd.to_datetime(merged['Date_obj']).dt.strftime('%d/%m/%Y')
                    merged['Yield'] = (merged['Close_end'] / merged['Close_start']) - 1
                    all_results[sym] = merged[['Date', 'Close_start', 'Close_end', 'Yield']]
                
                else: # all_hours
                    df_all = df[['Close']].copy()
                    df_all['Date'] = df_all.index.strftime('%d/%m/%Y')
                    df_all['Time'] = df_all.index.strftime('%H:%M')
                    df_all['Yield'] = (df_all['Close'] / df_all['Close'].shift(1)) - 1
                    all_results[sym] = df_all[['Date', 'Time', 'Close', 'Yield']]
            
            else: # daily
                df_daily = df[['Open', 'Close']].copy()
                df_daily['Date'] = df_daily.index.strftime('%d/%m/%Y')
                df_daily['Yield'] = (df_daily['Close'] / df_daily['Close'].shift(1)) - 1
                all_results[sym] = df_daily[['Date', 'Open', 'Close', 'Yield']]

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            col = 0
            for s, d in all_results.items():
                pd.Series([f"נכס: {s}"]).to_excel(writer, startrow=0, startcol=col, index=False, header=False)
                d.to_excel(writer, startrow=1, startcol=col, index=False)
                col += len(d.columns) + 1
        
        st.session_state.excel_file = buf.getvalue()
        st.success("✅ הקובץ מוכן עם נתונים רציפים!")
        st.download_button("📥 הורד אקסל", st.session_state.excel_file, "Market_Report.xlsx")

    except Exception as e:
        st.error(f"❌ שגיאה: {e}")
