import streamlit as st
import pandas as pd
import numpy as np
import requests
import itertools
import json
import xmltodict
from datetime import datetime

st.set_page_config(layout="wide")
st.title("🏗️ 1365 사정율 분석 도구")
st.markdown("공고번호를 입력하면 복수예가 조합, 낙찰하한율, 개찰결과를 분석해 드립니다.")

display_width = st.selectbox("📏 표 표시 너비 설정", ["자동(전체 너비)", "고정(좁게)"])
use_wide = display_width == "자동(전체 너비)"

st.subheader("🔍 분석할 공고번호를 1개에서 10개까지 입력하세요 (줄바꿈으로 구분)")
gongo_nums_input = st.text_area("예시: \n20230123456\n20230123457\n...", height=200)

@st.cache_data(ttl=3600)
def analyze_gongo(gongo_nm):
    top_bidder_info = {"name": "정보 없음", "rate": "N/A"}
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        service_key = st.secrets["SERVICE_KEY"] 


        # ▶ 복수예가 상세
        url1 = f'http://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoCnstwkPreparPcDetail?inqryDiv=2&bidNtceNo={gongo_nm}&bidNtceOrd=00&pageNo=1&numOfRows=15&type=json&ServiceKey={service_key}'
        res1 = requests.get(url1, headers=headers)
        if res1.status_code != 200:
            raise Exception(f"API 호출 실패 (복수예가): HTTP {res1.status_code}")
        data1 = json.loads(res1.text)
        if 'response' not in data1 or 'body' not in data1['response'] or 'items' not in data1['response']['body'] or not data1['response']['body']['items']:
            raise ValueError(f"복수예가 데이터 없음")
        df1 = pd.json_normalize(data1['response']['body']['items'])
        df1 = df1[['bssamt', 'bsisPlnprc']].astype('float')
        df1['SA_rate'] = df1['bsisPlnprc'] / df1['bssamt'] * 100
        base_price = df1.iloc[1]['bssamt']

        # ▶ 조합 평균 계산
        if len(df1['SA_rate']) < 4:
            raise ValueError(f"복수예가 항목이 4개 미만입니다")
        combs = itertools.combinations(df1['SA_rate'], 4)
        rates = [np.mean(c) for c in combs]
        df_rates = pd.DataFrame(rates, columns=['rate']).sort_values('rate').reset_index(drop=True)
        df_rates['조합순번'] = range(1, len(df_rates)+1)

        # ▶ 낙찰하한율 조회
        url2 = f'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk?inqryDiv=2&bidNtceNo={gongo_nm}&pageNo=1&numOfRows=10&type=json&ServiceKey={service_key}'
        res2 = requests.get(url2, headers=headers)
        if res2.status_code != 200:
            raise Exception(f"API 호출 실패 (낙찰하한율): HTTP {res2.status_code}")
        data2 = json.loads(res2.text)
        if 'response' not in data2 or 'body' not in data2['response'] or 'items' not in data2['response']['body'] or not data2['response']['body']['items']:
            raise ValueError(f"낙찰하한율 데이터 없음")
        df2 = pd.json_normalize(data2['response']['body']['items'])
        sucsfbidLwltRate = float(df2.loc[0, 'sucsfbidLwltRate'])

        # ▶ A값 계산
        url3 = f'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwkBsisAmount?inqryDiv=2&bidNtceNo={gongo_nm}&pageNo=1&numOfRows=10&type=json&ServiceKey={service_key}'
        res3 = requests.get(url3, headers=headers)
        if res3.status_code != 200:
            raise Exception(f"API 호출 실패 (A값): HTTP {res3.status_code}")
        data3 = json.loads(res3.text)
        if 'response' not in data3 or 'body' not in data3['response'] or 'items' not in data3['response']['body'] or not data3['response']['body']['items']:
            raise ValueError(f"A값 데이터 없음")
        df3 = pd.json_normalize(data3['response']['body']['items'])
        cost_cols = ['sftyMngcst','sftyChckMngcst','rtrfundNon','mrfnHealthInsrprm','npnInsrprm','odsnLngtrmrcprInsrprm','qltyMngcst']
        valid_cost_cols = [col for col in cost_cols if col in df3.columns]
        if not valid_cost_cols:
            A_value = 0
        else:
            A_value = df3[valid_cost_cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1).iloc[0]

        # ▶ 개찰결과 (여기서 맨 첫 번째 업체가 1순위)
        url4 = f'http://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoOpengCompt?serviceKey={service_key}&pageNo=1&numOfRows=999&bidNtceNo={gongo_nm}'
        res4 = requests.get(url4, headers=headers)
        if res4.status_code != 200:
            raise Exception(f"API 호출 실패 (개찰결과): HTTP {res4.status_code}")
        data4 = json.loads(json.dumps(xmltodict.parse(res4.text)))
        
        if 'response' not in data4 or 'body' not in data4['response'] or 'items' not in data4['response']['body'] or 'item' not in data4['response']['body']['items']:
            df4 = pd.DataFrame()
        else:
            items = data4['response']['body']['items']['item']
            if not isinstance(items, list):
                items = [items]
            df4 = pd.DataFrame(items)
            df4['bidprcAmt'] = pd.to_numeric(df4['bidprcAmt'], errors='coerce')
            df4 = df4.dropna(subset=['bidprcAmt'])

        if not df4.empty:
            top_bidder_name = df4.iloc[0]['prcbdrNm']
            
            if sucsfbidLwltRate != 0 and base_price != 0:
                df4['rate'] = (((df4['bidprcAmt'] - A_value) * 100 / sucsfbidLwltRate) + A_value) * 100 / base_price
            else:
                df4['rate'] = np.nan

            df4 = df4.drop_duplicates(subset=['rate']).copy()
            df4 = df4[(df4['rate'] >= 90) & (df4['rate'] <= 110)].copy()
            df4 = df4[['prcbdrNm', 'rate']].rename(columns={'prcbdrNm': '업체명'})

            top_bidder_rate_row = df4[df4['업체명'] == top_bidder_name]
            if not top_bidder_rate_row.empty:
                top_bidder_info = {
                    "name": top_bidder_name,
                    "rate": round(top_bidder_rate_row.iloc[0]['rate'], 5)
                }
            else:
                 top_bidder_info = {"name": top_bidder_name, "rate": "범위 외"}
        else:
            top_bidder_info = {"name": "개찰 결과 없음", "rate": "N/A"}

        df_combined_gongo = pd.concat([
            df_rates[['rate']].assign(업체명=df_rates['조합순번'].astype(str)), 
            df4.rename(columns={'업체명': '업체명'})
        ], ignore_index=True).sort_values('rate').reset_index(drop=True)
        df_combined_gongo['rate'] = round(df_combined_gongo['rate'], 5)
        
        df_combined_gongo['공고번호'] = gongo_nm 

        df_combined_gongo['강조_업체명'] = df_combined_gongo['업체명'].apply(
            lambda x: f"🏆 **{x}**" if x == top_bidder_info['name'] else x
        )
        
        return df_combined_gongo, None, top_bidder_info 

    except ValueError as ve:
        return pd.DataFrame(), f"⚠️ 경고: 공고번호 {gongo_nm} - {ve}", top_bidder_info
    except Exception as e:
        return pd.DataFrame(), f"❌ 오류 발생: 공고번호 {gongo_nm} - {e}", top_bidder_info

