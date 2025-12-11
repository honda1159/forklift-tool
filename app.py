import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
from datetime import datetime
import json

# --- 設定 ---
SHEET_NAME = "forklift_db"

# --- 認証とデータ取得 ---
@st.cache_resource
def init_connection():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # 【変更点】Secretsから「JSONファイルの中身」を丸ごと取得して辞書に変換
    # 以前のような replace 処理は不要になります
    json_content = st.secrets["gcp_service_account"]["json_file"]
    creds_dict = json.loads(json_content)
    
    # 認証
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client

# データをキャッシュ (ttl=60秒)
@st.cache_data(ttl=60)
def get_data():
    client = init_connection()
    try:
        sheet = client.open(SHEET_NAME).sheet1
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"スプレッドシートが見つかりません: {e}")
        return pd.DataFrame()

def add_data(record):
    client = init_connection()
    sheet = client.open(SHEET_NAME).sheet1
    sheet.append_row(record)

# --- アプリ画面 ---
st.title("🚜 フォークリフト整備管理クラウド")

# サイドバー：データ入力
st.sidebar.header("新規登録")
with st.sidebar.form("entry_form"):
    v_id = st.text_input("車両ID (例: FL-01)")
    date = st.date_input("日付", datetime.now())
    cost = st.number_input("費用 (円)", min_value=0, step=1000)
    hours = st.number_input("アワーメーター (h)", min_value=0, step=1)
    category = st.selectbox("区分", ["定期点検", "修理", "タイヤ交換", "その他"])
    note = st.text_area("詳細メモ")
    
    submitted = st.form_submit_button("登録する")
    
    if submitted:
        if v_id and cost > 0:
            record = [v_id, str(date), cost, hours, category, note]
            add_data(record)
            st.success("保存しました！")
            st.cache_data.clear()
            st.rerun()
        else:
            st.sidebar.error("車両IDと費用は必須です。")

# メイン画面：分析
st.header("📊 整備コスト分析")

try:
    df = get_data()
    if not df.empty:
        df['日付'] = pd.to_datetime(df['日付'])
        
        vehicle_list = df['ID'].unique()
        selected_vehicle = st.selectbox("車両を選択して詳細を表示", ["全て"] + list(vehicle_list))
        
        if selected_vehicle != "全て":
            df_display = df[df['ID'] == selected_vehicle]
        else:
            df_display = df

        total_cost = df_display['費用'].sum()
        st.metric(label="合計整備費用", value=f"¥{total_cost:,}")

        fig = px.bar(df_display, x='日付', y='費用', color='区分', 
                     title='整備費用の推移', hover_data=['メモ'])
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(df_display.sort_values('日付', ascending=False))
    else:
        st.info("データがありません。サイドバーから登録してください。")
except Exception as e:
    st.warning("データを読み込めませんでした。スプレッドシートの設定を確認してください。")
