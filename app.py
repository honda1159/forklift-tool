import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.graph_objects as go
import json

# --- 設定 ---
SHEET_NAME = "forklift_db"

# --- 認証とデータ取得 ---
@st.cache_resource
def init_connection():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    json_content = st.secrets["gcp_service_account"]["json_file"]
    creds_dict = json.loads(json_content)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client

@st.cache_data(ttl=60)
def load_all_data():
    client = init_connection()
    spreadsheet = client.open(SHEET_NAME)
    
    def get_df(sheet_name):
        try:
            return pd.DataFrame(spreadsheet.worksheet(sheet_name).get_all_records())
        except:
            return pd.DataFrame()

    return get_df("sheet1"), get_df("parts_master"), get_df("contract_master"), get_df("risk_cases")

def add_log_data(record):
    client = init_connection()
    sheet = client.open(SHEET_NAME).worksheet("sheet1")
    sheet.append_row(record)

def upload_excel_data(df_upload):
    """Excelデータをまとめてスプレッドシートに追加"""
    client = init_connection()
    sheet = client.open(SHEET_NAME).worksheet("sheet1")
    
    # データフレームをリストのリストに変換
    data_to_upload = df_upload.astype(str).values.tolist()
    sheet.append_rows(data_to_upload)

# --- ページ設定 ---
st.set_page_config(page_title="TCOシミュレーター", layout="wide")

# ==========================================
# 🔐 ログイン機能 (簡易版)
# ==========================================
# セッションステートでログイン状態を管理
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

def login():
    st.title("🔐 ログイン")
    password = st.text_input("パスワードを入力してください", type="password")
    
    # Secretsに設定したパスワードと照合（設定がない場合は 'admin' で入れます）
    try:
        correct_password = st.secrets["general"]["password"]
    except:
        correct_password = "admin" # デフォルトパスワード

    if st.button("ログイン"):
        if password == correct_password:
            st.session_state['logged_in'] = True
            st.rerun()
        else:
            st.error("パスワードが違います")

# ログインしていない場合はログイン画面のみ表示して終了
if not st.session_state['logged_in']:
    login()
    st.stop()

# ==========================================
# 🚜 メインアプリ (ログイン後のみ表示)
# ==========================================
st.title("🚜 フォークリフト 生涯コスト(TCO)シミュレーター")

# データ読み込み
df_log, df_parts, df_contract, df_risk = load_all_data()

# タブ構成
tab1, tab2, tab3 = st.tabs(["📊 契約プラン比較提案", "📝 車両管理・記録", "📥 Excel一括登録"])

# ==========================================
# タブ1：生涯コストシミュレーション (提案用)
# ==========================================
with tab1:
    st.markdown("### 5年間の維持費シミュレーション")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.info("🛠 **比較条件の設定**")
        if not df_contract.empty:
            plan_names = df_contract["プラン名"].tolist()
            selected_plan = st.selectbox("提案プランを選択", plan_names, index=len(plan_names)-1)
            plan_data = df_contract[df_contract["プラン名"] == selected_plan].iloc[0]
            monthly_cost = int(plan_data["月額費用"])
            st.write(f"**{selected_plan}**")
            st.write(f"月額: ¥{monthly_cost:,}")
            st.caption(f"内容: {plan_data['備考']}")
        else:
            st.error("マスターデータがありません")
            monthly_cost = 0

        st.write("---")
        st.warning("⚠️ **想定する故障リスク**")
        if not df_risk.empty:
            risk_names = df_risk["故障事例"].tolist()
            selected_risk = st.selectbox("発生しうる故障", risk_names)
            risk_data = df_risk[df_risk["故障事例"] == selected_risk].iloc[0]
            risk_cost = int(risk_data["想定修理費"])
            risk_desc = risk_data["ダウンタイム損失解説"]
            st.markdown(f"""
            <div style="background-color:#ffebeb; padding:10px; border-radius:5px; border:1px solid red;">
                <span style="color:red; font-weight:bold;">¥{risk_cost:,} の突発出費</span><br>
                <small>{risk_desc}</small>
            </div>
            """, unsafe_allow_html=True)
        else:
            risk_cost = 0

    with col2:
        if not df_parts.empty:
            years = 5
            contract_total = monthly_cost * 12 * years
            spot_maintenance_total = 0
            for _, part in df_parts.iterrows():
                freq = float(part["交換頻度(年)"])
                count = int(years / freq)
                unit_price = int(part["単価"]) + int(part["工賃"])
                spot_maintenance_total += unit_price * count

            fig = go.Figure()
            fig.add_trace(go.Bar(name=f"【契約】{selected_plan}", x=["契約プラン"], y=[contract_total], text=[f"¥{contract_total:,}"], textposition='auto', marker_color='royalblue'))
            fig.add_trace(go.Bar(name="スポット整備費用", x=["スポット対応"], y=[spot_maintenance_total], text=[f"¥{spot_maintenance_total:,}"], textposition='auto', marker_color='lightgray'))
            fig.add_trace(go.Bar(name=f"⚠️ 故障リスク", x=["スポット対応"], y=[risk_cost], text=[f"+¥{risk_cost:,}"], textposition='inside', marker_color='crimson'))

            fig.update_layout(
                title="<b>5年間の総トータルコスト比較</b>", barmode='stack', yaxis_title="累計費用 (円)", height=500, showlegend=True,
                transition={'duration': 800, 'easing': 'cubic-in-out'}
            )
            st.plotly_chart(fig, use_container_width=True, key="tco_chart")

