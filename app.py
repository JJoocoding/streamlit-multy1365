import streamlit as st
import pandas as pd
import numpy as np
import requests
import itertools
import json
import xmltodict
from datetime import datetime
import re
import io 

st.set_page_config(layout="wide")
st.title("🏗️ 1365 사정율 분석 도구")
st.markdown("공고번호를 입력하면 복수예가 조합, 낙찰하한율, 개찰결과를 분석해 드립니다.")

# 커스텀 CSS 삽입 - 줄바꿈을 강제하고 폰트 크기 조절 시도
st.markdown("""
<style>
/* 통합 사정율 테이블 헤더 셀 스타일 */
/* 이 셀렉터는 Streamlit 버전에 따라 변경될 수 있습니다. F12 개발자 도구로 정확한 클래스명을 확인해야 합니다. */
div[data-testid="stDataFrame"] .st-emotion-cache-16ffz97 { /* 통합 테이블 헤더 셀 (예: Streamlit 1.28+) */
    white-space: normal !important; /* 필요에 따라 줄바꿈 허용 (기본값) */
    word-wrap: break-word !important; /* 긴 단어도 강제 줄바꿈 */
    text-align: center; /* 텍스트 가운데 정렬 */
    vertical-align: middle; /* 세로 가운데 정렬 */
    font-size: 11px; /* 글자 크기 조정 */
    line-height: 1.3; /* 줄 간격 조정 */
    padding: 4px 8px; /* 패딩 조정 */
}

/* Rate 컬럼 헤더는 좌측 정렬 유지 및 글자 크기 조정 */
div[data-testid="stDataFrame"] .st-emotion-cache-16ffz97:first-child {
    text-align: left !important;
    font-size: 12px !important; /* Rate 컬럼 헤더의 글자 크기는 조금 더 크게 */
}

/* 각 공고별 사정율 테이블의 헤더 셀 (개별 테이블에만 적용) */
.stDataFrame > div > div > div > div > div > div:nth-child(2) > div > div > div > div {
    white-space: normal !important; /* 필요에 따라 줄바꿈 허용 */
    word-wrap: break-word !important;
    text-align: center;
    vertical-align: middle;
    font-size: 11px;
    line-height: 1.3;
    padding: 4px 8px;
}
</style>
""", unsafe_allow_html=True)


display_width = st.selectbox("📏 표 표시 너비 설정", ["자동(전체 너비)", "고정(좁게)"])
use_wide = display_width == "자동(전체 너비)" 

st.subheader("🔍 분석할 공고번호를 1개에서 10개까지 입력하세요 (줄바꿈으로 구분)")

# session_state에 gongo_nums_input 값을 저장하여, rerun 후에도 값을 유지하고 초기화할 수 있도록 함
if 'gongo_nums_input_value' not in st.session_state:
    st.session_state.gongo_nums_input_value = ""
# 분석이 완료되었는지 여부를 저장하는 상태 변수
if 'analysis_completed' not in st.session_state:
    st.session_state.analysis_completed = False
# 분석 결과 데이터를 저장하는 상태 변수
if 'results_by_gongo_data' not in st.session_state:
    st.session_state.results_by_gongo_data = []
if 'errors_data' not in st.session_state:
    st.session_state.errors_data = []


# 분석이 완료되지 않았을 때만 입력창과 '분석 시작' 버튼 표시
if not st.session_state.analysis_completed:
    gongo_nums_input = st.text_area("예시: \n20230123456\n20230123457\n...", 
                                    height=200, 
                                    value=st.session_state.gongo_nums_input_value, 
                                    key="gongo_input_area") # 고유 키 추가

    if st.button("분석 시작"): # 분석 시작 버튼 클릭 시
        st.session_state.gongo_nums_input_value = gongo_nums_input # 입력 값 저장
        gongo_nums = [gn.strip() for gn in gongo_nums_input.split('\n') if gn.strip()]

        if not (1 <= len(gongo_nums) <= 10):
            st.error("⚠️ 공고번호는 1개에서 10개까지만 입력 가능합니다.")
            st.session_state.analysis_completed = False # 에러 발생 시 분석 완료 상태 아님
        else:
            results_by_gongo = []
            errors = []

            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, gongo_nm in enumerate(gongo_nums):
                status_text.text(f"📊 공고번호 {gongo_nm} 분석 중... ({i+1}/{len(gongo_nums)})")
                df_result, error_msg, top_bidder_info = analyze_gongo(gongo_nm)
                
                if error_msg:
                    errors.append(error_msg)
                if not df_result.empty:
                    results_by_gongo.append({
                        "gongo_num": gongo_nm,
                        "df": df_result,
                        "top_bidder": top_bidder_info
                    })
                progress_bar.progress((i + 1) / len(gongo_nums))

            status_text.empty()
            progress_bar.empty()

            st.session_state.results_by_gongo_data = results_by_gongo # 결과 데이터 저장
            st.session_state.errors_data = errors # 에러 메시지 저장
            st.session_state.analysis_completed = True # 분석 완료 상태로 변경
            st.rerun() # 분석 완료 후 화면 업데이트를 위해 재실행
