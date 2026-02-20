import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
from io import BytesIO
import warnings
import re

warnings.filterwarnings('ignore')

st.set_page_config(page_title="מחולל נתוני שוק", page_icon="📈", layout="centered")

st.markdown("""
<style>
    .block-container { direction: rtl; text-align: right; }
    [data-testid="stDownloadButton"] button {
        background-color: #17B169; color: white; border-radius: 8px; font-weight: bold; width: 100%; margin-top: 15px; border: none;
    }
    [data-testid="stDownloadButton"] button:hover { background-color: #128C53; color: white; }
    .stButton > button { border-radius: 8px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("📈 מחולל נתוני שוק אוטומטי")
st.markdown("ברוכים הבאים למערכת החכמה להפקת נתוני מסחר. המערכת מבינה שפה חופשית ותכין עבורכם קובץ אקסל מסודר (יומי או שעתי).")
st.divider()

with st.sidebar:
    st.header("⚙️ הגדרות מערכת")
    api_key = st.text_input("הכנס מפתח Gemini API:", type="password")
    st.caption("[לחץ כאן להוצאת מפתח חינמי מגוגל](https://aistudio.google.com/app/apikey)")
    st.divider()
    st.markdown("💡 **טיפ:** אם מופיעה שגיאה, המתן כדקה ונסה שוב.")

st.subheader("מה ברצונך לבדוק?")
instruction = "לדוגמה: תא 35 ודולר לשנה אחרונה / פועלים ולאומי לחודש אחרון בין 11:00 ל-14:00."
user_input = st.text_area("הקלד את בקשתך כאן:", placeholder=instruction, height=100)

if st.button("🚀 נתח והפק אקסל", use_container_width=True):
    if not api_key:
        st.error("🔒 אנא הכנס מפתח API בסרגל הצד.")
        st.stop()
    if not user_input.strip():
        st.warning("✍️ אנא הכנס בקשה בתיבת הטקסט.")
        st.stop()
        
    try:
        with st.spinner("🤖 מנתח את הבקשה, מתחבר לבורסה ומכין את הנתונים... אנא המתן ⏳"):
            
            genai.configure(api_key=api_key, transport='rest')
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            prompt = f"""
            Analyze the user request: "{user_input}"
            Extract the required financial data parameters and return ONLY a valid JSON object.
            Map assets to tickers: ת"א 35=TA35.TA, דולר/שקל=ILS=X, S&P 500=ES=F, לאומי=LUMI.TA, פועלים=POLI.TA, בנקים=TELB.TA. 
            CRITICAL RULE: The "tickers" array MUST contain ONLY official English/Symbol tickers. NEVER return Hebrew text in the "tickers" array.
            Rules for JSON fields:
            - "tickers": list of strings (tickers).
            - "period": valid yfinance period (e.g., "1mo", "1y", "729d"). If hourly requested and period is over 2 years, max is "729d".
            - "interval": "1h" if user asks for specific hours or intraday. "1d" if user asks for daily data or doesn't mention hours.
            - "start_hour": integer (0-23), only if interval is "1h". Default is 11.
            - "end_hour": integer (0-23), only if interval is "1h". Default is 14.
            Example: {{"tickers": ["TA35.TA"], "period": "1mo", "interval": "1h", "start_hour": 11, "end_hour": 14}}
            """
            
            response = model.generate_content(prompt)
            clean_text = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(clean_text)
            
            raw_tickers = data.get("tickers", [])
            tickers = [t for t in raw_tickers if not re.search(r'[\u0590-\u05FF]', t)]
            
            period = data.get("period", "1y")
            interval = data.get("interval", "1d")
            start_hour = data.get("start_hour", 11)
            end_hour = data.get("end_hour", 14)

            if not tickers:
                st.error("❌ לא הצלחתי לזהות נכסים באנגלית בבקשה שלך. נסה לנסח שוב (למשל: לאומי ודולר שקל).")
                st.stop()

            all_results = {}
            for sym in tickers:
                df = yf.download(sym, period=period, interval=interval, auto_adjust=False, progress=False)
                if df.empty: continue
                
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                if df.index.tz is None:
                    df.index = df.index.tz_localize('UTC').tz_convert('Asia/Jerusalem')
                else:
                    df.index = df.index.tz_convert('Asia/Jerusalem')
                
                if interval == "1h":
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
                    
                else:
                    # --- לוגיקה יומית מתוקנת ---
                    df = df[~df.index.duplicated(keep='first')]
                    df_daily = df[['Open', 'Close']].copy()
                    
                    df_daily['Date_obj'] = df_daily.index.date
                    df_daily['Date_obj'] = pd.to_datetime(df_daily['Date_obj'])
                    df_daily = df_daily.sort_values('Date_obj')
                    df_daily.dropna(subset=['Open', 'Close'], inplace=True)
                    
                    df_daily['Date'] = df_daily['Date_obj'].dt.strftime('%d/%m/%Y')
                    
                    # התיקון הקריטי: חישוב תשואה יומית (סגירה נוכחית חלקי סגירה של אתמול)
                    df_daily['Yield'] = (df_daily['Close'] / df_daily['Close'].shift(1)) - 1
                    
                    all_results[sym] = df_daily[['Date', 'Open', 'Close', 'Yield']]

            if not all_results:
                st.warning("⚠️ לא נמצאו נתונים תקינים בבורסה (ייתכן שהבורסה הייתה סגורה בימים אלו).")
                st.stop()

            buf = BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                col = 0
                for s, d in all_results.items():
                    pd.Series([f"נכס: {s}"]).to_excel(writer, startrow=0, startcol=col, index=False, header=False)
                    d.to_excel(writer, startrow=1, startcol=col, index=False)
                    col += len(d.columns) + 1
        
        st.success(f"✅ סיימתי! משכתי נתונים נקיים ומסודרים עבור {len(all_results)} נכסים.")
        
        st.download_button(
            label="📥 הורד את קובץ האקסל שלך עכשיו", 
            data=buf.getvalue(), 
            file_name="Market_Report.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    except Exception as e:
        st.error(f"❌ אירעה שגיאה בעיבוד. נסה שוב בעוד כמה שניות. (פירוט טכני: {e})")
