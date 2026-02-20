import streamlit as st
import yfinance as yf
import pandas as pd
from io import BytesIO
import warnings

warnings.filterwarnings('ignore')

st.set_page_config(page_title="מחולל נתוני שוק", page_icon="📈")
st.title("📈 מחולל נתוני שוק אוטומטי")
st.markdown("מערכת להפקת קבצי אקסל של נתוני מסחר.")

TICKER_MAP = {
    'תא 35': 'TA35.TA', 'ת"א 35': 'TA35.TA', 'ta35': 'TA35.TA',
    'דולר שקל': 'ILS=X', 'דולר/שקל': 'ILS=X', 'דולר': 'ILS=X',
    'לאומי': 'LUMI.TA',
    'פועלים': 'POLI.TA',
    'בנקים': 'TELB.TA',
    'sp500': 'ES=F', 's&p': 'ES=F', 'sp 500': 'ES=F',
}

PERIOD_MAP = {
    'שנה': '1y', 'שנתיים': '2y',
    'חודש': '1mo', 'חודשיים': '3mo', 'שלושה חודשים': '3mo',
    'שבוע': '5d', 'יום': '1d',
}

instruction = "לדוגמה: תא 35, לאומי ודולר שקל לשנה אחרונה."
user_input = st.text_area("מה ברצונך לבדוק?", placeholder=instruction)

with st.expander("נכסים זמינים"):
    st.markdown("""
| שם | טיקר |
|---|---|
| ת"א 35 | TA35.TA |
| לאומי | LUMI.TA |
| פועלים | POLI.TA |
| בנקים | TELB.TA |
| דולר/שקל | ILS=X |
| S&P 500 | ES=F |
""")

if st.button("הפק אקסל"):
    if not user_input.strip():
        st.error("אנא הכנס בקשה.")
        st.stop()

    lower_input = user_input.lower()
    tickers = list({v for k, v in TICKER_MAP.items() if k in lower_input})
    period = next((v for k, v in PERIOD_MAP.items() if k in lower_input), '1y')

    if not tickers:
        st.warning("לא זוהו נכסים. נסה לכתוב: לאומי, תא 35, דולר שקל וכו'")
        st.stop()

    st.info(f"זוהו: {', '.join(tickers)} | תקופה: {period}")

    try:
        all_results = {}
        for sym in tickers:
            df = yf.download(sym, period=period, interval="1h", auto_adjust=False, progress=False)
            if df.empty:
                st.warning(f"לא נמצאו נתונים עבור {sym}")
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert('Asia/Jerusalem')
            else:
                df.index = df.index.tz_convert('Asia/Jerusalem')

            df = df[~df.index.duplicated(keep='first')].resample('h').ffill(limit=4)

            df_11 = df[df.index.hour == 11][['Close']].copy()
            df_14 = df[df.index.hour == 14][['Close']].copy()
            df_11['Date'] = df_11.index.strftime('%d/%m/%Y')
            df_14['Date'] = df_14.index.strftime('%d/%m/%Y')

            merged = pd.merge(df_11, df_14, on='Date', how='outer', suffixes=('_11', '_14'))
            if merged.empty:
                continue

            merged['Time_11'], merged['Time_14'] = '11:00', '14:00'
            merged['Yield'] = (merged['Close_14'] / merged['Close_11']) - 1
            all_results[sym] = merged[['Date', 'Time_11', 'Close_11', 'Time_14', 'Close_14', 'Yield']]

        if not all_results:
            st.warning("לא נמצאו נתונים תקינים.")
            st.stop()

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            col = 0
            for s, d in all_results.items():
                pd.Series([f"נכס: {s}"]).to_excel(writer, startrow=0, startcol=col, index=False, header=False)
                d.to_excel(writer, startrow=1, startcol=col, index=False)
                col += len(d.columns) + 1

        st.success("הקובץ מוכן!")
        st.download_button("הורד אקסל", buf.getvalue(), "Market_Report.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    except Exception as e:
        st.error(f"שגיאה: {e}")
```

---

**requirements.txt:**
```
streamlit
yfinance
pandas
openpyxl
