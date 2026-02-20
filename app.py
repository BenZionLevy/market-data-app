import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import json
from io import BytesIO
import warnings

# השתקת אזהרות
warnings.filterwarnings('ignore')

st.set_page_config(page_title="מחולל נתוני שוק", page_icon="📈")

st.title("📈 מחולל נתוני שוק אוטומטי")
st.markdown("מערכת להפקת קבצי אקסל של נתוני מסחר.")

# סרגל צד
with st.sidebar:
    st.header("הגדרות")
    api_key = st.text_input("הכנס מפתח Gemini API:", type="password")
    st.markdown("[לחץ כאן להוצאת מפתח חינמי](https://aistudio.google.com/app/apikey)")

instruction = "לדוגמה: תא 35, לאומי ודולר שקל לשנה אחרונה."
user_input = st.text_area("מה ברצונך לבדוק?", placeholder=instruction)

if st.button("🚀 הפק אקסל"):
    if not api_key:
        st.error("אנא הכנס מפתח API.")
        st.stop()
    
    try:
        # פתרון סופי: שימוש במודל בגרסת ה-Beta המעודכנת (v1beta)
        # שם המודל המדויק לגרסה זו הוא gemini-1.5-flash-latest
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
        
        prompt = f"""
        Extract assets and period from: "{user_input}"
        Map: ת"א 35=TA35.TA, דולר/שקל=ILS=X, S&P 500=ES=F, לאומי=LUMI.TA, פועלים=POLI.TA, בנקים=TELB.TA.
        Return ONLY JSON: {{"tickers": ["TICKER"], "period": "1y"}}
        """
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        
        response = requests.post(url, json=payload)
        
        if response.status_code != 200:
            st.error(f"שגיאה מהשרת של גוגל: {response.text}")
            st.stop()
            
        result_json = response.json()
        ai_text = result_json['candidates'][0]['content']['parts'][0]['text']
        
        # ניקוי ופענוח JSON
        clean_text = ai_text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_text)
        tickers = data.get("tickers", [])
        period = data.get("period", "1y")

        if not tickers:
            st.error("לא זוהו נכסים בבקשה.")
            st.stop()

        all_results = {}
        for sym in tickers:
            # הורדה ועיבוד נתונים
            df = yf.download(sym, period=period, interval="1h", auto_adjust=False, progress=False)
            if df.empty: continue
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # תיקון אזור זמן לישראל
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert('Asia/Jerusalem')
            else:
                df.index = df.index.tz_convert('Asia/Jerusalem')
            
            # השלמת נתונים חסרים (Forward Fill)
            df = df[~df.index.duplicated(keep='first')].resample('h').ffill(limit=4)
            
            df_11 = df[df.index.hour == 11][['Close']].copy()
            df_14 = df[df.index.hour == 14][['Close']].copy()
            df_11['Date'] = df_11.index.strftime('%d/%m/%Y')
            df_14['Date'] = df_14.index.strftime('%d/%m/%Y')
            
            merged = pd.merge(df_11, df_14, on='Date', how='outer', suffixes=('_11', '_14'))
            if merged.empty: continue
            
            merged['Time_11'], merged['Time_14'] = '11:00', '14:00'
            merged['Yield'] = (merged['Close_14'] / merged['Close_11']) - 1
            all_results[sym] = merged[['Date', 'Time_11', 'Close_11', 'Time_14', 'Close_14', 'Yield']]

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
        
        st.success("✅ הקובץ מוכן!")
        st.download_button("📥 הורד אקסל", buf.getvalue(), "Market_Report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    except Exception as e:
        st.error(f"שגיאה: {e}")