if st.button("분석 시작") and gongo_nums_input:
    gongo_nums = [gn.strip() for gn in gongo_nums_input.split('\n') if gn.strip()]

    if not (1 <= len(gongo_nums) <= 10):
        st.error("⚠️ 공고번호는 1개에서 10개까지만 입력 가능합니다.")
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

                        if top_bidder["name"] != "개찰 결과 없음":
                            st.markdown(f"**공고번호 {gongo_num}**: **{top_bidder['name']}** (사정율: **{top_bidder['rate']}%**)")
                        else:
                            st.markdown(f"**공고번호 {gongo_num}**: 개찰 결과 정보 없음")
                        
                        def highlight_top_bidder(row):
                            color = 'background-color: yellow'
                            if '🏆' in str(row['강조_업체명']):
                                return [color] * len(row)
                            return [''] * len(row)

                        display_df_styled = df[['rate', '강조_업체명']].style.apply(highlight_top_bidder, axis=1)

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
            top_bidder_info_for_header = {} # 컬럼 헤더 위에 표시할 1순위 정보 저장

            # 초기 'rate' 컬럼을 위한 DataFrame 생성
            if results_by_gongo:
                # 첫 번째 공고의 rate만 가져와서 병합의 시작점으로 사용
                # 모든 가능한 rate 값을 포함하기 위해 모든 df에서 rate를 추출 후 unique 값 사용
                all_rates = pd.concat([res['df']['rate'] for res in results_by_gongo], ignore_index=True).unique()
                base_rates_df = pd.DataFrame({'rate': all_rates}).sort_values('rate').reset_index(drop=True)
                merged_df = base_rates_df
            
            # 각 공고별 데이터를 merged_df에 병합
            for i, result_data in enumerate(results_by_gongo):
                gongo_num = result_data["gongo_num"]
                df_current_gongo = result_data["df"].copy()
                top_bidder = result_data["top_bidder"]
                
                df_for_merge = df_current_gongo[['rate', '강조_업체명']].copy()
                # 컬럼 이름 변경: '강조_업체명' -> '공고번호_업체명' (이 컬럼명이 실제 테이블 헤더가 됨)
                df_for_merge.rename(columns={'강조_업체명': f'공고번호 {gongo_num}'}, inplace=True)
                
                # 'rate' 기준으로 외부 조인 (outer join)하여 모든 rate 값을 유지
                merged_df = pd.merge(merged_df, df_for_merge, on='rate', how='outer')
                
                # 컬럼 헤더 위에 표시할 1순위 정보 저장
                top_bidder_info_for_header[f'공고번호 {gongo_num}'] = top_bidder

            # 최종 통합 DataFrame 정렬 (rate 기준)
            if not merged_df.empty: # merged_df가 비어있지 않은 경우에만 처리
                final_merged_df = merged_df.sort_values(by='rate').reset_index(drop=True)
                
                # 컬럼 헤더 (1순위 업체 정보) 표시
                # Rate 컬럼 + 각 공고번호 컬럼 수만큼 할당
                header_cols_widths = [1] + [1] * len(gongo_nums)
                header_cols = st.columns(header_cols_widths)
                
                with header_cols[0]:
                    st.markdown("<div style='text-align: center; font-weight: bold;'>Rate</div>", unsafe_allow_html=True) 
                
                for idx, gongo_num_str in enumerate(gongo_nums):
                    col_key = f'공고번호 {gongo_num_str}'
                    with header_cols[idx + 1]: 
                        top_info = top_bidder_info_for_header.get(col_key, {"name": "정보 없음", "rate": "N/A"})
                        
                        # 1순위 업체명과 사정율을 함께 표시 (새로운 요청)
                        if top_info["name"] != "개찰 결과 없음":
                            st.markdown(
                                f"<div style='text-align: center; font-size: 14px;'>"
                                f"**{top_info['name']}**<br>"
                                f"(사정율: **{top_info['rate']:.5f}%**)" # 사정율 소수점 5자리까지 표시
                                f"</div>",
                                unsafe_allow_html=True
                            )
                        else:
                            st.markdown(f"<div style='text-align: center; font-size: 14px;'>개찰 결과 없음</div>", unsafe_allow_html=True)
                        
                        # 공고번호 자체를 bold 처리
                        st.markdown(f"<div style='text-align: center; font-weight: bold;'>{gongo_num_str}</div>", unsafe_allow_html=True) 
                
                # Styler 함수 (통합 테이블용)
                # 이제 '강조_업체명' 대신 각 '공고번호 XXX' 컬럼의 값에서 순수 업체명을 추출하여 비교
                def highlight_top_bidder_in_merged_table(val, top_bidder_name_raw):
                    # val이 NaN이 아닐 때만 처리
                    if pd.notna(val) and isinstance(val, str):
                        # val에서 '🏆 **'와 '**'를 제거하여 순수 업체명만 추출
                        clean_val = val.replace('🏆 **', '').replace('**', '').strip()
                        if clean_val == top_bidder_name_raw:
                            return 'background-color: yellow'
                    return ''

                styled_final_merged_df = final_merged_df.style
                for col_name, top_info in top_bidder_info_for_header.items():
                    top_bidder_name_raw = top_info['name'] # 강조 이모지가 없는 순수 업체명
                    if top_bidder_name_raw != "정보 없음" and top_bidder_name_raw != "개찰 결과 없음":
                        styled_final_merged_df = styled_final_merged_df.applymap(
                            lambda x: highlight_top_bidder_in_merged_table(x, top_bidder_name_raw),
                            subset=[col_name]
                        )
                
                st.dataframe(
                    styled_final_merged_df,
                    use_container_width=True,
                    hide_index=True,
                    height=min(35 * len(final_merged_df) + 38, 600)
                )
            else:
                st.info("분석할 유효한 공고번호가 없거나 데이터 병합에 실패했습니다.")


            # --- 전체 결과 다운로드 (기존 유지) ---
            st.subheader("📥 전체 결과 다운로드")
            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"통합_사정율분석_{now}.xlsx"
            
            all_results_df_for_download = pd.concat([res["df"] for res in results_by_gongo], ignore_index=True)
            download_df = all_results_df_for_download.copy()
            download_df['업체명'] = download_df['강조_업체명'].str.replace('🏆 ', '').str.replace('**', '') 
            download_df = download_df[['공고번호', 'rate', '업체명']] 
            download_df.to_excel(filename, index=False)
            with open(filename, "rb") as f:
                st.download_button("엑셀 다운로드", f, file_name=filename)

        else:
            st.warning("분석할 유효한 공고번호가 없거나 모든 공고번호에서 오류가 발생했습니다.")

        if errors:
            st.subheader("⚠️ 분석 중 발생한 경고 및 오류:")
            for err in errors:
                st.write(err)
        elif not results_by_gongo and not errors and gongo_nums_input.strip():
             st.info("입력된 공고번호에 대한 분석 결과가 없습니다. 공고번호를 다시 확인해주세요.")