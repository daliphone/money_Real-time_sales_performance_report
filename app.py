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
                # 請確認 secrets.toml 裡有設定 main_password
                if password == st.secrets["passwords"]["main_password"]:
                    st.session_state.password_correct = True
                    st.rerun()
                else:
                    st.error("密碼錯誤")
        return False
    return True

if not check_password():
    st.stop()

# --- 3. 側邊欄：選擇分店 ---
with st.sidebar:
    st.header("🏢 請選擇分店")
    
    branch_options = [
        "ALL", "東門店", "小西門店", "文賢店", 
        "歸仁店", "永康店", "安中店", "鹽行店", "五甲店"
    ]
    
    selected_branch = st.selectbox("切換戰情看板", branch_options)
    st.info(f"正在讀取：{selected_branch} 分頁...")
    
    if st.button("🔄 強制重新讀取資料"):
        st.cache_data.clear()
        st.rerun()

# --- 4. 讀取資料 (v2.1 自動化升級) ---
@st.cache_data(ttl=600)
def load_data(worksheet_name):
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    # 讀取整張表
    df_raw = conn.read(worksheet=worksheet_name, header=None)
    
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
    
    # F. 全自動數字轉換 (v2.1 關鍵修改)
    # 以前是指定 numeric_cols，現在我們遍歷「所有」欄位
    # 只要不是 '日期'，就試著把它轉成數字。這樣未來您新增欄位，這裡會自動抓到。
    for col in df.columns:
        if col != '日期':
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    return df

try:
    df_view = load_data(selected_branch)
except Exception as e:
    st.error(f"❌ 讀取失敗！請確認試算表狀態。")
    st.error(f"錯誤訊息: {e}")
    st.stop()

# --- 5. 顯示戰情儀表板 ---

st.title(f"📊 {selected_branch} - 營運戰情室")
st.caption(f"v2.1 | 資料來源: A2年份/B2月份 + A15日期 | 更新時間: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")

if df_view.empty:
    st.warning("⚠️ 讀取後無資料，請檢查 A2/B2 是否有年份月份，以及 A15 開始是否有填寫日期。")
    st.stop()

# =========================================================
#  [第一層] 營運戰情看板
# =========================================================

# 計算總和函數
def get_sum(col_name):
    # 使用 .get() 確保即使欄位不存在也不會報錯 (會回傳 0)
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

# --- D. 🔵 遠傳指標 (v2.1 新增) ---
st.markdown("### 🔵 遠傳指標")
col_f1, col_f2, col_f3, col_f4 = st.columns(4)

with col_f1:
    st.metric("續約累積 GAP", f"{get_sum('遠傳續約累積GAP'):,.0f}")
with col_f2:
    # 假設是百分比，這裡先顯示原數字，若是 0.8 這種格式可自行 x100
    st.metric("升續率", f"{get_sum('遠傳升續率'):.1f}") 
with col_f3:
    st.metric("平續率", f"{get_sum('遠傳平續率'):.1f}")
with col_f4:
    st.metric("綜合指標", f"{get_sum('綜合指標'):.1f}")

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

# [第三層] 詳細資料表 (v1.9 終極重建法 - 支援自動欄位更新)
with st.expander(f"查看 {selected_branch} 詳細資料 (自動同步新增欄位)"):
    df_display = df_view.copy()
    
    # 格式化日期
    if '日期' in df_display.columns:
        df_display['日期'] = df_display['日期'].dt.strftime('%Y-%m-%d')
    
    # 1. 解構 (Deconstruct)
    data_as_dicts = df_display.to_dict(orient='records')
    
    # 2. 重建 (Rebuild)
    df_clean = pd.DataFrame(data_as_dicts)
    
    # 3. 欄位顯示設定
    column_config_settings = {}
    for col in df_clean.columns:
        if pd.api.types.is_numeric_dtype(df_clean[col]):
             # 讓所有數字看起來像整數 (如果您希望比率顯示小數點，這裡可以微調)
             # 目前設定：有小數點的會四捨五入顯示 (例如 0.8 會變 1)，若需精準可改 %.1f
             column_config_settings[col] = st.column_config.NumberColumn(format="%.0f")

    # 4. 顯示
    st.dataframe(
        df_clean,
        column_config=column_config_settings,
        use_container_width=True
    )

# --- 6. 頁尾版權與版本資訊 ---
st.markdown("---")
with st.container():
    col_footer_L, col_footer_R = st.columns([3, 1])
    
    with col_footer_L:
        st.caption("© 2026 馬尼通訊管理部 | Mani Communication Management System")
        
    with col_footer_R:
        with st.expander("ℹ️ 版本資訊"):
            st.markdown("""
            **目前版本：v2.1 (Auto-Detect)**
            - 新增：遠傳指標專區 (累積GAP、升續率、平續率、綜合指標)。
            - 優化：全自動欄位偵測 (未來新增欄位會自動顯示在詳細資料表中)。
            - 核心：維持 v1.9 的重建法核心，確保系統穩定。
            """)
