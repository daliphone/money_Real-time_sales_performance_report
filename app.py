import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime

# ==========================================
# 1. 系統基礎設定
# ==========================================
st.set_page_config(
    page_title="馬尼通訊戰情室 v8.8", 
    page_icon="📱", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# --- 安全登入機制 ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if not st.session_state.password_correct:
        st.markdown("### 🔒 請輸入戰情室密碼")
        with st.form("login_form"):
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("登入")
            if submitted:
                if "passwords" not in st.secrets:
                    st.error("❌ 找不到 secrets.toml 設定檔！")
                    return False
                
                if password == st.secrets["passwords"]["main_password"]:
                    st.session_state.password_correct = True
                    st.rerun()
                else:
                    st.error("密碼錯誤")
        return False
    return True

if not check_password():
    st.stop()

# ==========================================
# 2. 工具函式庫
# ==========================================

def clean_df_for_streamlit(df):
    """解決 int64 序列化問題"""
    if df.empty: return df
    df = df.reset_index(drop=True)
    try:
        data_dict = df.to_dict(orient='records')
        df_clean = pd.DataFrame(data_dict)
        return df_clean
    except:
        return df

def clean_google_sheet_url(url):
    """網址清洗"""
    if not isinstance(url, str): return url
    url = url.strip()
    if "#" in url: url = url.split("#")[0]
    if "/edit" in url: url = url.split("/edit")[0] + "/edit"
    return url

# ==========================================
# 3. 資料讀取層
# ==========================================

@st.cache_data(ttl=600)
def load_system_config():
    """讀取中控表與英雄榜"""
    if "leaderboard" not in st.secrets:
        return pd.DataFrame(), pd.DataFrame() 
    
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        config_url = clean_google_sheet_url(st.secrets["leaderboard"]["url"])
        
        # A. 系統配置
        df_config = conn.read(spreadsheet=config_url, worksheet="系統配置")
        if not df_config.empty:
            for col in df_config.columns:
                if df_config[col].dtype == object:
                    df_config[col] = df_config[col].astype(str).str.strip()
            
            if '月份' in df_config.columns:
                df_config['月份_dt'] = pd.to_datetime(df_config['月份'], errors='coerce')
                df_config['月份_std'] = df_config['月份_dt'].dt.strftime('%Y-%m')

        # B. 排名結果
        df_leaderboard_raw = conn.read(spreadsheet=config_url, worksheet="排名結果")
        df_clean = df_leaderboard_raw.copy()
        
        if not df_clean.empty:
             cols_list = list(df_clean.columns)
             cut_off_index = -1
             for i, col_name in enumerate(cols_list):
                 if "--->勿動" in str(col_name):
                     cut_off_index = i
                     break
             if cut_off_index != -1:
                 df_clean = df_clean.iloc[:, :cut_off_index]

             cols = [str(c) for c in df_clean.columns]
             
             if '月份' in df_clean.columns:
                 df_clean['月份'] = df_clean['月份'].astype(str).str.strip().replace(['', 'nan', 'None'], np.nan).fillna(method='ffill')
                 df_clean['月份_dt'] = pd.to_datetime(df_clean['月份'], errors='coerce')
                 df_clean['月份_std'] = df_clean['月份_dt'].dt.strftime('%Y-%m')

             if '分店' in df_clean.columns:
                 df_clean['分店'] = df_clean['分店'].astype(str).str.strip().replace(['', 'nan', 'None'], np.nan).fillna(method='ffill')
                 df_clean['分店'] = df_clean['分店'].astype(str).str.strip()

             if '人員' in df_clean.columns:
                 df_clean['人員'] = df_clean['人員'].astype(str).str.strip()

             if '來客數' in df_clean.columns:
                 if pd.api.types.is_datetime64_any_dtype(df_clean['來客數']):
                     base_date = pd.Timestamp("1899-12-30")
                     df_clean['來客數'] = (df_clean['來客數'] - base_date).dt.days
                 df_clean['來客數'] = pd.to_numeric(df_clean['來客數'], errors='coerce').fillna(0).astype(int)
             
             exclude_keywords = ["總表", "ALL", "Total", "小計", "合計", "小西門"] 
             mask_keyword = ~df_clean['人員'].isin(exclude_keywords)
             
             def is_not_store_summary(row):
                 branch = str(row['分店']).replace('店', '') 
                 person = str(row['人員'])
                 if person == branch: return False
                 if person == row['分店']: return False
                 return True

             mask_smart = df_clean.apply(is_not_store_summary, axis=1)
             df_clean = df_clean[mask_keyword & mask_smart]

        return df_config, df_clean
    except Exception as e:
        st.error(f"無法讀取系統配置表: {e}")
        return pd.DataFrame(), pd.DataFrame()


@st.cache_data(ttl=600)
def load_data(url, worksheet, selected_branch_name):
    """讀取單店日報表"""
    conn = st.connection("gsheets", type=GSheetsConnection)
    clean_url = clean_google_sheet_url(url)
    
    forced_name = None
    if "sheet_names" in st.secrets:
        forced_name = st.secrets["sheet_names"].get(selected_branch_name)
    
    try_list = []
    if worksheet == selected_branch_name or worksheet in ["ALL", "總表", "全店總表"]:
        if forced_name: try_list.append(forced_name)
        try_list.extend([worksheet, worksheet.replace("店", ""), "總表", "ALL"])
    else:
        try_list = [worksheet] 
        
    df_raw = pd.DataFrame()
    last_error = None
    
    for sheet_name in try_list:
        try:
            df_raw = conn.read(spreadsheet=clean_url, worksheet=sheet_name, header=None)
            break 
        except Exception as e:
            last_error = e
            continue 
    
    if df_raw.empty and (worksheet == selected_branch_name or worksheet in ["ALL", "總表", "全店總表"]):
        try:
            df_raw = conn.read(spreadsheet=clean_url, header=None)
        except Exception as e:
            last_error = e

    if df_raw.empty:
        raise ValueError(f"無法讀取分頁，已嘗試: {try_list}")

    try:
        year_val = pd.to_numeric(df_raw.iloc[1, 0], errors='coerce')
        month_val = pd.to_numeric(df_raw.iloc[1, 1], errors='coerce')
        year_val = int(year_val) if not pd.isna(year_val) else 2026
        month_val = int(month_val) if not pd.isna(month_val) else 1
    except:
        year_val = 2026; month_val = 1

    headers = df_raw.iloc[2].astype(str).str.strip()
    df = df_raw.iloc[14:].copy()
    df.columns = headers
    
    valid_columns = [col for col in df.columns if col.lower() != 'nan' and not col.startswith('Unnamed') and col.strip() != ""]
    df = df[valid_columns]
    df = df.loc[:, ~df.columns.duplicated()]
    
    if not df.empty:
        first_col = df.columns[0]
        df = df[pd.to_numeric(df[first_col], errors='coerce').notna()]
        df['year'] = year_val
        df['month'] = month_val
        df['day'] = df[first_col].astype(int)
        df['日期'] = pd.to_datetime(df[['year', 'month', 'day']], errors='coerce')
        df = df.drop(columns=['year', 'month', 'day'])

    for col in df.columns:
        if col != '日期':
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)
            
    return df

