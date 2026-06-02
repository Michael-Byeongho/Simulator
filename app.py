import streamlit as st
import pandas as pd
import json
import os
import io

# --- [페이지 설정] ---
st.set_page_config(page_title="동정광 블렌딩 & 판매 관리", layout="wide")

# --- [파일 저장/로드 로직] ---
DB_FILE = "smelters.json"

def load_smelters():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for name in data:
                    if 'RC' not in data[name]: 
                        data[name]['RC'] = 0.08
                return data
        except Exception as e:
            st.error(f"데이터베이스 로드 중 오류 발생: {e}")
            pass
    return {}

def save_smelters(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

if 'smelters' not in st.session_state:
    st.session_state['smelters'] = load_smelters()

# --- [상단 탭 구성] ---
tab_input, tab_setting = st.tabs(["📊 데이터 분석 및 실행", "⚙️ 판매 조건 상세 설정"])

# ==========================================
# --- [Tab 1] 데이터 분석 실행 화면 ---
# ==========================================
with tab_input:
    with st.sidebar:
        st.header("📊 시장가격")
        lme_cu = st.number_input("LME Cu ($/mt)", value=12000.0, format="%.2f")
        silver_price = st.number_input("Silver ($/oz)", value=70.0, format="%.2f")
        gold_price = st.number_input("Gold ($/oz)", value=4500.0, format="%.2f")

    st.subheader("구매 Lot 정보 입력")
    st.caption("💡 **안내**: 중량은 소수점 3자리까지 표시하고 복/붙하세요.")

    init_data = pd.DataFrame([{
        "Vendors": "", "Lot No": "", 
        "WMT": 0.000, "H2O(%)": 0.00, "DMT": 0.000, "Franchise(%)": 0.00, "NDMT": 0.000, 
        "Cu(%)": 0.000, "Ag(g/MT)": 0.00, "Au(g/MT)": 0.00, "As(%)": 0.000
    }])
    
    edited_df = st.data_editor(
        init_data, num_rows="dynamic", use_container_width=True,
        column_config={
            "WMT": st.column_config.NumberColumn(format="%.3f"),
            "DMT": st.column_config.NumberColumn(format="%.3f"),
            "NDMT": st.column_config.NumberColumn(format="%.3f"),
            "Cu(%)": st.column_config.NumberColumn(format="%.3f"),
            "As(%)": st.column_config.NumberColumn(format="%.3f"),
        }
    )

    if st.button("📈 분석 실행"):
        df = edited_df.copy()
        numeric_cols = ["WMT", "DMT", "NDMT", "Cu(%)", "Au(g/MT)", "Ag(g/MT)", "As(%)"]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
        final_df = df[df['NDMT'] > 0].copy()
        
        if final_df.empty:
            st.warning("분석할 데이터를 입력해주세요.")
        else:
            total_wmt = final_df['WMT'].sum()
            total_dmt = final_df['DMT'].sum()
            total_ndmt = final_df['NDMT'].sum()
            
            avg_cu = (final_df['Cu(%)'] * final_df['NDMT']).sum() / total_ndmt
            avg_ag = (final_df['Ag(g/MT)'] * final_df['NDMT']).sum() / total_ndmt
            avg_au = (final_df['Au(g/MT)'] * final_df['NDMT']).sum() / total_ndmt
            avg_as = (final_df['As(%)'] * final_df['NDMT']).sum() / total_ndmt
            
            st.success(f"### ✅ 총 {len(final_df)}개 Lot 페이퍼 블렌딩 결과")
            m1, m2, m3 = st.columns(3)
            m1.metric("총 WMT", f"{total_wmt:,.3f} mt")
            m2.metric("총 DMT", f"{total_dmt:,.3f} mt")
            m3.metric("총 NDMT", f"{total_ndmt:,.3f} mt")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("평균 Cu", f"{avg_cu:.2f} %")
            c2.metric("평균 Ag", f"{avg_ag:.2f} g/t")
            c3.metric("평균 Au", f"{avg_au:.2f} g/t")
            
            as_threshold = 0.4
            if avg_as >= as_threshold:
                c4.metric("평균 As", f"{avg_as:.3f} %", delta="기준 초과(0.4%↑)", delta_color="inverse")
            else:
                c4.metric("평균 As", f"{avg_as:.3f} %")

            match_results = [] 
            for name, spec in st.session_state['smelters'].items():
                # --- 1. Cu 계산 ---
                cu_p = float(spec.get('Cu_pay', 0)) / 100
                cu_md = float(spec.get('Cu_MD', 0))
                payable_cu_pct = max(0, min(avg_cu * cu_p, avg_cu - cu_md))
                cu_rev = (payable_cu_pct / 100) * lme_cu
                
                # Cu-RC 단가의 부호(-3.4 등)를 그대로 유지
                cu_rc_val = float(spec.get('Cu-RC', 8.0)) / 100
                cu_rc_ton = (payable_cu_pct * 22.0462) * cu_rc_val

                # --- 2. Ag 계산 ---
                ag_min = float(spec.get('Ag_min', 0))
                ag_pay_ratio = float(spec.get('Ag_pay', 0)) / 100
                ag_pay_qty_g = avg_ag * ag_pay_ratio if avg_ag >= ag_min else 0
                ag_oz_per_ton = ag_pay_qty_g * 0.032150747
                ag_rev_ton = ag_oz_per_ton * silver_price
                # Ag-RC 단가의 부호(+0.5 등)를 그대로 유지
                ag_rc_ton = ag_oz_per_ton * float(spec.get('Ag-RC', 0.50))

                # --- 3. Au 계산 ---
                au_pay_qty_g = 0
                au_tiers = spec.get('Au_tiers', [])
                for tier in au_tiers:
                    if float(tier.get('Min(>)', 0)) < avg_au <= float(tier.get('Max(<=)', 9999)):
                        ded = float(tier.get('Ded(g)') or 0)
                        pay = float(tier.get('Pay(%)', 0)) / 100
                        au_pay_qty_g = max(0, (avg_au - ded) * pay)
                        break
                        
                au_oz_per_ton = au_pay_qty_g * 0.032150747
                au_rev_ton = au_oz_per_ton * gold_price
                # Au-RC 단가의 부호(+5.0 등)를 그대로 유지
                au_rc_ton = au_oz_per_ton * float(spec.get('Au-RC', 5.00))

                # --- 4. 기타 비용 및 대수적 합산 ---
                tc = float(spec.get('TC', 0)) # -34.00 등의 음수 그대로 로드
                cntr = float(spec.get('CNTR', 0)) 
                cntr_per_dmt = cntr * (total_wmt / total_dmt) if total_dmt > 0 else 0
                
                # abs()를 제거하여 부호대로 연산 (-34 + -16.44 + 1.93 + 1.64...)
                # 결과적으로 보통 음수 값(예: -46.87)이 도출됨
                total_costs = tc + cu_rc_ton + ag_rc_ton + au_rc_ton + cntr_per_dmt
                
                # 톤당 순수익: 매출 - (음수 디덕션) = 매출 + 디덕션 (단가 상승)
                net_rev_ton = (cu_rev + au_rev_ton + ag_rev_ton) - total_costs
                total_net_rev = net_rev_ton * total_dmt

                # --- 5. 결과 리스트 추가 ---
                match_results.append({
                    '제련소': name, 
                    '판매단가($/DMT)': round(net_rev_ton, 2),
                    '총 판매금액($)': round(total_net_rev, 2),
                    'Cu단가($)': round(cu_rev, 2),
                    'Ag단가($)': round(ag_rev_ton, 2),  
                    'Au단가($)': round(au_rev_ton, 2),
                    'Deductions($)': round(total_costs, 2) # 산출된 음수 총액 그대로 표기
                })

                
            # --- 6. 화면에 결과 출력 (여기가 테이블과 디자인 세팅 설정!) ---
            if match_results:
                st.divider()
                st.subheader("🏆 제련소별 예상 수익 비교표")
                
                results_df = pd.DataFrame(match_results)
                
                if not results_df.empty and "총 판매금액($)" in results_df.columns:
                    results_df = results_df.sort_values(by="총 판매금액($)", ascending=False).reset_index(drop=True)
                    
                    st.dataframe(
                        results_df,
                        use_container_width=True,
                        column_config={
                            "판매단가($/DMT)": st.column_config.NumberColumn(format="$ %.2f"),
                            "총 판매금액($)": st.column_config.NumberColumn(format="$ %.2f"),
                            "Cu단가($)": st.column_config.NumberColumn(format="$ %.2f"),
                            "Ag단가($)": st.column_config.NumberColumn(format="$ %.2f"),
                            "Au단가($)": st.column_config.NumberColumn(format="$ %.2f"),
                            "Deductions($)": st.column_config.NumberColumn(format="$ %.2f") 
                        }
                    )
                    
                else:
                    st.error("데이터 정렬 중 오류가 발생했습니다. 컬럼명을 확인해 주세요.")

# ==========================================
# --- [Tab 2] 판매 조건 설정 탭 ---
# ==========================================
with tab_setting:
    st.header("🏢 판매 조건 설정")

    if "add_error" not in st.session_state:
        st.session_state.add_error = None

    def add_smelter():
        name_to_add = st.session_state.new_smelter_input.strip()
        if not name_to_add:
            return

        if name_to_add in st.session_state['smelters']:
            st.session_state.add_error = f"'{name_to_add}'은(는) 이미 존재하는 이름입니다."
        else:
            existing_keys = list(st.session_state['smelters'].keys())
            if existing_keys:
                first_key = existing_keys[0]
                st.session_state['smelters'][name_to_add] = st.session_state['smelters'][first_key].copy()
            else:
                st.session_state['smelters'][name_to_add] = {
                    'Cu_pay': 0.965, 'Cu_MD': 1.0, 'TC': 80.0, 'RC': 0.08,
                    'Au_pay': 0.90, 'Ag_pay': 0.90, 'As_limit': 0.4
                }
            
            save_smelters(st.session_state['smelters'])
            st.session_state.add_error = None
            st.toast(f"✨ {name_to_add} 추가 완료!", icon='🆕')
            st.session_state.new_smelter_input = ""

    # 신규 판매선 추가 UI
    st.subheader("➕ 신규 판매선 추가")
    if st.session_state.add_error:
        st.error(st.session_state.add_error)

    col_add1, col_add2 = st.columns([3, 1])
    with col_add1:
        st.text_input(
            "판매선 이름을 입력하세요", 
            key="new_smelter_input", 
            on_change=add_smelter
        )
    with col_add2:
        st.write(" ") 
        st.button("🚀 추가", use_container_width=True, on_click=add_smelter)

    st.divider()

    # 기존 판매선 수정 UI
    smelter_names = list(st.session_state['smelters'].keys())

    if smelter_names:
        selected_smelter = st.selectbox("수정할 판매선 이름을 선택하세요", smelter_names)
        
        with st.form("smelter_edit_form"):
            s = st.session_state['smelters'][selected_smelter].copy()
            edit_name = st.text_input("판매 텀 상세 내용 (이름 변경 시 신규 저장됨)", value=selected_smelter)
            st.divider()
            
            c1, c2, c3 = st.columns(3)
            with c1:
                st.subheader("구리 %")
                s['Cu_pay'] = st.number_input("Payable (%)", value=float(s.get('Cu_pay', 0)), format="%.2f")
                s['Cu_MD'] = st.number_input("MD(unit)", value=float(s.get('Cu_MD', 0)), format="%.2f")

            with c2:
                st.subheader("은 G/MT")
                s['Ag_min'] = st.number_input("Min. Content (g/t)", value=float(s.get('Ag_min', 0.0)), format="%.2f")
                s['Ag_pay'] = st.number_input("Ag Pay (%)", value=float(s.get('Ag_pay', 0.0)), format="%.2f")

            with c3:
                st.subheader("금 G/MT")
                current_tiers = s.get('Au_tiers', [
                    {"Min(>)": 0.0, "Max(<=)": 0.5, "Ded(g)": 0.0, "Pay(%)": 0.0},
                    {"Min(>)": 0.5, "Max(<=)": 1.0, "Ded(g)": 0.3, "Pay(%)": 100.0},
                    {"Min(>)": 1.0, "Max(<=)": 3.0, "Ded(g)": 0.0, "Pay(%)": 90.0},
                    {"Min(>)": 3.0, "Max(<=)": 5.0, "Ded(g)": 0.0, "Pay(%)": 95.0}
                ])
                s['Au_tiers'] = st.data_editor(current_tiers, num_rows="dynamic", use_container_width=True, key=f"editor_{selected_smelter}")

            st.divider()
            st.subheader("💰 Deductions & Costs")
            c4_1, c4_2, c4_3 = st.columns(3)
            with c4_1:
                s['TC'] = st.number_input("TC ($/dmt)", value=float(s.get('TC', 0)), format="%.2f")
            with c4_2:
                s['Cu-RC'] = st.number_input("Cu RC ($/lb)", value=float(s.get('Cu-RC', 0.08)), format="%.2f")
                s['Ag-RC'] = st.number_input("Ag RC ($/oz)", value=float(s.get('Ag-RC', 0.50)), format="%.2f")
                s['Au-RC'] = st.number_input("Au RC ($/oz)", value=float(s.get('Au-RC', 5.00)), format="%.2f")
            with c4_3:
                s['CNTR'] = st.number_input("CNTR ($/wmt)", value=float(s.get('CNTR', 0)), format="%.2f")

            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                submit_btn = st.form_submit_button("💾 수정사항 저장", use_container_width=True)
            with col_btn2:
                delete_btn = st.form_submit_button("🗑️ 삭제", use_container_width=True)

            # --- [저장 로직 처리] ---
            if submit_btn:
                if edit_name != selected_smelter:
                    if selected_smelter in st.session_state['smelters']:
                        del st.session_state['smelters'][selected_smelter]
                
                st.session_state['smelters'][edit_name] = s
                save_smelters(st.session_state['smelters'])
                st.success(f"✅ '{edit_name}' 정보가 성공적으로 저장되었습니다.")
                st.rerun()

            # --- [삭제 로직 처리] ---
            if delete_btn:
                if len(st.session_state['smelters']) > 1:
                    del st.session_state['smelters'][selected_smelter]
                    save_smelters(st.session_state['smelters'])
                    st.warning(f"🗑️ '{selected_smelter}' 판매선이 삭제되었습니다.")
                    st.rerun()
                else:
                    st.error("⚠️ 최소 한 개의 판매선 정보는 유지해야 합니다. (전체 삭제 불가)")

        # 복사 기능
        with st.expander("👯 조건을 복사하여 새로 만들기"):
            copy_name = st.text_input("새로운 판매선 이름을 입력하세요", key="copy_name_input")
            if st.button("복사하기"):
                if copy_name and copy_name not in st.session_state['smelters']:
                    st.session_state['smelters'][copy_name] = st.session_state['smelters'][selected_smelter].copy()
                    save_smelters(st.session_state['smelters'])
                    st.rerun()
                else:
                    st.error("이름이 중복되거나 비어있습니다.")
    else:
        st.info("등록된 판매선이 없습니다. 상단에서 새로 추가해주세요.")

    st.divider()
    st.subheader("📥 전체 조건 내보내기")

    @st.cache_data
    def convert_to_excel(smelters_dict):
        all_data = []
        for name, specs in smelters_dict.items():
            row = specs.copy()
            row['제련소명'] = name
            
            if 'Au_tiers' in row and isinstance(row['Au_tiers'], list):
                tier_texts = []
                for t in row['Au_tiers']:
                    txt = f"{t.get('Min(>)',0)}~{t.get('Max(<=)',0)}g: {t.get('Pay(%)',0)}%"
                    tier_texts.append(txt)
                row['Au_Pay_Conditions'] = " / ".join(tier_texts)
            
            all_data.append(row)
        
        df = pd.DataFrame(all_data)

        desired_order = [
            '제련소명', 'Cu_pay', 'Cu_MD', 'Ag_pay', 'Ag_min',
            'Au_Pay_Conditions', 'TC', 'Cu-RC', 'Ag-RC', 'Au-RC', 'CNTR'
        ]
        
        final_cols = [col for col in desired_order if col in df.columns]
        remaining_cols = [col for col in df.columns if col not in desired_order and col != 'Au_tiers']
        df = df[final_cols + remaining_cols]

        rename_map = {
            '제련소명': '판매선(제련소)',
            'Cu_pay': 'Cu Pay(%)', 'Cu_MD': 'Cu Ded(unit)',
            'Ag_pay': 'Ag Pay(%)', 'Ag_min': 'Ag Min(g/t)',
            'Au_Pay_Conditions': 'Au Pay 구간별 조건',
            'TC': 'TC($/dmt)', 'Cu-RC': 'Cu RC($/lb)', 
            'Ag-RC': 'Ag RC($/oz)', 'Au-RC': 'Au RC($/oz)', 'CNTR': '기타비용(CNTR)'
        }
        df = df.rename(columns=rename_map)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Sales_Terms')
            
            worksheet = writer.sheets['Sales_Terms']
            for i, col in enumerate(df.columns):
                column_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                worksheet.set_column(i, i, column_len)
                
        return output.getvalue()

    # 다운로드 버튼 배치
    if smelter_names:
        excel_data = convert_to_excel(st.session_state['smelters'])
        st.download_button(
            label="📊 전체 판매 조건 엑셀 다운로드",
            data=excel_data,
            file_name="smelter_terms_all.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

