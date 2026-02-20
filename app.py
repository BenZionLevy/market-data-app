import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
from io import BytesIO
import warnings
import os

# השתקת אזהרות
warnings.filterwarnings('ignore')

st.set_page_config(page_title="מחולל נתוני שוק", page_icon="📈", layout="centered")

st.title("📈 מחולל נתוני שוק חכם")
st.markdown("הכנס בקשה חופשית (למשל: תל אביב 35 ולאומי לשנה אחרונה), והמערכת תייצר עבורך קובץ אקסל.")

# סרגל צד
with st.sidebar:
    st.header("הגדרות מערכת")
    api_key = st.text_input("הכנס מפתח Gemini API:", type="password")
    st.markdown("[לינק ליצירת מפתח חינמי](https://aistudio.google.com/app/apikey)")

user_input = st.text_area("מה תרצה לבדוק?", placeholder="לדוגמה: דולר שקל, תל אביב 35 ופועלים לשנתיים האחרונות.")

if st.button("🚀 הפק נתונים לאקסל"):
    if not api_key:
        st.error("אנא הכנס מפתח API בסרגל הצד.")
        st.stop()
    if not user_input:
        st.error("אנא הקלד את הבקשה שלך.")
        st.stop()
        
    st.info("מנתח את הבקשה ומוריד נתונים... אנא המתן.")
    
    try:
        # הגדרה קשיחה לגרסה היציבה v1
        os.environ["GOOGLE_API_USE_MTLS"] = "never"
        genai.configure(api_key=api_key, transport='rest') # שימוש ב-REST למניעת שגיאות גרסה
        
        # שימוש במודל הפלאש היציב
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        Extract financial assets and period from this request: "{user_input}"
        Rules:
        1. Mapping: ת"א 35 = TA35.TA, דולר/שקל = ILS=X, S&P 500 = ES=F, לאומי = LUMI.TA, פועלים = POLI.TA, מדד הבנקים = TELB.TA.
        2. If an asset is not in the list, find its Yahoo Finance ticker.
        3. Return ONLY a JSON object: {{"tickers": ["TICKER1"], "period": "1y"}}
        """
        
        response = model.generate_content(prompt)
        
        # ניקוי ופענוח JSON
        cleaned_json = response.text.replace('```json', '').replace('```', '').strip()
        parsed_data = json.loads(cleaned_json)
        
        tickers = parsed_data.get("tickers", [])
        period = parsed_data.get("period", "1y")
        
        if not tickers:
            st.error("לא הצלחתי לזהות נכסים.")
            st.stop()
            
        all_dfs = {}
        
        for symbol in tickers:
            df = yf.download(symbol, period=period, interval="1h", auto_adjust=False, progress=False)
            if df.empty: continue
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # תיקון אזור זמן לישראל
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert('Asia/Jerusalem')
            else:
                df.index = df.index.tz_convert('Asia/Jerusalem')
            
            # השלמת נתונים
            df = df[~df.index.duplicated(keep='first')]
            df = df.resample('h').ffill(limit=4)
            
            df_11 = df[df.index.hour == 11][['Close']].copy()
            df_14 = df[df.index.hour == 14][['Close']].copy()
            
            df_11['Date'] = df_11.index.strftime('%d/%m/%Y')
            df_14['Date'] = df_14.index.strftime('%d/%m/%Y')
            
            merged = pd.merge(df_11, df_14, on='Date', how='outer', suffixes=('_11', '_14'))
            if merged.empty: continue
            
            merged['Time_11'] = '11:00'
            merged['Time_14'] = '14:00'
            merged['Yield'] = (merged['Close_14'] / merged['Close_11']) - 1
            
            final_df = merged[['Date', 'Time_11', 'Close_11', 'Time_14', 'Close_14', 'Yield']]
            all_dfs[symbol] = final_df

        if not all_dfs:
            st.warning("לא נמצאו נתונים תקינים.")
            st.stop()
            
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            start_col = 0
            for sym, data in all_dfs.items():
                pd.Series([f"נכס: {sym}"]).to_excel(writer, startrow=0, startcol=start_col, index=False, header=False)
                data.to_excel(writer, startrow=1, startcol=start_col, index=False)
                start_col += len(data.columns) + 1
        
        st.success("✅ הצלחנו!")
        st.download_button(label="📥 הורד קובץ אקסל",
                           data=output.getvalue(),
                           file_name="Market_Report.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                           
    except Exception as e:
        st.error(f"שגיאה: {e}")