# --- [v8.6] 讀取延平毛利表 ---
@st.cache_data(ttl=600)
def load_yanping_data(sheet_name="2026年"):
    if "yanping" not in st.secrets:
        return pd.DataFrame()
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        url = clean_google_sheet_url(st.secrets["yanping"]["url"])
        df = conn.read(spreadsheet=url, worksheet=sheet_name, header=0)
        
        if not df.empty:
            df.columns = df.columns.str.strip()
            rename_map = {'門市薪水': '薪資', '門市獎金': '獎金', '總結': '淨利'}
            df.rename(columns=rename_map, inplace=True)

            numeric_cols = [
                'MDF', '買線MDF', '門市毛利', '機售毛利', '買線成本', '續約成本', 
                '薪資', '獎金', '勞健保', 
                '房租', '水電', 'POS租金', '印表機', '停車費', '雜費', '會計師費用', 
                '淨利'
            ]
            
            for col in df.columns:
                if any(keyword in col for keyword in numeric_cols):
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            if '日期' in df.columns:
                df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
        
        return df
    except Exception as e:
        return pd.DataFrame()

# --- [v8.8] 讀取馬尼毛利表 (民國年適配版) ---
@st.cache_data(ttl=600)
def load_mani_profit_data(roc_year="115"):
    """
    讀取馬尼門市毛利表
    :param roc_year: 民國年份字串 (如 "115")
    """
    if "mani_profit" not in st.secrets:
        return pd.DataFrame(), "Secrets 未設定 [mani_profit]"
    
    conn = st.connection("gsheets", type=GSheetsConnection)
    secrets_mani = st.secrets["mani_profit"]
    
    # 1. 取得網址 (使用 year_115 這樣的 key)
    url = secrets_mani.get(f"year_{roc_year}", secrets_mani.get("url", ""))
    
    if not url: return pd.DataFrame(), f"找不到 {roc_year} 年的網址設定 (請檢查 secrets [mani_profit] year_{roc_year})"

    url = clean_google_sheet_url(url)
    all_dfs = []
    debug_msg = []
    
    # 計算西元年份 (用於建立 datetime 物件)
    try:
        ad_year = int(roc_year) + 1911
    except:
        ad_year = 2026 # 預設值
    
    for i in range(1, 13):
        possible_sheets = [f"{i}月", f"{i}月 ", f"{i:02d}月", f"{i}"]
        df_raw = pd.DataFrame()
        for s in possible_sheets:
            try:
                temp = conn.read(spreadsheet=url, worksheet=s, header=None)
                if not temp.empty:
                    df_raw = temp
                    break
            except: continue
        
        if not df_raw.empty:
            try:
                num_rows = len(df_raw)
                if num_rows < 3: continue 

                branch_header_row = 0 
                row0_str = df_raw.iloc[0].astype(str).str.cat()
                if "毛利" not in row0_str and num_rows > 1:
                    branch_header_row = 1
                
                branch_headers = df_raw.iloc[branch_header_row].astype(str).str.strip().tolist()
                data_end_idx = min(num_rows, 11)
                
                df_month = df_raw.iloc[branch_header_row+1 : data_end_idx].copy()
                df_month.columns = branch_headers
                df_month = df_month.loc[:, ~df_month.columns.duplicated()]
                df_month = df_month.loc[:, (df_month.columns.notna()) & (df_month.columns != 'nan') & (df_month.columns != '')]
                
                if df_month.shape[1] > 0:
                     first_col = df_month.columns[0]
                     df_month = df_month[df_month[first_col].astype(str).str.strip() != '']

                summary_val = 0
                telecom_profit = 0
                machine_loss = 0
                renewal_income = 0
                
                if num_rows >= 16:
                    try:
                        s_header = df_raw.iloc[14].astype(str).str.strip().tolist()
                        s_row = df_raw.iloc[15]
                        
                        def get_val_by_col(name):
                             if name in s_header:
                                 return pd.to_numeric(s_row[s_header.index(name)], errors='coerce')
                             return 0

                        summary_val = get_val_by_col("總結算")
                        telecom_profit = get_val_by_col("門號毛利")
                        machine_loss = get_val_by_col("機損")
                        renewal_income = get_val_by_col("中華續約")
                    except: pass

                # [v8.8] 使用西元年份 (ad_year) 建立統一月份格式，方便 Plotly 排序
                month_str = f"{ad_year}-{i:02d}"
                df_month['月份_統一'] = month_str
                df_month['全公司總結算'] = summary_val if not pd.isna(summary_val) else 0
                df_month['全公司門號毛利'] = telecom_profit if not pd.isna(telecom_profit) else 0
                df_month['全公司機損'] = machine_loss if not pd.isna(machine_loss) else 0
                df_month['全公司中華續約'] = renewal_income if not pd.isna(renewal_income) else 0

                target_cols = [
                    '毛利', '薪水', '勞健保', '房租', '水電', '電話費', '保全', '影印機', 
                    'pos', '會計師', '綠界', '顧問系統', '手機王', '紙袋', '雜支', 
                    '關鍵字', 'fb', '內勤', '電台', '總結'
                ]
                for c in df_month.columns:
                    if any(t in c for t in target_cols):
                         df_month[c] = pd.to_numeric(df_month[c], errors='coerce').fillna(0)

                all_dfs.append(df_month)
            except Exception as e:
                debug_msg.append(f"{i}月: 解析錯誤 ({e})")
        else:
             if i <= datetime.now().month: debug_msg.append(f"{i}月: 讀取不到分頁")

    if all_dfs:
        df_final = pd.concat(all_dfs, ignore_index=True, sort=False)
        return df_final, ""
    else:
        return pd.DataFrame(), f"讀取失敗。詳細: {debug_msg}"

