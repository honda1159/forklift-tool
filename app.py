import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
from datetime import datetime

# --- 設定 ---
SHEET_NAME = "forklift_db"

# --- 認証とデータ取得 ---
@st.cache_resource
def init_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # Secretsから辞書として読み込む
    creds_dict = dict(st.secrets["gcp_service_account"])
    
    # 【重要】private_keyの改行コード文字化けを修正
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

# データをキャッシュして高速化（ttl=60秒で自動更新）
@st.cache_data(ttl=60)
def get_data():
    client = init_connection()
    try:
        sheet = client.open(SHEET_NAME).sheet1
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"スプレッドシートの読み込みに失敗しました: {e}")
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
            # キャッシュをクリアして最新データを即座に反映させる
            st.cache_data.clear()
            st.rerun() # 画面をリロード
        else:
            st.sidebar.error("車両IDと費用は必須です。")

# メイン画面：分析
st.header("📊 整備コスト分析")

df = get_data()

if not df.empty:
    # データ型変換
    df['日付'] = pd.to_datetime(df['日付'])
    
    # 車両選択フィルタ
    vehicle_list = df['ID'].unique()
    selected_vehicle = st.selectbox("車両を選択して詳細を表示", ["全て"] + list(vehicle_list))
    
    if selected_vehicle != "全て":
        df_display = df[df['ID'] == selected_vehicle]
    else:
        df_display = df

    # 合計金額
    total_cost = df_display['費用'].sum()
    st.metric(label="合計整備費用", value=f"¥{total_cost:,}")

    # グラフ
    fig = px.bar(df_display, x='日付', y='費用', color='区分', 
                 title='整備費用の推移', hover_data=['メモ'])
    st.plotly_chart(fig, use_container_width=True)

    # テーブル
    st.dataframe(df_display.sort_values('日付', ascending=False))
else:
    st.info("データがありません。サイドバーから登録してください。")

