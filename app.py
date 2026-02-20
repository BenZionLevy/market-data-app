import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
from io import BytesIO
import warnings

# השתקת אזהרות
warnings.filterwarnings('ignore')

st.set_page_config(page_title="מחולל נתוני שוק", page_icon="📈")

st.title("📈 מחולל נתוני שוק אוטומטי")
st.markdown("מערכת חכמה להפקת קבצי אקסל של נתוני מסחר (יומי או שעתי לבחירתך).")

# סרגל צד
with st.sidebar:
    st.header("הגדרות")
    api_key = st.text_input("הכנס מפתח Gemini API:", type="password")
    st.markdown("[לחץ כאן להוצאת מפתח חינמי](https://aistudio.google.com/app/apikey)")

instruction = "לדוגמה: תא 35 ודולר לשנה אחרונה ברזולוציה יומית / פועלים ולאומי לחודש אחרון בין 10:00 ל-16:00."
user_input = st.text_area("מה ברצונך לבדוק?", placeholder=instruction)

if st.button("🚀 הפק אקסל"):
    if not api_key:
        st.error("אנא הכנס מפתח API.")
        st.stop()
    
    if not user_input.strip():
        st.error("אנא הכנס בקשה.")
        st.stop()
        
    try:
        # הגדרת Gemini
        genai.configure(api_key=api_key, transport='rest')
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # פרומפט חכם ששואב גם את השעות והרזולוציה
        prompt = f"""
        Analyze the user request: "{user_input}"
        Extract the required financial data parameters and return ONLY a valid JSON object.
        Map assets to tickers: ת"א 35=TA35.TA, דולר/שקל=ILS=X, S&P 500=ES=F, לאומי=LUMI.TA, פועלים=POLI.TA, בנקים=TELB.TA. If not in list, guess the correct Yahoo Finance ticker.
        Rules for JSON fields:
        - "tickers": list of strings (tickers).
        - "period": valid yfinance period (e.g., "1mo", "1y", "729d"). If hourly requested and period is over 2 years, max is "729d".
        - "interval": "1h" if user asks for specific hours or intraday. "1d" if user asks for daily data or doesn't mention hours.
        - "start_hour": integer (0-23), only if interval is "1h". Default is 11.
        - "end_hour": integer (0-23), only if interval is "1h". Default is 14.
        Example: {{"tickers": ["TA35.TA"], "period": "1mo", "interval": "1h", "start_hour": 10, "end_hour": 15}}
        """
        
        # קבלת תשובה מ-Gemini
        response = model.generate_content(prompt)
        
        # ניקוי ופענוח JSON
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_text)
        
        tickers = data.get("tickers", [])
        period = data.get("period", "1y")
        interval = data.get("interval", "1d")
        start_hour = data.get("start_hour", 11)
        end_hour = data.get("end_hour", 14)

        if not tickers:
            st.error("לא זוהו נכסים בבקשה.")
            st.stop()
            
        st.info(f"מוריד נתונים: {', '.join(tickers)} | תקופה: {period} | רזולוציה: {interval}" + 
                (f" | שעות: {start_hour}:00 - {end_hour}:00" if interval == "1h" else ""))

        all_results = {}
        for sym in tickers:
            # הורדה ועיבוד נתונים
            df = yf.download(sym, period=period, interval=interval, auto_adjust=False, progress=False)
            if df.empty: continue
            
            # שיטוח עמודות MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # תיקון אזור זמן
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert('Asia/Jerusalem')
            else:
                df.index = df.index.tz_convert('Asia/Jerusalem')
            
            # פיצול לוגיקה: לפי שעות (1h) או יומי (1d)
            if interval == "1h":
                # השלמת נתונים חסרים (Forward Fill)
                df = df[~df.index.duplicated(keep='first')].resample('h').ffill(limit=4)
                
                # חילוץ השעות המבוקשות
                df_start = df[df.index.hour == start_hour][['Close']].copy()
                df_end = df[df.index.hour == end_hour][['Close']].copy()
                
                df_start['Date'] = df_start.index.strftime('%d/%m/%Y')
                df_end['Date'] = df_end.index.strftime('%d/%m/%Y')
                
                merged = pd.merge(df_start, df_end, on='Date', how='outer', suffixes=('_start', '_end'))
                if merged.empty: continue
                
                merged[f'Time_{start_hour}'] = f'{start_hour}:00'
                merged[f'Time_{end_hour}'] = f'{end_hour}:00'
                merged['Yield'] = (merged['Close_end'] / merged['Close_start']) - 1
                
                cols = ['Date', f'Time_{start_hour}', 'Close_start', f'Time_{end_hour}', 'Close_end', 'Yield']
                all_results[sym] = merged[cols]
                
            else:
                # לוגיקה יומית (1d)
                df = df[~df.index.duplicated(keep='first')]
                df_daily = df[['Open', 'Close']].copy()
                df_daily['Date'] = df_daily.index.strftime('%d/%m/%Y')
                df_daily['Yield'] = (df_daily['Close'] / df_daily['Open']) - 1
                all_results[sym] = df_daily[['Date', 'Open', 'Close', 'Yield']]

        if not all_results:
            st.warning("לא נמצאו נתונים תקינים ביאהו פייננס.")
            st.stop()

        # כתיבה לאקסל
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            col = 0
            for s, d in all_results.items():
                pd.Series([f"נכס: {s}"]).to_excel(writer, startrow=0, startcol=col, index=False, header=False)
                d.to_excel(writer, startrow=1, startcol=col, index=False)
                col += len(d.columns) + 1
        
        st.success("✅ הקובץ מוכן להורדה!")
        st.download_button("📥 הורד אקסל", buf.getvalue(), "Market_Report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    except Exception as e:
        st.error(f"אירעה שגיאה: {e}")
