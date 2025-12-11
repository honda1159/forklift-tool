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

# --- アプリ画面設定 ---
st.set_page_config(page_title="TCOシミュレーター", layout="wide")
st.title("🚜 フォークリフト 生涯コスト(TCO)シミュレーター")

# データ読み込み
df_log, df_parts, df_contract, df_risk = load_all_data()

# タブ構成
tab1, tab2 = st.tabs(["📊 契約プラン比較提案", "📝 車両管理・記録"])

# ==========================================
# タブ1：生涯コストシミュレーション (提案用)
# ==========================================
with tab1:
    st.markdown("### 5年間の維持費シミュレーション")
    
    col1, col2 = st.columns([1, 2])
    
    # --- 左カラム：条件設定 ---
    with col1:
        st.info("🛠 **比較条件の設定**")
        
        # 1. 契約プラン選択
        if not df_contract.empty:
            plan_names = df_contract["プラン名"].tolist()
            selected_plan = st.selectbox("提案プランを選択", plan_names, index=len(plan_names)-1)
            
            # プラン詳細取得
            plan_data = df_contract[df_contract["プラン名"] == selected_plan].iloc[0]
            monthly_cost = int(plan_data["月額費用"])
            
            st.write(f"**{selected_plan}**")
            st.write(f"月額: ¥{monthly_cost:,}")
            st.caption(f"内容: {plan_data['備考']}")
        else:
            st.error("マスターデータ(contract_master)がありません")
            monthly_cost = 0

        st.write("---")
        
        # 2. リスク事例の選択（恐怖訴求）
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
            selected_risk = "データなし"

    # --- 右カラム：グラフによる比較 ---
    with col2:
        if not df_parts.empty:
            # === 計算ロジック ===
            years = 5
            
            # A. 契約プランのコスト（5年総額）
            contract_total = monthly_cost * 12 * years
            
            # B. スポット整備のコスト（積み上げ計算）
            spot_maintenance_total = 0
            for _, part in df_parts.iterrows():
                # 5年間での交換回数 × (部品代+工賃)
                freq = float(part["交換頻度(年)"])
                count = int(years / freq)
                unit_price = int(part["単価"]) + int(part["工賃"])
                spot_maintenance_total += unit_price * count

            # === グラフ作成 (Stacked Bar) ===
            fig = go.Figure()

            # 1. 契約プラン（青色一本）
            fig.add_trace(go.Bar(
                name=f"【契約】{selected_plan}",
                x=["契約プラン"],
                y=[contract_total],
                text=[f"¥{contract_total:,}"],
                textposition='auto',
                marker_color='royalblue'
            ))

            # 2. スポット整備（ベース部分・グレー）
            fig.add_trace(go.Bar(
                name="スポット整備費用",
                x=["スポット対応"],
                y=[spot_maintenance_total],
                text=[f"¥{spot_maintenance_total:,}"],
                textposition='auto',
                marker_color='lightgray'
            ))

            # 3. リスクコスト（上に積み上げ・赤色）
            fig.add_trace(go.Bar(
                name=f"⚠️ 故障リスク ({selected_risk})",
                x=["スポット対応"],
                y=[risk_cost],
                text=[f"+¥{risk_cost:,}"],
                textposition='inside',
                marker_color='crimson'
            ))

            fig.update_layout(
                title="<b>5年間の総トータルコスト比較</b>",
                barmode='stack',
                yaxis_title="累計費用 (円)",
                height=500,
                showlegend=True,
                font=dict(size=14),
                # データ変更時のアニメーション設定
                transition={
                    'duration': 800, 
                    'easing': 'cubic-in-out'
                }
            )

            # keyを指定することで、同じグラフの更新としてアニメーションを有効にする
            st.plotly_chart(fig, use_container_width=True, key="tco_chart")

            # --- クロージングメッセージ ---
            diff = (spot_maintenance_total + risk_cost) - contract_total
            if diff > 0:
                st.success(f"🎉 **契約プランの方が、リスク発生時より ¥{diff:,} お得で安心です！**")
            else:
                st.info("コスト面ではスポットが安いですが、ダウンタイムの損失を含めてご検討ください。")

# ==========================================
# タブ2：管理機能 (既存のまま)
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