# =========================================================
# 4. 主程式邏輯 (Main UI)
# =========================================================

with st.sidebar:
    st.title("🚀 馬尼戰情室")
    app_mode = st.radio("選擇功能模組", ["📊 營運戰情室 (全店)", "💰 延平毛利分析總覽", "💰 馬尼門市毛利分析"])
    st.markdown("---")
    if st.button("🔄 更新資料/清除快取", type="primary"):
        st.cache_data.clear()
        st.rerun()

# =========================================================
# 模組 A: 營運戰情室 (全店)
# =========================================================
if app_mode == "📊 營運戰情室 (全店)":

    df_sys_config, df_lb_clean = load_system_config()
    
    with st.sidebar:
        if df_sys_config.empty:
            st.error("❌ 無法讀取配置表")
            st.stop()
        
        try:
            if '月份_std' in df_sys_config.columns:
                available_months = sorted(df_sys_config['月份_std'].dropna().unique(), reverse=True)
            else:
                available_months = sorted(df_sys_config['月份'].astype(str).unique(), reverse=True)
            
            current_month_str = datetime.now().strftime("%Y-%m")
            try: default_index = list(available_months).index(current_month_str)
            except: default_index = 0
        except:
            available_months = df_sys_config['月份'].astype(str).unique()
            default_index = 0

        st.header("📅 業績月份")
        selected_month = st.selectbox("請選擇月份", available_months, index=default_index)
        
        st.header("🏢 請選擇分店")
        mask_month = df_sys_config['月份_std'] == selected_month
        current_month_config = df_sys_config[mask_month]
        
        if current_month_config.empty:
            st.warning(f"找不到 {selected_month} 的設定")
            st.stop()

        branch_list = current_month_config['分店代號'].unique().tolist()
        if 'ALL' in branch_list:
            branch_list.remove('ALL')
            branch_list.insert(0, 'ALL')
        
        selected_branch = st.selectbox("切換分店看板", branch_list)

        try:
            target_row = current_month_config[current_month_config['分店代號'] == selected_branch]
            if not target_row.empty:
                raw_url = target_row.iloc[0]['試算表網址']
                target_url = clean_google_sheet_url(raw_url)
                if selected_branch != "ALL":
                    st.caption(f"🔗 連線中: {selected_branch}")
            else:
                st.error("找不到該分店網址"); st.stop()
        except:
            st.error("網址讀取失敗"); st.stop()

        target_person = "全店總表"
        worksheet_to_load = selected_branch 

        if selected_branch != "ALL":
            st.markdown("---")
            st.header("👤 選擇檢視對象")
            staff_list = st.secrets.get("branch_staff", {}).get(selected_branch, [])
            if not staff_list:
                staff_list = st.secrets.get("branch_staff", {}).get(selected_branch.replace("店",""), [])
            
            if staff_list:
                target_person = st.selectbox("請選擇人員", ["全店總表"] + staff_list)
                worksheet_to_load = selected_branch if target_person == "全店總表" else target_person
            else:
                st.caption("⚠️ 未偵測到人員名單")
        st.info(f"檢視模式：{selected_month} > {selected_branch}")

    try:
        df_view = load_data(target_url, worksheet_to_load, selected_branch)
    except Exception as e:
        st.error(f"❌ 資料讀取失敗"); st.stop()

    display_title = f"{selected_month} {selected_branch} - {target_person}"
    st.title(f"📊 {display_title} 戰情室")

    if df_view.empty: st.warning("⚠️ 無資料"); st.stop()

    def get_sum(col_name): return df_view.get(col_name, pd.Series([0])).sum()

    st.markdown("### 💰 營收與獲利")
    m1, m2, m3 = st.columns(3)
    with m1: st.metric("總毛利", f"${get_sum('毛利'):,.0f}")
    with m2: st.metric("配件營收", f"${get_sum('配件營收'):,.0f}")
    with m3: st.metric("保險營收", f"${get_sum('保險營收'):,.0f}")

    st.markdown("### 📈 關鍵營運指標")
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("門號申辦數", f"{get_sum('門號'):,.0f}")
    with c2: st.metric("總來客數", f"{get_sum('來客數'):,.0f}")
    with c3: st.metric("Google 評論", f"{get_sum('GOOGLE 評論'):,.0f}")
    with c4: st.metric("生活圈加入", f"{get_sum('生活圈'):,.0f}")

    st.markdown("### 📱 手機與硬體銷售/庫存")
    i1, i2, i3, i4 = st.columns(4)
    with i1: st.metric("庫存手機", f"{get_sum('庫存手機'):,.0f}")
    with i2: st.metric("VIVO 手機", f"{get_sum('VIVO手機'):,.0f}")
    with i3: st.metric("蘋果手機", f"{get_sum('蘋果手機'):,.0f}")
    with i4: st.metric("蘋果平板+手錶", f"{get_sum('蘋果平板+手錶'):,.0f}")

    i5, i6, i7, i8 = st.columns(4)
    with i5: st.metric("華為穿戴", f"{get_sum('華為穿戴'):,.0f}")
    with i6: st.metric("GPLUS 吸塵器", f"{get_sum('GPLUS GP-S10吸塵器'):,.0f}")
    with i7: st.metric("VIVO 目標", f"{get_sum('VIVO銷售目標'):,.0f}")
    with i8: st.metric("橙艾玻璃貼", f"{get_sum('橙艾玻璃貼(13,14,15系列)'):,.0f}")

    st.markdown("### 🔵 遠傳指標")
    f1, f2, f3, f4 = st.columns(4)
    with f1: st.metric("續約累積 GAP", f"{get_sum('遠傳續約累積GAP'):,.0f}")
    with f2: st.metric("升續率", f"{get_sum('遠傳升續率'):.1f}") 
    with f3: st.metric("平續率", f"{get_sum('遠傳平續率'):.1f}")
    with f4: st.metric("綜合指標", f"{get_sum('綜合指標'):.1f}")

    st.markdown("---")

    c1, c2 = st.columns([2, 1])

    if df_lb_clean.empty:
        df_lb_month = pd.DataFrame()
    else:
        mask_lb_month = df_lb_clean['月份_std'] == selected_month
        df_lb_month = df_lb_clean[mask_lb_month].copy()

    with c1:
        st.subheader("📈 日毛利趨勢")
        if '日期' in df_view.columns:
            daily_profit = df_view.groupby('日期')['毛利'].sum().reset_index()
            daily_profit = clean_df_for_streamlit(daily_profit)
            st.plotly_chart(px.line(daily_profit, x='日期', y='毛利', markers=True, color_discrete_sequence=['#1f77b4']), use_container_width=True)

    with c2:
        st.subheader("🏆 業績佔比")
        if not df_lb_month.empty:
            pie_data = df_lb_month if selected_branch == "ALL" else df_lb_month[df_lb_month['分店'] == selected_branch]
            group_key = '分店' if selected_branch == "ALL" else '人員'
            if not pie_data.empty:
                 pie_data['毛利'] = pd.to_numeric(pie_data['毛利'], errors='coerce').fillna(0)
                 fig_pie = px.pie(pie_data, values='毛利', names=group_key, hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                 st.plotly_chart(fig_pie, use_container_width=True)
            else:
                 st.info("尚無資料可繪製")

    st.subheader("🏆 業績英雄榜")
    with st.expander("查看排名細節", expanded=True):
        if not df_lb_month.empty:
            df_rank_source = df_lb_month if selected_branch == "ALL" else df_lb_month[df_lb_month['分店'] == selected_branch]
            
            if not df_rank_source.empty:
                fixed_cols = ['月份', '分店', '人員', '更新時間', 'Display', '月份_dt', '月份_std', '來客數', 'Index'] 
                available_metrics = [c for c in df_rank_source.columns if c not in fixed_cols]
                default_metrics = ['毛利', '門號', '配件營收', '保險營收']
                metric_options = sorted(available_metrics, key=lambda x: default_metrics.index(x) if x in default_metrics else 999)

                if selected_branch == "ALL":
                    tab1, tab2 = st.tabs(["👤 個人排名", "🏢 門市排名"])
                    with tab1:
                        col1, col2 = st.columns([1, 3])
                        with col1: rank_p = st.radio("指標 (個人)", metric_options, key="rank_p")
                        with col2:
                            df_p = df_rank_source.copy()
                            df_p[rank_p] = pd.to_numeric(df_p[rank_p], errors='coerce').fillna(0)
                            df_p = df_p.sort_values(rank_p, ascending=False).head(20)
                            df_p['Display'] = df_p['分店'] + " - " + df_p['人員']
                            st.plotly_chart(px.bar(df_p, x=rank_p, y='Display', orientation='h', text=rank_p, color=rank_p, color_continuous_scale='Blues').update_layout(yaxis={'categoryorder':'total ascending', 'title': ''}), use_container_width=True)
                    with tab2:
                        col1, col2 = st.columns([1, 3])
                        with col1: rank_s = st.radio("指標 (門市)", metric_options, key="rank_s")
                        with col2:
                            df_s = df_rank_source.copy()
                            df_s[rank_s] = pd.to_numeric(df_s[rank_s], errors='coerce').fillna(0)
                            df_store = df_s.groupby('分店')[rank_s].sum().reset_index().sort_values(rank_s, ascending=False)
                            st.plotly_chart(px.bar(df_store, x=rank_s, y='分店', orientation='h', text=rank_s, color=rank_s, color_continuous_scale='Reds').update_layout(yaxis={'categoryorder':'total ascending', 'title': ''}), use_container_width=True)
                else:
                    col1, col2 = st.columns([1, 3])
                    with col1: rank_single = st.radio("選擇排名指標", metric_options, key="rank_single")
                    with col2:
                        df_s = df_rank_source.copy()
                        df_s[rank_single] = pd.to_numeric(df_s[rank_single], errors='coerce').fillna(0)
                        df_s = df_s.sort_values(rank_single, ascending=False)
                        st.plotly_chart(px.bar(df_s, x=rank_single, y='人員', orientation='h', text=rank_single, color=rank_single, color_continuous_scale='Teal').update_layout(yaxis={'categoryorder':'total ascending', 'title': ''}), use_container_width=True)

                if '更新時間' in df_rank_source.columns: st.caption(f"ℹ️ 數據更新時間：{df_rank_source['更新時間'].iloc[0]}")
            else: st.info("尚無排名數據")
        else: st.info("尚無排名數據")

    st.markdown("---")

    with st.expander(f"查看 {display_title} 詳細資料"):
        df_display = df_view.copy()
        if '日期' in df_display.columns: df_display['日期'] = df_display['日期'].dt.strftime('%Y-%m-%d')
        first_col_name = df_display.columns[0]
        if '日期' in df_display.columns:
            cols = ['日期'] + [c for c in df_display.columns if c != '日期' and c != first_col_name]
            df_display = df_display[cols]
        df_display = clean_df_for_streamlit(df_display)
        for col in df_display.columns:
            if pd.api.types.is_numeric_dtype(df_display[col]):
                df_display[col] = df_display[col].astype(float)
        st.dataframe(df_display, use_container_width=True, hide_index=True)

# =========================================================
#  模組 B: 延平毛利分析 (v8.6 修正)
# =========================================================
elif app_mode == "💰 延平毛利分析總覽":
    st.title("💰 延平毛利分析總覽")
    with st.sidebar:
        st.header("📅 選擇年份")
        selected_year_sheet = st.selectbox("選擇年度分頁", ["2026年", "2025年", "2024年"], index=0)
    
    df_yan = load_yanping_data(selected_year_sheet)
    if df_yan.empty: st.warning("尚無資料"); st.stop()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 獲利結構", "🚀 業務效益", "👥 人事效率", "⚖️ 損益平衡", "⚡ 異常監控"])
    with tab1:
        target = ['MDF', '買線MDF', '門市毛利', '機售毛利']
        cols = [c for c in target if c in df_yan.columns]
        if cols:
             st.plotly_chart(px.area(df_yan, x=df_yan.index, y=cols, title="月度獲利結構堆疊圖"), use_container_width=True)
    with tab2:
        if '買線MDF' in df_yan.columns and '買線成本' in df_yan.columns:
             df_yan['新辦獲利'] = df_yan['買線MDF'] - df_yan['買線成本']
             st.plotly_chart(px.bar(df_yan, x=df_yan.index, y='新辦獲利', title="新辦案件淨利趨勢"), use_container_width=True)
    with tab3:
        fig_hr = go.Figure()
        bonus = next((c for c in ['獎金', '門市獎金'] if c in df_yan.columns), None)
        profit = next((c for c in ['淨利', '總結'] if c in df_yan.columns), None)
        if bonus: fig_hr.add_trace(go.Bar(x=df_yan.index, y=df_yan[bonus], name='發放獎金'))
        if profit: fig_hr.add_trace(go.Scatter(x=df_yan.index, y=df_yan[profit], name='淨利', yaxis='y2'))
        fig_hr.update_layout(yaxis2=dict(overlaying='y', side='right'))
        st.plotly_chart(fig_hr, use_container_width=True)
    with tab4:
        fix_cols = [c for c in ['房租', '水電', '薪資', '門市薪水', '基本底薪'] if c in df_yan.columns]
        if fix_cols:
             fixed_cost = int(df_yan.iloc[-1][fix_cols].sum())
             col1, col2 = st.columns([1, 2])
             with col1: f_in = st.number_input("固定成本", value=fixed_cost, step=5000)
             with col2: m_in = st.number_input("平均毛利", value=1500)
             st.metric("損益平衡件數", f"{f_in/m_in:.0f} 件")
    with tab5:
        exp_cols = [c for c in ['房租', '水電', '雜費'] if c in df_yan.columns]
        if exp_cols: st.plotly_chart(px.imshow(df_yan[exp_cols].T), use_container_width=True)

    st.subheader("原始資料檢視")
    st.dataframe(df_yan, use_container_width=True)

# =========================================================
#  模組 C: 馬尼門市毛利分析 (v8.8 民國年適配版)
# =========================================================
elif app_mode == "💰 馬尼門市毛利分析":
    st.title("💰 馬尼門市毛利分析")
    with st.sidebar:
        st.header("📅 選擇年份")
        # [v8.8] 使用民國年選單
        year_list = ["115年", "114年", "113年"] 
        selected_year_roc = st.selectbox("選擇年度檔案", year_list, index=0)
    
    # 提取年份數字 (115)
    roc_year_str = selected_year_roc.replace("年", "")
    
    with st.spinner(f"正在讀取 {selected_year_roc} (民國) 資料..."):
        df_mani, err = load_mani_profit_data(roc_year=roc_year_str)
    
    if df_mani.empty: st.warning(f"⚠️ {err if err else '尚無資料'}")
    else:
        df_mani = clean_df_for_streamlit(df_mani)
        
        if '月份_統一' in df_mani.columns:
             df_monthly = df_mani.drop_duplicates(subset=['月份_統一'])[['月份_統一', '全公司總結算', '全公司門號毛利', '全公司機損', '全公司中華續約']].copy()
             df_monthly.set_index('月份_統一', inplace=True)
             
             branch_col = df_mani.columns[0] # 店名

             tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 獲利結構", "🚀 分店淨利排行", "👥 人事效率", "⚖️ 損益平衡", "⚡ 異常監控"])
             
             with tab1:
                 df_stores_sum = df_mani.groupby('月份_統一')['總結'].sum().reset_index().rename(columns={'總結': '分店淨利總和'})
                 df_viz = df_monthly.reset_index().merge(df_stores_sum, on='月份_統一', how='left').set_index('月份_統一')
                 df_viz['總部額外收益'] = df_viz['全公司門號毛利'] + df_viz['全公司中華續約'] - df_viz['全公司機損']
                 st.plotly_chart(px.area(df_viz, x=df_viz.index, y=['分店淨利總和', '總部額外收益'], title="全公司獲利來源結構"), use_container_width=True)

             with tab2:
                 sel_m = st.selectbox("選擇月份", df_mani['月份_統一'].unique(), index=len(df_mani['月份_統一'].unique())-1)
                 st.plotly_chart(px.bar(df_mani[df_mani['月份_統一']==sel_m].sort_values('總結'), x='總結', y=branch_col, orientation='h', title=f"{sel_m} 各店淨利排名"), use_container_width=True)

             with tab3:
                 if '薪水' in df_mani.columns and '勞健保' in df_mani.columns:
                      df_hr = df_mani.groupby('月份_統一')[['薪水', '勞健保', '毛利']].sum().reset_index()
                      df_hr['人事總成本'] = df_hr['薪水'] + df_hr['勞健保']
                      df_hr['人事費用率'] = (df_hr['人事總成本'] / df_hr['毛利'] * 100).replace([np.inf, -np.inf], 0).fillna(0)
                      fig_hr = go.Figure()
                      fig_hr.add_trace(go.Bar(x=df_hr['月份_統一'], y=df_hr['人事總成本'], name='人事總成本'))
                      fig_hr.add_trace(go.Scatter(x=df_hr['月份_統一'], y=df_hr['人事費用率'], name='費用率%', yaxis='y2'))
                      fig_hr.update_layout(yaxis2=dict(overlaying='y', side='right', range=[0, 100]))
                      st.plotly_chart(fig_hr, use_container_width=True)

             with tab4:
                 all_exp = ['薪水', '勞健保', '房租', '水電', '電話費', '保全', '影印機', 'pos', '會計師', '綠界', '顧問系統', '手機王', '紙袋', '雜支', '關鍵字', 'fb', '內勤', '電台']
                 valid_exp = [c for c in all_exp if c in df_mani.columns]
                 if valid_exp:
                      latest_cost = df_mani[df_mani['月份_統一'] == df_mani['月份_統一'].iloc[-1]][valid_exp].sum().sum()
                      c1, c2 = st.columns([1, 2])
                      with c1: f_in = st.number_input("本月總支出", value=int(latest_cost), step=10000)
                      with c2: m_in = st.number_input("平均毛利", value=1500)
                      st.metric("損益平衡成交件數", f"{f_in/m_in:.0f} 件")

             with tab5:
                 mon_cols = ['房租', '水電', '電話費', '關鍵字', 'fb', '雜支', '內勤']
                 valid_mon = [c for c in mon_cols if c in df_mani.columns]
                 if valid_mon:
                      st.plotly_chart(px.imshow(df_mani.groupby('月份_統一')[valid_mon].sum().T, title="費用熱力圖"), use_container_width=True)

             st.subheader("📄 年度詳細數據檢視")
             st.dataframe(df_mani, use_container_width=True)
        else:
             st.warning("資料格式異常")
             st.dataframe(df_mani)
