import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import numpy as np

# --- 1. 頁面基礎設定 ---
st.set_page_config(
    page_title="馬尼通訊戰情室",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. 安全登入機制 ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if not st.session_state.password_correct:
        st.markdown("### 🔒 請輸入戰情室密碼")
        with st.form("login_form"):
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("登入")
            
            if submitted:
                if password == st.secrets["passwords"]["main_password"]:
                    st.session_state.password_correct = True
                    st.rerun()
                else:
                    st.error("密碼錯誤")
        return False
    return True

if not check_password():
    st.stop()

# --- 3. 側邊欄：選擇分店與人員 ---
with st.sidebar:
    st.header("🏢 請選擇分店")
    
    # 分店清單
    branch_options = [
        "ALL", "東門店", "小西門店", "文賢店", 
        "歸仁店", "永康店", "安中店", "鹽行店", "五甲店"
    ]
    selected_branch = st.selectbox("切換戰情看板", branch_options)

    # 讀取網址
    try:
        target_url = st.secrets["branch_urls"][selected_branch]
    except KeyError:
        st.error(f"❌ 尚未設定「{selected_branch}」的試算表網址！")
        st.stop()

    # --- 人員選擇邏輯 (v2.3 下拉選單穩定版) ---
    target_person = "全店總表" # 預設值
    
    if selected_branch != "ALL":
        st.markdown("---")
        st.header("👤 選擇檢視對象")
        
        # 1. 從 secrets 讀取該店的人員名單
        staff_list = []
        if "branch_staff" in st.secrets:
             staff_list = st.secrets["branch_staff"].get(selected_branch, [])
        
        # 2. 判斷顯示模式
        if staff_list:
            # 如果有設定名單 -> 顯示下拉選單
            options = ["全店總表"] + staff_list
            target_person = st.selectbox("請選擇人員", options)
        else:
            # 如果沒設定名單 -> 顯示文字輸入框 (備用方案)
            person_mode = st.radio("顯示模式", ["全店總表", "指定人員 (手動輸入)"])
            
            if person_mode == "指定人員 (手動輸入)":
                target_person = st.text_input("請輸入人員分頁名稱", placeholder="例如: 914")
                if not target_person:
                    st.warning("請輸入名稱")
                    st.stop()
            else:
                target_person = selected_branch # 全店總表

    else:
        # ALL 模式
        target_person = "ALL"

    st.info(f"正在讀取：{selected_branch} > {target_person}")
    
    if st.button("🔄 強制重新讀取資料"):
        st.cache_data.clear()
        st.rerun()

# --- 4. 讀取資料 ---
@st.cache_data(ttl=600)
def load_data(url, worksheet):
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_raw = conn.read(spreadsheet=url, worksheet=worksheet, header=None)
    
    # A. 抓取 年份(A2) 和 月份(B2)
    try:
        year_val = pd.to_numeric(df_raw.iloc[1, 0], errors='coerce')
        month_val = pd.to_numeric(df_raw.iloc[1, 1], errors='coerce')
        
        if pd.isna(year_val) or pd.isna(month_val):
            year_val = pd.Timestamp.now().year
            month_val = pd.Timestamp.now().month
    except:
        year_val = 2026
        month_val = 1 

    # B. 抓取 標題列(第3列)
    headers = df_raw.iloc[2].astype(str).str.strip()
    
    # C. 抓取 數據區(第15列開始)
    df = df_raw.iloc[14:].copy()
    df.columns = headers
    
    # D. 資料清潔
    valid_columns = []
    for col in df.columns:
        if col.lower() != 'nan' and not col.startswith('Unnamed') and col.strip() != "":
            valid_columns.append(col)
    df = df[valid_columns]
    df = df.loc[:, ~df.columns.duplicated()]
    
    # E. 合體日期
    if not df.empty:
        first_col_name = df.columns[0]
        df = df[pd.to_numeric(df[first_col_name], errors='coerce').notna()]
        
        df['year_temp'] = int(year_val)
        df['month_temp'] = int(month_val)
        df['day_temp'] = df[first_col_name].astype(int)
        
        df['日期'] = pd.to_datetime(df[['year_temp', 'month_temp', 'day_temp']].rename(columns={'year_temp':'year', 'month_temp':'month', 'day_temp':'day'}), errors='coerce')
        
        df = df.drop(columns=['year_temp', 'month_temp', 'day_temp'])
    
    # F. 全自動數字轉換
    for col in df.columns:
        if col != '日期':
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    return df

try:
    # 決定要讀取的分頁名稱
    worksheet_to_load = target_person
    
    # 特例處理：如果選的是「全店總表」，實際上要去讀的分頁名稱就是「分店名」(例如：東門店)
    # 除非是 ALL 模式，分頁才叫 ALL
    if target_person == "全店總表":
        worksheet_to_load = selected_branch 
    if target_person == "ALL":
        worksheet_to_load = "ALL" # 假設全店總表的分頁名叫 ALL，請依實際修改

    df_view = load_data(target_url, worksheet_to_load)
    
except Exception as e:
    st.error(f"❌ 讀取失敗！")
    st.markdown(f"**可能原因：**\n1. 網址錯誤\n2. 找不到分頁名稱「{worksheet_to_load}」\n3. secrets.toml 名單設定有誤")
    st.error(f"系統訊息: {e}")
    st.stop()

# --- 5. 顯示戰情儀表板 ---

display_title = f"{selected_branch} - {target_person}"
st.title(f"📊 {display_title} 戰情室")
st.caption(f"v2.3 穩定版 | 資料來源: {selected_branch} > {worksheet_to_load}")

if df_view.empty:
    st.warning("⚠️ 讀取後無資料，請檢查檔案內容。")
    st.stop()

# =========================================================
#  [第一層] 營運戰情看板
# =========================================================

def get_sum(col_name):
    return df_view.get(col_name, pd.Series([0])).sum()

# --- A. 💰 財務金額區 ---
st.markdown("### 💰 營收與獲利")
col_m1, col_m2, col_m3 = st.columns(3)
with col_m1: st.metric("總毛利", f"${get_sum('毛利'):,.0f}")
with col_m2: st.metric("配件營收", f"${get_sum('配件營收'):,.0f}")
with col_m3: st.metric("保險營收", f"${get_sum('保險營收'):,.0f}")

# --- B. 🔢 關鍵計數指標 ---
st.markdown("### 📈 關鍵營運指標")
col_c1, col_c2, col_c3, col_c4 = st.columns(4)
with col_c1: st.metric("門號申辦數", f"{get_sum('門號'):,.0f}")
with col_c2: st.metric("總來客數", f"{get_sum('來客數'):,.0f}")
with col_c3: st.metric("Google 評論", f"{get_sum('GOOGLE 評論'):,.0f}")
with col_c4: st.metric("生活圈加入", f"{get_sum('生活圈'):,.0f}")

# --- C. 📦 手機與硬體庫存 ---
st.markdown("### 📱 手機與硬體銷售/庫存")
col_i1, col_i2, col_i3, col_i4 = st.columns(4)
with col_i1: st.metric("庫存手機", f"{get_sum('庫存手機'):,.0f}")
with col_i2: st.metric("VIVO 手機", f"{get_sum('VIVO手機'):,.0f}")
with col_i3: st.metric("蘋果手機", f"{get_sum('蘋果手機'):,.0f}")
with col_i4: st.metric("蘋果平板+手錶", f"{get_sum('蘋果平板+手錶'):,.0f}")

# --- D. 🔵 遠傳指標 ---
st.markdown("### 🔵 遠傳指標")
col_f1, col_f2, col_f3, col_f4 = st.columns(4)
with col_f1: st.metric("續約累積 GAP", f"{get_sum('遠傳續約累積GAP'):,.0f}")
with col_f2: st.metric("升續率", f"{get_sum('遠傳升續率'):.1f}") 
with col_f3: st.metric("平續率", f"{get_sum('遠傳平續率'):.1f}")
with col_f4: st.metric("綜合指標", f"{get_sum('綜合指標'):.1f}")

st.markdown("---")

# [第二層] 圖表區
c1, c2 = st.columns([2, 1])

with c1:
    st.subheader("📈 日毛利趨勢")
    if '日期' in df_view.columns and '毛利' in df_view.columns:
        daily_data = df_view.groupby('日期')['毛利'].sum().reset_index()
        daily_data = daily_data.sort_values('日期')
        
        fig_line = px.line(daily_data, x='日期', y='毛利', markers=True)
        fig_line.update_xaxes(tickformat="%m/%d") 
        fig_line.update_layout(height=350)
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.warning("無法畫圖：缺少必要欄位")

with c2:
    st.subheader("📊 營收結構 (金額)")
    metrics = {
        '毛利': get_sum('毛利'),
        '配件營收': get_sum('配件營收'),
        '保險營收': get_sum('保險營收')
    }
    metrics = {k: v for k, v in metrics.items() if v > 0}
    
    if metrics:
        df_pie = pd.DataFrame(list(metrics.items()), columns=['類別', '金額'])
        fig_pie = px.pie(df_pie, values='金額', names='類別', hole=0.4)
        fig_pie.update_layout(height=350, showlegend=True)
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("無數據可顯示")

# [第三層] 詳細資料表 (v2.5 顯示優化版)
with st.expander(f"查看 {display_title} 詳細資料 (自動同步新增欄位)"):
    df_display = df_view.copy()
    
    # 1. 格式化日期 (確保顯示為 YYYY-MM-DD)
    if '日期' in df_display.columns:
        df_display['日期'] = df_display['日期'].dt.strftime('%Y-%m-%d')
    
    # 2. 欄位大風吹：把「日期」搬到第一欄，並移除原本的「日(業績項目)」
    # 邏輯：找出第一欄的名稱 (通常是 '業績項目' 或 '日期')
    first_col_name = df_display.columns[0]
    
    # 如果系統生成的完整 '日期' 存在
    if '日期' in df_display.columns:
        # 建立新的欄位順序：日期排第一，接著是其他欄位 (扣除掉原本的第1欄 '業績項目' 避免重複)
        # 注意：我們把 first_col_name (即 '業績項目') 排除掉，因為它只顯示 1, 2，資訊太少
        cols = ['日期'] + [c for c in df_display.columns if c != '日期' and c != first_col_name]
        df_display = df_display[cols]
    
    # 3. 解構與重建 (維持穩定性)
    data_as_dicts = df_display.to_dict(orient='records')
    df_clean = pd.DataFrame(data_as_dicts)
    
    # 4. 欄位顯示設定
    column_config_settings = {}
    
    # 設定日期欄位的標題名稱
    column_config_settings["日期"] = st.column_config.TextColumn(
        "📅 日期",  # 這裡可以改標題顯示名稱
        help="交易日期"
    )

    for col in df_clean.columns:
        if pd.api.types.is_numeric_dtype(df_clean[col]):
             column_config_settings[col] = st.column_config.NumberColumn(format="%.0f")

    # 5. 顯示表格 (關鍵：hide_index=True)
    st.dataframe(
        df_clean,
        column_config=column_config_settings,
        use_container_width=True,
        hide_index=True  # 👈 這一行就是讓 (指數) 0, 1, 2 消失的魔法！
    )

# --- 6. 頁尾版權 ---
st.markdown("---")
with st.container():
    st.caption("© 2026 馬尼通訊管理部 | v2.3 Stable Config Mode")