# ==========================================
# タブ2：管理機能
# ==========================================
with tab2:
    st.subheader("整備履歴の登録")
    with st.form("entry_form"):
        col_a, col_b = st.columns(2)
        with col_a:
            v_id = st.text_input("車両ID (例: FL-01)")
            date = st.date_input("日付")
            cost = st.number_input("費用 (円)", min_value=0, step=1000)
        with col_b:
            hours = st.number_input("アワーメーター (h)", min_value=0, step=1)
            category = st.selectbox("区分", ["定期点検", "修理", "タイヤ交換", "その他"])
            note = st.text_area("詳細メモ")
        if st.form_submit_button("登録"):
            if v_id and cost >= 0:
                add_log_data([v_id, str(date), cost, hours, category, note])
                st.success("登録しました")
                st.cache_data.clear()

    if not df_log.empty:
        st.dataframe(df_log, use_container_width=True)

# ==========================================
# タブ3：Excel一括登録 (NEW!)
# ==========================================
with tab3:
    st.header("📥 データの一括インポート")
    st.info("Excelファイルをアップロードして、過去の整備記録を一括で登録できます。")
    
    # テンプレートのフォーマット提示
    st.markdown("""
    **Excelファイルの形式 (列の並び順が重要です)**
    | A列: ID | B列: 日付 | C列: 費用 | D列: 時間(h) | E列: 区分 | F列: メモ |
    |---|---|---|---|---|---|
    | FL-01 | 2024-01-01 | 15000 | 1200 | 定期点検 | オイル交換 |
    """)

    uploaded_file = st.file_uploader("Excelファイルをドラッグ＆ドロップ", type=["xlsx"])
    
    if uploaded_file:
        try:
            # Excel読み込み
            df_upload = pd.read_excel(uploaded_file)
            
            # 簡易チェック（列数が合っているか）
            if len(df_upload.columns) < 6:
                st.error("列が足りません。A〜F列までデータがあるか確認してください。")
            else:
                # プレビュー表示
                st.write("▼ 読み込みプレビュー (最初の5件)")
                st.dataframe(df_upload.head())
                
                # 指定した列だけ抽出してリネーム（安全策）
                # ユーザーのExcelの1行目がヘッダーである前提
                df_clean = df_upload.iloc[:, :6] # 最初の6列だけ使う
                df_clean.columns = ["vehicle_id", "date", "cost", "hours", "category", "note"]
                
                # 日付の文字列化などクリーニング
                df_clean['date'] = df_clean['date'].astype(str)
                df_clean['cost'] = df_clean['cost'].fillna(0).astype(int)
                df_clean['hours'] = df_clean['hours'].fillna(0).astype(int)
                df_clean['category'] = df_clean['category'].fillna("その他")
                df_clean['note'] = df_clean['note'].fillna("")

                if st.button("このデータをデータベースに追加登録する"):
                    with st.spinner("スプレッドシートに書き込み中..."):
                        upload_excel_data(df_clean)
                        st.success(f"{len(df_clean)}件のデータを登録しました！")
                        st.cache_data.clear() # キャッシュクリア
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