else: # analysis_completed가 True일 때 (분석 결과 화면 표시)
    results_by_gongo = st.session_state.results_by_gongo_data
    errors = st.session_state.errors_data
    gongo_nums = [res["gongo_num"] for res in results_by_gongo] # 분석된 공고 번호 목록

    st.markdown("---") 

    # --- 각 공고별 결과 분리 및 가로 배열 (기존 유지) ---
    if results_by_gongo:
        st.subheader("📈 각 공고별 사정율 분석 결과")
        
        num_cols_per_row = 2 
        
        for i in range(0, len(results_by_gongo), num_cols_per_row):
            cols = st.columns(num_cols_per_row) 
            
            for j, result_data in enumerate(results_by_gongo[i : i + num_cols_per_row]):
                with cols[j]: 
                    gongo_num = result_data["gongo_num"]
                    df = result_data["df"]
                    top_bidder = result_data["top_bidder"]

                    # 개별 테이블 상단 정보는 업체명 포함하여 기존처럼 표시
                    if top_bidder["name"] != "개찰 결과 없음":
                        st.markdown(f"**공고번호 {gongo_num}**: **{top_bidder['name']}** (사정율: **{top_bidder['rate']}%**)")
                    else:
                        st.markdown(f"**공고번호 {gongo_num}**: 개찰 결과 정보 없음")
                    
                    # --- highlight_top_bidder_individual 함수 ---
                    def highlight_top_bidder_individual(row, top_bidder_name):
                        styles = [''] * len(row)
                        # 1순위 업체 (빨간색)
                        if pd.notna(row['강조_업체명']) and row['강조_업체명'] == top_bidder_name:
                            styles = ['background-color: #ffcccc'] * len(row) # 연한 빨간색
                        # 대명포장중기 (노란색) - 1순위 업체가 아닌 경우에만 적용
                        elif pd.notna(row['강조_업체명']) and "대명포장중기" in row['강조_업체명']:
                            styles = ['background-color: #ffffcc'] * len(row) # 연한 노란색
                        return styles

                    # '강조_업체명'에는 이제 순수 업체명이 들어가므로 top_bidder['name']과 직접 비교
                    display_df_styled = df[['rate', '강조_업체명']].style.apply(
                        lambda row: highlight_top_bidder_individual(row, top_bidder['name']), axis=1
                    )

                    st.dataframe(
                        display_df_styled,
                        use_container_width=True,
                        hide_index=True,
                        height=min(35 * len(df) + 38, 400) 
                    )
                    st.markdown("---") 

        # --- 통합 사정율 분석 결과 (새로운 형식) 섹션 ---
        st.markdown("---") 
        st.subheader("📊 통합 사정율 분석 결과") 

        merged_df = pd.DataFrame()
        top_bidder_info_for_header = {} 

        if results_by_gongo:
            all_rates = pd.concat([res['df']['rate'] for res in results_by_gongo], ignore_index=True).unique()
            base_rates_df = pd.DataFrame({'rate': all_rates}).sort_values('rate').reset_index(drop=True)
            merged_df = base_rates_df
        
        # 컬럼 순서를 위한 리스트 (rate, 그리고 뒤집힌 공고번호 순서)
        ordered_gongo_nums = gongo_nums[::-1] # 입력된 공고번호 리스트를 뒤집음
        
        for gongo_num_to_process in ordered_gongo_nums:
            current_result_data = next((res for res in results_by_gongo if res['gongo_num'] == gongo_num_to_process), None)
            
            if current_result_data:
                df_current_gongo = current_result_data["df"].copy()
                top_bidder = current_result_data["top_bidder"]
                
                df_for_merge = df_current_gongo[['rate', '강조_업체명']].copy()
                df_for_merge.rename(columns={'강조_업체명': f'{gongo_num_to_process}'}, inplace=True) 
                
                merged_df = pd.merge(merged_df, df_for_merge, on='rate', how='outer')
                
                top_bidder_info_for_header[gongo_num_to_process] = top_bidder 

        if not merged_df.empty:
            final_merged_df = merged_df.sort_values(by='rate').reset_index(drop=True)
            
            final_merged_df = final_merged_df.fillna('') 

            columns_order = ['rate'] + ordered_gongo_nums
            final_merged_df = final_merged_df[columns_order]

            column_config_dict = {"rate": "Rate"} 

            for gongo_num_col in ordered_gongo_nums: 
                top_info = top_bidder_info_for_header.get(gongo_num_col, {"name": "정보 없음", "rate": "N/A"})
                
                header_text = f"{gongo_num_col}\n" 
                if top_info["name"] != "개찰 결과 없음" and top_info["rate"] != "N/A":
                    header_text += f"{top_info['rate']:.5f}%"
                else:
                    header_text += "정보 없음" 
                
                column_config_dict[gongo_num_col] = st.column_config.TextColumn(
                    label=header_text, 
                    width="small" 
                )
            
            # --- highlight_top_bidder_in_merged_table 함수 ---
            def highlight_top_bidder_in_merged_table(s, top_bidder_info_map):
                current_gongo_num_raw = s.name 
                top_info = top_bidder_info_map.get(current_gongo_num_raw) 
                
                styles = []
                for val in s:
                    style = ''
                    # 1순위 업체 (빨간색)
                    if top_info and top_info['name'] != "정보 없음" and top_info['name'] != "개찰 결과 없음" and \
                       pd.notna(val) and val == top_info['name']:
                        style = 'background-color: #ffcccc' # 연한 빨간색
                    # 대명포장중기 (노란색) - 1순위 업체가 아닌 경우에만 적용 (빨간색 우선)
                    elif pd.notna(val) and "대명포장중기" in val and \
                         not (top_info and top_info['name'] != "정보 없음" and top_info['name'] != "개찰 결과 없음" and val == top_info['name']):
                        style = 'background-color: #ffffcc' # 연한 노란색
                    styles.append(style)
                return styles 

            columns_to_style = [col for col in final_merged_df.columns if col != 'rate']

            styled_final_merged_df = final_merged_df.style.apply(
                lambda s: highlight_top_bidder_in_merged_table(s, top_bidder_info_for_header), 
                subset=columns_to_style
            )
            
            st.dataframe(
                styled_final_merged_df,
                use_container_width=True,
                hide_index=True,
                height=min(35 * len(final_merged_df) + 38, 600),
                column_config=column_config_dict 
            )
        else:
            st.info("분석할 유효한 공고번호가 없거나 데이터 병합에 실패했습니다.")


        # --- 전체 결과 다운로드 ---
        st.subheader("📥 전체 결과 다운로드")
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"통합_사정율분석_{now}.xlsx"
        
        # st.form 내부에 다운로드 버튼을 배치하여 앱 재실행 방지
        # form_key를 고유하게 설정합니다.
        with st.form(key="excel_download_form"): 
            if not final_merged_df.empty: 
                excel_buffer = io.BytesIO()
                styled_final_merged_df.to_excel(excel_buffer, index=False, engine='openpyxl') 
                excel_buffer.seek(0)
                
                st.download_button(
                    label="통합 결과 엑셀 다운로드",
                    data=excel_buffer,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_button_key" # 다운로드 버튼에도 고유 키 추가
                )
            else:
                st.info("다운로드할 통합 결과 데이터가 없습니다.")
            
            # 폼 제출 버튼이 없어도 download_button은 독립적으로 동작합니다.
            # st.form의 목적은 폼 내 다른 위젯들의 상호작용을 제출 버튼 전까지 지연시키는 것이므로,
            # 다운로드 버튼이 단독으로 있을 때에도 이 안에 있으면 재실행을 덜 유발할 수 있습니다.
            st.form_submit_button("숨겨진 제출 버튼 (클릭 불필요)", help="이 버튼은 기능에 영향을 주지 않습니다.", disabled=True) 

        # --- "처음으로" 버튼 추가 ---
        st.markdown("---")
        def reset_app():
            # 세션 상태 초기화
            st.session_state.gongo_nums_input_value = "" 
            st.session_state.analysis_completed = False
            st.session_state.results_by_gongo_data = []
            st.session_state.errors_data = []
            st.cache_data.clear() # 캐시 데이터도 초기화 (필요시)
            st.rerun() # 앱 재실행

        st.button("처음으로", on_click=reset_app) # 버튼 클릭 시 reset_app 함수 호출

    else:
        st.warning("분석할 유효한 공고번호가 없거나 모든 공고번호에서 오류가 발생했습니다.")

    if errors:
        st.subheader("⚠️ 분석 중 발생한 경고 및 오류:")
        for err in errors:
            st.write(err)
    elif not results_by_gongo and not errors and st.session_state.gongo_nums_input_value.strip():
         st.info("입력된 공고번호에 대한 분석 결과가 없습니다. 공고번호를 다시 확인해주세요.")