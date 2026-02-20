import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
from io import BytesIO
import warnings

warnings.filterwarnings('ignore')

st.set_page_config(page_title="מחולל נתוני שוק", page_icon="📈", layout="centered")

st.title("📈 מחולל נתוני שוק חכם")
st.markdown("הכנס בקשה חופשית, והמערכת תייצר עבורך קובץ אקסל מסודר.")

# סרגל צד להכנסת מפתח API
with st.sidebar:
    st.header("הגדרות")
    api_key = st.text_input("הכנס מפתח Gemini API:", type="password")
    st.markdown("[לחץ כאן ליצירת מפתח חינמי](https://aistudio.google.com/app/apikey)")

user_input = st.text_area("מה תרצה לבדוק?", placeholder="לדוגמה: תביא לי את תל אביב 35, לאומי ודולר שקל לשנה אחרונה מ-11 עד 14.")

if st.button("🚀 הפק נתונים לאקסל"):
    if not api_key:
        st.error("אנא הכנס מפתח API בסרגל הצד.")
        st.stop()
    if not user_input:
        st.error("אנא הקלד בקשה.")
        st.stop()
        
    st.info("מנתח את הבקשה ומוריד נתונים... זה עשוי לקחת מספר שניות.")
    
    try:
        # הגדרת ג'ימיני
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        Extract the financial assets and time period from this user request: "{user_input}"
        Rules:
        1. Translate Israeli assets to their Yahoo Finance tickers. 
           Dictionary: ת"א 35 = TA35.TA, דולר/שקל = ILS=X, S&P 500 = ES=F, בנק לאומי = LUMI.TA, בנק הפועלים = POLI.TA.
        2. Determine the period (e.g., '1y', '6mo', '729d'). Default is '1y' if not specified.
        3. Output ONLY a valid, raw JSON object exactly like this, no markdown formatting, no backticks, no extra text:
        {{"tickers": ["TA35.TA", "LUMI.TA"], "period": "1y"}}
        """
        
        response = model.generate_content(prompt)
        # ניקוי הטקסט למקרה שג'ימיני מוסיף תווים
        cleaned_response = response.text.replace('```json', '').replace('```', '').strip()
        parsed_data = json.loads(cleaned_response)
        
        tickers = parsed_data.get("tickers", [])
        period = parsed_data.get("period", "1y")
        
        if not tickers:
            st.error("לא הצלחתי לזהות נכסים בבקשה שלך.")
            st.stop()
            
        all_dfs = {}
        
        # לולאת ההורדה והעיבוד שלנו
        for symbol in tickers:
            df = yf.download(symbol, period=period, interval="1h", auto_adjust=False, progress=False)
            if df.empty:
                continue
                
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert('Asia/Jerusalem')
            else:
                df.index = df.index.tz_convert('Asia/Jerusalem')
                
            # סינון שעות והשלמת חוסרים
            df = df[~df.index.duplicated(keep='first')]
            df = df.resample('h').ffill(limit=4)
            
            df_11 = df[df.index.hour == 11][['Close']].copy()
            df_14 = df[df.index.hour == 14][['Close']].copy()
            
            df_11['Date'] = df_11.index.strftime('%d/%m/%Y')
            df_14['Date'] = df_14.index.strftime('%d/%m/%Y')
            
            merged = pd.merge(df_11, df_14, on='Date', how='outer', suffixes=('_11', '_14'))
            if merged.empty:
                continue
                
            merged['Time_11'] = '11:00'
            merged['Time_14'] = '14:00'
            merged['Yield'] = (merged['Close_14'] / merged['Close_11']) - 1
            
            final_df = merged[['Date', 'Time_11', 'Close_11', 'Time_14', 'Close_14', 'Yield']]
            all_dfs[symbol] = final_df

        if not all_dfs:
            st.warning("לא נמצאו נתונים תקינים עבור הנכסים שביקשת. ייתכן שיאהו חסום או חסר נתונים.")
            st.stop()
            
        # יצירת קובץ האקסל בזיכרון
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            start_col = 0
            for sym, data in all_dfs.items():
                pd.Series([sym]).to_excel(writer, startrow=0, startcol=start_col, index=False, header=False)
                data.to_excel(writer, startrow=1, startcol=start_col, index=False)
                start_col += len(data.columns) + 1
        
        excel_data = output.getvalue()
        
        st.success("הקובץ מוכן!")
        st.download_button(label="📥 הורד קובץ אקסל",
                           data=excel_data,
                           file_name="Market_Data.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                           
    except Exception as e:
        st.error(f"אירעה שגיאה: {e}")
