import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import requests  # וודא שהשורה הזו קיימת
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
        padding: 3rem; 
        border-radius: 15px; 
        margin-top: 2rem;
        box-shadow: 0 8px 16px rgba(0,0,0,0.1);
    }

    .block-container, p, h1, h2, h3, h4, h5, h6, label, .stAlert, div[data-testid="stForm"] {
        direction: rtl !important;
        text-align: right !important;
    }
    
    .stTextInput input {
        direction: rtl !important;
        text-align: right !important;
        border: 2px solid #007BFF !important;
        border-radius: 10px !important;
        padding: 15px !important;
        font-size: 18px !important;
        box-shadow: 0 0 15px rgba(0, 123, 255, 0.2) !important;
        background-color: #f4f9ff !important;
        transition: all 0.3s ease-in-out;
    }
    
    .stTextInput input:focus {
        border-color: #17B169 !important;
        box-shadow: 0 0 20px rgba(23, 177, 105, 0.4) !important;
        background-color: #ffffff !important;
    }

    [data-testid="stDownloadButton"] button {
        background-color: #17B169; color: white; border-radius: 8px; font-weight: bold; width: 100%; margin-top: 15px; border: none; font-size: 16px;
    }
    [data-testid="stDownloadButton"] button:hover { background-color: #128C53; color: white; }
    [data-testid="stFormSubmitButton"] button {
        border-radius: 8px; font-weight: bold; width: 100%; background-color: #007BFF; color: white;
    }
    [data-testid="stFormSubmitButton"] button:hover { background-color: #0056b3; color: white; }
</style>
""", unsafe_allow_html=True)

if 'excel_file' not in st.session_state:
    st.session_state.excel_file = None
    st.session_state.success_message = ""
    st.session_state.interval_info = ""

st.title("מחולל נתוני שוק אוטומטי")
st.markdown("ברוכים הבאים למערכת החכמה להפקת נתוני מסחר. המערכת מבינה שפה חופשית ותכין עבורכם קובץ אקסל מסודר (יומי או שעתי).")

st.info("🕒 **שימו לב:** נתונים שעתיים מתורגמים תמיד ל**שעון ישראל**. נתונים יומיים מוצגים לפי תאריך יום המסחר המקורי של הבורסה.")
st.divider()

st.subheader("מה ברצונך לבדוק?")
instruction = "לדוגמה: CAC 40 שנה אחורה / מניית אפל וטסלה כל שעה / תא 35 בין 11:00 ל-14:00."

with st.form(key='search_form'):
    user_input = st.text_input("הקלד את בקשתך כאן ולחץ אנטר (Enter):", placeholder=instruction)
    submit_button = st.form_submit_button("🚀 נתח והפק אקסל")

if submit_button:
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        st.error("🔒 שגיאה: לא הוגדר מפתח API. אנא הוסף את המפתח להגדרות ה-Secrets ב-Streamlit Cloud.")
        st.stop()
        
    if not user_input.strip():
        st.warning("✍️ אנא הכנס בקשה בתיבת הטקסט.")
        st.stop()
        
    try:
        with st.spinner("🤖 מנתח את הבקשה, מתחבר לבורסה ומכין את הנתונים... אנא המתן ⏳"):
            genai.configure(api_key=api_key, transport='rest')
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            prompt = f"""
            You are an expert financial data extraction system.
            Analyze the user request: "{user_input}"
            Return ONLY a valid JSON object.

            TICKER IDENTIFICATION ALGORITHM:
            1. ISRAELI DICTIONARY: ONLY if the user explicitly asks for these specific Israeli terms, use this exact mapping: ת"א 35=TA35.TA, דולר/שקל=ILS=X, S&P 500=ES=F, לאומי=LUMI.TA, פועלים=POLI.TA, בנקים=TELB.TA.
            2. GLOBAL SEARCH: For ANY other asset globally (indices, stocks, crypto), ignore the Israeli dictionary. Use your vast knowledge to find its official Yahoo Finance ticker. 
            3. NO FALLBACK: If the user misspells a global asset (e.g., "AC 40" instead of CAC 40), resolve the spelling error intelligently. NEVER default to TA35.TA or any other local asset unless requested.
            4. FORMAT: The "tickers" array MUST contain ONLY official English/Symbol tickers. No Hebrew text.

            DATA PARAMETERS:
            - "tickers": list of strings.
            - "period": valid yfinance period (e.g., "1mo", "1y", "729d"). If hourly requested and period is over 2 years, max is "729d".
            - "mode": "compare_hours" (if user asks to compare specific hours), "all_hours" (if user asks for every hour continuously), or "daily" (default).
            - "start_hour": integer (0-23), only if mode is "compare_hours". Default is 11.
            - "end_hour": integer (0-23), only if mode is "compare_hours". Default is 14.
            """
            
            response = model.generate_content(prompt)
            clean_text = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(clean_text)
            
            raw_tickers = data.get("tickers", [])
            tickers = [t for t in raw_tickers if not re.search(r'[\u0590-\u05FF]', t)]
            
            period = data.get("period", "1y")
            mode = data.get("mode", "daily")
            start_hour = data.get("start_hour", 11)
            end_hour = data.get("end_hour", 14)

            interval = "1h" if mode in ["compare_hours", "all_hours"] else "1d"

            if not tickers:
                st.error("❌ לא הצלחתי לזהות נכסים באנגלית בבקשה שלך. נסה לנסח שוב.")
                st.stop()

            all_results = {}
            for sym in tickers:
                df = yf.download(sym, period=period, interval=interval, auto_adjust=False, progress=False)
                if df.empty: continue
                
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                if mode == "compare_hours":
                    if df.index.tz is None:
                        df.index = df.index.tz_localize('UTC').tz_convert('Asia/Jerusalem')
                    else:
                        df.index = df.index.tz_convert('Asia/Jerusalem')
                        
                    df = df[~df.index.duplicated(keep='first')].resample('h').ffill(limit=4)
                    df_start = df[df.index.hour == start_hour][['Close']].copy()
                    df_end = df[df.index.hour == end_hour][['Close']].copy()
                    
                    df_start['Date_obj'] = df_start.index.date
                    df_end['Date_obj'] = df_end.index.date
                    
                    merged = pd.merge(df_start, df_end, on='Date_obj', how='outer', suffixes=('_start', '_end'))
                    merged.dropna(subset=['Close_start', 'Close_end'], inplace=True)
                    if merged.empty: continue
                    
                    merged['Date_obj'] = pd.to_datetime(merged['Date_obj'])
                    merged = merged.sort_values('Date_obj')
                    merged['Date'] = merged['Date_obj'].dt.strftime('%d/%m/%Y')
                    
                    merged[f'Time_{start_hour}'] = f'{start_hour}:00'
                    merged[f'Time_{end_hour}'] = f'{end_hour}:00'
                    merged['Yield'] = (merged['Close_end'] / merged['Close_start']) - 1
                    
                    cols = ['Date', f'Time_{start_hour}', 'Close_start', f'Time_{end_hour}', 'Close_end', 'Yield']
                    all_results[sym] = merged[cols]
                
                elif mode == "all_hours":
                    if df.index.tz is None:
                        df.index = df.index.tz_localize('UTC').tz_convert('Asia/Jerusalem')
                    else:
                        df.index = df.index.tz_convert('Asia/Jerusalem')
                        
                    df = df[~df.index.duplicated(keep='first')].resample('h').ffill(limit=4)
                    df.dropna(subset=['Close'], inplace=True)
                    
                    df_all = df[['Close']].copy()
                    df_all['Date'] = df_all.index.strftime('%d/%m/%Y')
                    df_all['Time'] = df_all.index.strftime('%H:%M')
                    df_all['Yield'] = (df_all['Close'] / df_all['Close'].shift(1)) - 1
                    
                    all_results[sym] = df_all[['Date', 'Time', 'Close', 'Yield']]
                    
                else: 
                    df = df[~df.index.duplicated(keep='first')]
                    df_daily = df[['Open', 'Close']].copy()
                    
                    df_daily['Date_obj'] = df_daily.index.date
                    df_daily['Date_obj'] = pd.to_datetime(df_daily['Date_obj'])
                    df_daily = df_daily.sort_values('Date_obj')
                    df_daily.dropna(subset=['Open', 'Close'], inplace=True)
                    
                    df_daily['Date'] = df_daily['Date_obj'].dt.strftime('%d/%m/%Y')
                    df_daily['Yield'] = (df_daily['Close'] / df_daily['Close'].shift(1)) - 1
                    all_results[sym] = df_daily[['Date', 'Open', 'Close', 'Yield']]

            if not all_results:
                st.warning(f"⚠️ לא נמצאו נתונים תקינים עבור הנכסים שביקשת ({', '.join(tickers)}).")
                st.stop()

            buf = BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                col = 0
                for s, d in all_results.items():
                    pd.Series([f"נכס: {s}"]).to_excel(writer, startrow=0, startcol=col, index=False, header=False)
                    d.to_excel(writer, startrow=1, startcol=col, index=False)
                    col += len(d.columns) + 1
            
            st.session_state.excel_file = buf.getvalue()
            st.session_state.success_message = f"✅ סיימתי! משכתי נתונים עבור {len(all_results)} נכסים ({', '.join(tickers)})."
            
            if mode == "compare_hours":
                st.session_state.interval_info = f"📊 הקובץ כולל השוואה בין השעה {start_hour}:00 לשעה {end_hour}:00."
            elif mode == "all_hours":
                st.session_state.interval_info = "📊 הקובץ כולל נתונים רציפים עבור כל שעת מסחר."
            else:
                st.session_state.interval_info = "📊 הקובץ כולל נתונים ברזולוציה יומית."

    except Exception as e:
        st.error(f"❌ אירעה שגיאה בעיבוד. נסה שוב בעוד כמה שניות. (פירוט טכני: {e})")

if st.session_state.excel_file is not None:
    st.success(st.session_state.success_message)
    st.info(st.session_state.interval_info)
    
    st.download_button(
        label="📥 הורד את קובץ האקסל שלך עכשיו", 
        data=st.session_state.excel_file, 
        file_name="Market_Report.xlsx", 
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
