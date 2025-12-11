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
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    json_content = st.secrets["gcp_service_account"]["json_file"]
    creds_dict = json.loads(json_content)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client

# 複数のシートをまとめて読み込む関数
@st.cache_data(ttl=60)
def load_all_data():
    client = init_connection()
    try:
        spreadsheet = client.open(SHEET_NAME)
        
        # 各シートを取得（なければ空DF）
        try:
            log_sheet = spreadsheet.worksheet("sheet1") # 既存のログ
            df_log = pd.DataFrame(log_sheet.get_all_records())
        except: df_log = pd.DataFrame()

        try:
            parts_sheet = spreadsheet.worksheet("parts_master")
            df_parts = pd.DataFrame(parts_sheet.get_all_records())
        except: df_parts = pd.DataFrame()

        try:
            contract_sheet = spreadsheet.worksheet("contract_master")
            df_contract = pd.DataFrame(contract_sheet.get_all_records())
        except: df_contract = pd.DataFrame()

        try:
            risk_sheet = spreadsheet.worksheet("risk_cases")
            df_risk = pd.DataFrame(risk_sheet.get_all_records())
        except: df_risk = pd.DataFrame()

        return df_log, df_parts, df_contract, df_risk

    except Exception as e:
        st.error(f"スプレッドシートの読み込みエラー: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def add_log_data(record):
    client = init_connection()
    sheet = client.open(SHEET_NAME).worksheet("sheet1")
    sheet.append_row(record)

# --- アプリ画面構成 ---
st.set_page_config(page_title="フォークリフト管理・提案ツール", layout="wide")
st.title("🚜 フォークリフト管理 & 契約提案システム")

# データ読み込み
df_log, df_parts, df_contract, df_risk = load_all_data()

# タブで機能を分ける
tab1, tab2 = st.tabs(["📊 5年コストシミュレーション (提案用)", "📝 整備記録・履歴 (管理用)"])

# ==========================================
# タブ1：提案・シミュレーション機能
# ==========================================
with tab1:
    st.header("契約更新時のコスト比較シミュレーション")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("🛠 シミュレーション条件")
        # マスターデータが読み込めているか確認
        if df_parts.empty or df_contract.empty:
            st.warning("スプレッドシートに 'parts_master' または 'contract_master' シートを作成してください。")
        else:
            # 契約プラン選択
            plan_names = df_contract["プラン名"].tolist()
            selected_plan_name = st.selectbox("提案する契約プラン", plan_names)
            
            # 選択されたプランの情報を取得
            plan_info = df_contract[df_contract["プラン名"] == selected_plan_name].iloc[0]
            monthly_cost = int(plan_info["月額費用"])
            yearly_contract_cost = monthly_cost * 12
            
            st.info(f"**{selected_plan_name}**\n\n月額: ¥{monthly_cost:,} (年額: ¥{yearly_contract_cost:,})\n\n備考: {plan_info['備考']}")

            st.write("---")
            st.write("▼ スポット修理の想定稼働")
            # 簡易的な稼働条件（本来はここも詳細設定可能にできる）
            st.caption("※以下の部品交換頻度に基づいて算出します")
            st.dataframe(df_parts[["部品名", "交換目安(年)"]], height=150)

    with col2:
        if not df_parts.empty and not df_contract.empty:
            # --- コスト計算ロジック ---
            years = [1, 2, 3, 4, 5]
            
            # A: 契約プランの累積コスト
            contract_costs = [yearly_contract_cost * y for y in years]
            
            # B: スポット修理の累積コスト（積み上げ計算）
            spot_costs = []
            cumulative_spot = 0
            
            # 各年のコストを計算
            for y in years:
                year_cost = 0
                for index, part in df_parts.iterrows():
                    freq = float(part["交換目安(年)"])
                    # その年に交換時期が来るか？ (簡易計算: 年数 ÷ 頻度が整数の時)
                    # 実際は0.5年などは「毎年」扱いにするなどのロジック調整
                    if freq > 0 and (y % freq == 0 or (freq < 1 and y >= 1)):
                        # 0.5年ごとのものは毎年2回分加算する等の補正
                        count = 1 if freq >= 1 else int(1/freq)
                        cost_unit = int(part["部品代"]) + int(part["工賃"])
                        year_cost += cost_unit * count
                
                cumulative_spot += year_cost
                spot_costs.append(cumulative_spot)

            # --- グラフ描画 (Plotly) ---
            fig = go.Figure()

            # 1. 契約プラン（安心・定額）
            fig.add_trace(go.Bar(
                x=[f"{y}年目" for y in years],
                y=contract_costs,
                name=f"契約プラン ({selected_plan_name})",
                marker_color='blue',
                opacity=0.7
            ))

            # 2. スポット修理（基本コスト）
            fig.add_trace(go.Bar(
                x=[f"{y}年目" for y in years],
                y=spot_costs,
                name="スポット修理 (基本維持費)",
                marker_color='gray'
            ))

            # 3. リスク（高額故障）の上乗せ表示
            # 5年目に「もし故障したら」というリスクを積み上げで表示
            if not df_risk.empty:
                max_risk_cost = df_risk["想定修理費"].max() # 一番高い故障事例
                risk_name = df_risk.loc[df_risk["想定修理費"].idxmax(), "故障事例"]
                
                # 5年目のデータだけにリスクを乗せる
                risk_data = [0, 0, 0, 0, max_risk_cost]
                
                fig.add_trace(go.Bar(
                    x=[f"{y}年目" for y in years],
                    y=risk_data,
                    name=f"⚠️ 故障リスク例: {risk_name}",
                    marker_color='red',
                    base=spot_costs # スポットコストの上に積み上げる
                ))

            fig.update_layout(
                title="5年間のトータルコスト比較シミュレーション",
                barmode='group', # 並列表示（リスク部分は積み上げられないためgroup推奨だが、視覚効果を狙う）
                yaxis_title="累積費用 (円)",
                xaxis_title="経過年数",
                height=500
            )
            
            # グラフモード切り替え（並列か、比較か）
            # ここではシンプルに契約vsスポット+リスクを見せる
            st.plotly_chart(fig, use_container_width=True)

            # --- リスクの具体例提示（不安を煽るセクション） ---
            st.error("⚠️ **契約なし（スポット）の場合の潜在リスク**")
            st.write("定期的なメンテナンス契約がない場合、予兆検知が遅れ、以下のような高額修理が突然発生するリスクがあります。")
            
            if not df_risk.empty:
                risk_cols = st.columns(len(df_risk))
                for i, row in df_risk.iterrows():
                    with risk_cols[i % 3]: # 3列で折り返し
                        st.markdown(f"""
                        <div style="border:1px solid #ffcccc; padding:10px; border-radius:5px; background-color:#fff5f5;">
                            <h4 style="color:red; margin:0;">🚨 {row['故障事例']}</h4>
                            <p style="font-size:20px; font-weight:bold;">想定: ¥{int(row['想定修理費']):,}</p>
                            <p style="font-size:12px; color:#555;">{row['内容']}</p>
                        </div>
                        """, unsafe_allow_html=True)
            
            st.caption("※グラフの赤色は、5年目に上記の最大故障リスクが1度発生した場合のシミュレーションです。")

# ==========================================
# タブ2：既存の整備記録機能
# ==========================================
with tab2:
    st.header("整備記録の入力・閲覧")
    
    # --- サイドバーの内容をここに移設または整理 ---
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
        
        submitted = st.form_submit_button("登録する")
        
        if submitted:
            if v_id and cost >= 0:
                record = [v_id, str(date), cost, hours, category, note]
                add_log_data(record)
                st.success("保存しました！")
                st.cache_data.clear()
            else:
                st.error("車両IDを入力してください")

    # 履歴表示
    if not df_log.empty:
        df_log['日付'] = pd.to_datetime(df_log['日付'])
        st.dataframe(df_log.sort_values('日付', ascending=False), use_container_width=True)
    else:
        st.info("データがまだありません")
