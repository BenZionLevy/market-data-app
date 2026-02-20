import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
from io import BytesIO
import warnings

# השתקת אזהרות
warnings.filterwarnings('ignore')

# הגדרת דף האתר
st.set_page_config(page_title="מחולל נתוני שוק", page_icon="📈", layout="centered")

st.title("📈 מחולל נתוני שוק חכם")
st.markdown("הכנס בקשה חופשית (למשל: תל אביב 35 ולאומי לשנה אחרונה), והמערכת תייצר עבורך קובץ אקסל.")

# סרגל צד להגדרות
with st.sidebar:
    st.header("הגדרות מערכת")
    api_key = st.text_input("הכנס מפתח Gemini API:", type="password")
    st.markdown("[לינק ליצירת מפתח חינמי](https://aistudio.google.com/app/apikey)")
    st.info("האתר משתמש במודל Gemini 1.5 Flash לניתוח השאילתות.")

user_input = st.text_area("מה תרצה לבדוק?", placeholder="לדוגמה: דולר שקל, תל אביב 35 ופועלים לשנתיים האחרונות מ-11 עד שתיים.")

if st.button("🚀 הפק נתונים לאקסל"):
    if not api_key:
        st.error("אנא הכנס מפתח API בסרגל הצד.")
        st.stop()
    if not user_input:
        st.error("אנא הקלד את הבקשה שלך.")
        st.stop()
        
    st.info("מנתח את הבקשה ומוריד נתונים... אנא המתן.")
    
    try:
        # הגדרת ה-API של גוגל
        genai.configure(api_key=api_key)
        
        # שימוש במודל בגרסה היציבה
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # פרומפט משופר לחילוץ נתונים
        prompt = f"""
        Extract financial assets and period from this request: "{user_input}"
        Rules:
        1. Mapping: ת"א 35 = TA35.TA, דולר/שקל = ILS=X, S&P 500 = ES=F, לאומי = LUMI.TA, פועלים = POLI.TA, מדד הבנקים = TELB.TA.
        2. If an asset is not in the list, find its Yahoo Finance ticker (e.g., .TA for Israeli stocks).
        3. Period: '1y', '2y', '6mo', etc. Max for intraday is '729d'.
        4. Return ONLY a JSON object: {{"tickers": ["TICKER1", "TICKER2"], "period": "period_code"}}
        """
        
        response = model.generate_content(prompt)
        
        # ניקוי תגיות markdown מהתשובה של ה-AI
        json_text = response.text.replace('```json', '').replace('```', '').strip()
        parsed_data = json.loads(json_text)
        
        tickers = parsed_data.get("tickers", [])
        period = parsed_data.get("period", "1y")
        
        if not tickers:
            st.error("לא הצלחתי לזהות נכסים בבקשה.")
            st.stop()
            
        all_dfs = {}
        
        for symbol in tickers:
            # הורדה עם חסינות לבעיות זמן
            df = yf.download(symbol, period=period, interval="1h", auto_adjust=False, progress=False)
            
            if df.empty:
                continue
            
            # ניקוי עמודות
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # טיפול באזור זמן - תיקון לישראל
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert('Asia/Jerusalem')
            else:
                df.index = df.index.tz_convert('Asia/Jerusalem')
            
            # השלמת שעות חסרות (Forward Fill) כדי למנוע השמטת נכסים ישראליים
            df = df[~df.index.duplicated(keep='first')]
            df = df.resample('h').ffill(limit=4)
            
            # חילוץ שעות 11 ו-14
            df_11 = df[df.index.hour == 11][['Close']].copy()
            df_14 = df[df.index.hour == 14][['Close']].copy()
            
            df_11['Date'] = df_11.index.strftime('%d/%m/%Y')
            df_14['Date'] = df_14.index.strftime('%d/%m/%Y')
            
            # מיזוג גמיש (Outer)
            merged = pd.merge(df_11, df_14, on='Date', how='outer', suffixes=('_11', '_14'))
            
            if merged.empty:
                continue
            
            merged['Time_11'] = '11:00'
            merged['Time_14'] = '14:00'
            merged['Yield'] = (merged['Close_14'] / merged['Close_11']) - 1
            
            final_df = merged[['Date', 'Time_11', 'Close_11', 'Time_14', 'Close_14', 'Yield']]
            all_dfs[symbol] = final_df

        if not all_dfs:
            st.warning("לא נמצאו נתונים עבור הנכסים שצוינו.")
            st.stop()
            
        # יצירת קובץ אקסל
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            start_col = 0
            for sym, data in all_dfs.items():
                pd.Series([f"נכס: {sym}"]).to_excel(writer, startrow=0, startcol=start_col, index=False, header=False)
                data.to_excel(writer, startrow=1, startcol=start_col, index=False)
                start_col += len(data.columns) + 1
        
        st.success("✅ הקובץ נוצר בהצלחה!")
        st.download_button(label="📥 הורד קובץ אקסל",
                           data=output.getvalue(),
                           file_name="Market_Report.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                           
    except Exception as e:
        st.error(f"אירעה שגיאה טכנית: {e}")
