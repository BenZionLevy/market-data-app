import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
from io import BytesIO
import warnings

# השתקת אזהרות
warnings.filterwarnings('ignore')

# הגדרות עמוד (חובה להיות הפקודה הראשונה)
st.set_page_config(page_title="מחולל נתוני שוק", page_icon="📈", layout="centered")

# עיצוב מותאם אישית (RTL, פונטים, עיצוב כפתורים)
st.markdown("""
<style>
    /* כיווניות לימין עבור עברית */
    .block-container {
        direction: rtl;
        text-align: right;
    }
    /* עיצוב כפתור ההורדה לירוק ובולט */
    [data-testid="stDownloadButton"] button {
        background-color: #17B169;
        color: white;
        border-radius: 8px;
        font-weight: bold;
        width: 100%;
        margin-top: 15px;
        border: none;
    }
    [data-testid="stDownloadButton"] button:hover {
        background-color: #128C53;
        color: white;
    }
    /* עיצוב כפתור ההפקה הרגיל */
    .stButton > button {
        border-radius: 8px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

st.title("📈 מחולל נתוני שוק אוטומטי")
st.markdown("ברוכים הבאים למערכת החכמה להפקת נתוני מסחר. המערכת מבינה שפה חופשית ותכין עבורכם קובץ אקסל מסודר (ברזולוציה יומית או שעתית).")
st.divider()

# סרגל צד 
with st.sidebar:
    st.header("⚙️ הגדרות מערכת")
    api_key = st.text_input("הכנס מפתח Gemini API:", type="password", help="המערכת צריכה מפתח כדי להבין את השפה החופשית שלך.")
    st.caption("[לחץ כאן להוצאת מפתח חינמי מגוגל](https://aistudio.google.com/app/apikey)")
    st.divider()
    st.markdown("💡 **טיפ:** אם מופיעה שגיאה או שהאתר עמוס, פשוט המתן כדקה ונסה שוב.")

# אזור הקלט
st.subheader("מה ברצונך לבדוק?")
instruction = "לדוגמה: תא 35 ודולר לשנה אחרונה ברזולוציה יומית / פועלים ולאומי לחודש אחרון בין 10:00 ל-16:00."
user_input = st.text_area("הקלד את בקשתך כאן:", placeholder=instruction, height=100)

if st.button("🚀 נתח והפק אקסל", use_container_width=True):
    if not api_key:
        st.error("🔒 אנא הכנס מפתח API בסרגל הצד (משמאל) כדי להתחיל.")
        st.stop()
    
    if not user_input.strip():
        st.warning("✍️ אנא הכנס בקשה בתיבת הטקסט.")
        st.stop()
        
    try:
        # ספינר טעינה יפה בזמן שהמערכת חושבת (במקום השורה הכחולה המוזרה)
        with st.spinner("🤖 מנתח את הבקשה, מתחבר לבורסה ומכין את הנתונים... אנא המתן ⏳"):
            
            # הגדרת Gemini - שימוש במודל 2.5 העדכני
            genai.configure(api_key=api_key, transport='rest')
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # פרומפט חכם
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
            
            # קבלת תשובה
            response = model.generate_content(prompt)
            
            # פענוח ה-JSON
            clean_text = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(clean_text)
            
            tickers = data.get("tickers", [])
            period = data.get("period", "1y")
            interval = data.get("interval", "1d")
            start_hour = data.get("start_hour", 11)
            end_hour = data.get("end_hour", 14)

            if not tickers:
                st.error("❌ לא הצלחתי לזהות נכסים בבקשה שלך. נסה לנסח אחרת.")
                st.stop()

            all_results = {}
            for sym in tickers:
                # הורדת נתונים
                df = yf.download(sym, period=period, interval=interval, auto_adjust=False, progress=False)
                if df.empty: continue
                
                # עיבוד וסידור נתונים
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
                    df = df[~df.index.duplicated(keep='first')]
                    df_daily = df[['Open', 'Close']].copy()
                    df_daily['Date'] = df_daily.index.strftime('%d/%m/%Y')
                    df_daily['Yield'] = (df_daily['Close'] / df_daily['Open']) - 1
                    all_results[sym] = df_daily[['Date', 'Open', 'Close', 'Yield']]

            if not all_results:
                st.warning("⚠️ לא נמצאו נתונים תקינים בבורסה עבור הבקשה שלך.")
                st.stop()

            # יצירת קובץ האקסל הוירטואלי
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                col = 0
                for s, d in all_results.items():
                    pd.Series([f"נכס: {s}"]).to_excel(writer, startrow=0, startcol=col, index=False, header=False)
                    d.to_excel(writer, startrow=1, startcol=col, index=False)
                    col += len(d.columns) + 1
        
        # --- הודעות סיום מוצלחות וידידותיות ---
        st.success(f"✅ סיימתי! משכתי בהצלחה נתונים עבור {len(all_results)} נכסים.")
        
        if interval == "1h":
            st.info(f"📊 הקובץ כולל השוואה בין השעה {start_hour}:00 לשעה {end_hour}:00.")
        else:
            st.info("📊 הקובץ כולל נתונים ברזולוציה יומית (מחיר פתיחה מול סגירה).")

        # כפתור הורדה מוגדל (מקבל את העיצוב מה-CSS למעלה)
        st.download_button(
            label="📥 הורד את קובץ האקסל שלך עכשיו", 
            data=buf.getvalue(), 
            file_name="Market_Report.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    except Exception as e:
        st.error(f"❌ אירעה שגיאה. ייתכן שיש עומס על השרת, המתן חצי דקה ונסה שוב. (פירוט: {e})")
