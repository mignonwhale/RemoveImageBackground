"""
이미지 배경 제거 프로그램 - 메인 화면
동작 흐름: 프로그램 실행 > 이미지파일 업로드 > 배경없앤 이미지 미리보기 > 결과파일 자동 다운로드
"""

import streamlit as st
from PIL import Image

from background_remover import remove_background_from_image
from file_handler import convert_image_to_png_bytes, build_zip_file_from_results
from utils import (
    is_supported_image_file,
    build_error_message,
    build_progress_text,
    build_result_file_name,
)

# 모델별 알파매팅 필요 여부
# - birefnet 계열: 이미 정밀한 마스크를 만들기 때문에 알파매팅이 불필요 (오히려 경계를 해칠 수 있음)
# - u2net/isnet 계열: 마스크가 비교적 거칠어 알파매팅으로 경계를 다듬는 것이 도움이 됨
MODEL_ALPHA_MATTING_RECOMMENDATION = {
    "isnet-general-use": True,
    "birefnet-general": False,
    "birefnet-general-lite": False,
    "u2net": True,
    "u2netp": True,
}

MODEL_OPTIONS = list(MODEL_ALPHA_MATTING_RECOMMENDATION.keys())


def sync_alpha_matting_with_selected_model():
    """모델 선택이 바뀌면, 해당 모델에 알파매팅이 필요한지에 따라 옵션을 자동으로 켜거나 끈다."""
    selected_model = st.session_state.selected_model_name
    st.session_state.enable_alpha_matting = MODEL_ALPHA_MATTING_RECOMMENDATION.get(selected_model, True)

# 화면 기본 설정
st.set_page_config(page_title="이미지 배경 제거 프로그램", layout="wide")
st.title("🖼️ 이미지 배경 제거 프로그램")
st.caption("여러 장의 이미지를 업로드하면 배경을 자동으로 제거하고, 결과를 미리보기 후 다운로드할 수 있습니다.")

# 세션 상태 초기화 (재실행 시에도 처리 결과 유지)
if "processed_results" not in st.session_state:
    st.session_state.processed_results = []

# 업로드된 파일이 바뀌었는지 감지하기 위한 서명(파일명+크기 조합) 초기값
if "last_uploaded_file_signature" not in st.session_state:
    st.session_state.last_uploaded_file_signature = ()

# 고급 옵션 초기값 설정 (최초 1회만) - 기본 모델(birefnet-general) 기준으로 알파매팅 초기값 결정
if "selected_model_name" not in st.session_state:
    st.session_state.selected_model_name = MODEL_OPTIONS[0]
if "enable_alpha_matting" not in st.session_state:
    st.session_state.enable_alpha_matting = MODEL_ALPHA_MATTING_RECOMMENDATION[MODEL_OPTIONS[0]]

# ------------------------------------------------------------------
# 1단계: 이미지 파일 업로드
# ------------------------------------------------------------------
st.header("1. 이미지 업로드")
uploaded_files = st.file_uploader(
    "배경을 제거할 이미지를 선택하세요 (여러 장 선택 가능, 파일을 이 영역으로 끌어다 놓아도 됩니다)",
    type=["jpg", "jpeg", "png", "bmp", "webp"],
    accept_multiple_files=True,
)

# 업로드된 파일 목록(이름+크기)으로 서명을 만들어, 이전 업로드와 달라졌는지 감지한다
current_uploaded_file_signature = (
    tuple(sorted((file.name, file.size) for file in uploaded_files)) if uploaded_files else ()
)

if current_uploaded_file_signature != st.session_state.last_uploaded_file_signature:
    # 업로드 파일이 새로 추가/변경/삭제된 경우, 이전 배경 제거 결과는 더 이상 유효하지 않으므로 초기화한다
    if st.session_state.processed_results:
        st.session_state.processed_results = []
        st.info("업로드된 파일이 변경되어 이전 배경 제거 결과를 초기화했습니다.")
    st.session_state.last_uploaded_file_signature = current_uploaded_file_signature

if uploaded_files:
    st.write(f"총 **{len(uploaded_files)}개** 파일이 업로드되었습니다.")
    with st.expander("업로드된 파일 목록 보기"):
        for uploaded_file in uploaded_files:
            st.write(f"- {uploaded_file.name}")

# ------------------------------------------------------------------
# 고급 옵션: 모델 선택 및 경계선 정밀 보정(알파매팅)
# ------------------------------------------------------------------
with st.expander("⚙️ 고급 옵션 (경계선이 잘리거나 뭉개질 때 조절하세요)"):
    selected_model_name = st.selectbox(
        "배경 제거 모델",
        options=MODEL_OPTIONS,
        key="selected_model_name",
        on_change=sync_alpha_matting_with_selected_model,
        help="isnet-general-use: 일반 사물/아이콘 경계 인식에 적합\n"
             "birefnet-general: 사진처럼 배경이 복잡할 때 가장 정밀함 (기본값 권장, 처리 다소 느림)\n"
             "birefnet-general-lite: birefnet-general보다 가볍고 빠른 경량 버전\n"             
             "u2net: 범용 모델, 처리 속도 빠름\n"
             "u2netp: 경량 모델, 정확도는 낮지만 매우 빠름",
    )

    st.caption("""
    **모델 설명**
    - isnet-general-use : 일반 사물/아이콘 경계 인식에 적합
    - birefnet-general : 사진처럼 배경이 복잡할 때 가장 정밀 (기본값 권장, 처리 다소 느림)
    - birefnet-general-lite : 경량 버전
    - u2net : 범용
    - u2netp : 경량 모델, 정확도는 낮지만 매우 빠름
    """)

    alpha_matting_needed_for_model = MODEL_ALPHA_MATTING_RECOMMENDATION.get(selected_model_name, True)

    if not alpha_matting_needed_for_model:
        st.caption("ℹ️ 현재 모델은 알파매팅이 필요 없어 자동으로 꺼져 있습니다 (경계를 오히려 해칠 수 있음).")
    else:
        st.caption("ℹ️ 현재 모델은 알파매팅이 도움이 되어 자동으로 켜져 있습니다.")

    enable_alpha_matting = st.checkbox(
        "경계선 정밀 보정(알파매팅) 사용",
        key="enable_alpha_matting",
        disabled=not alpha_matting_needed_for_model,
        help="u2net/isnet처럼 비교적 거친 마스크를 정교하게 다듬을 때 유용합니다. "
             "birefnet 계열 모델은 이미 정밀한 마스크를 만들기 때문에, 알파매팅을 함께 켜면 "
             "그릇처럼 어둡고 명암 대비가 낮은 사물의 경계가 오히려 통째로 지워질 수 있어 "
             "선택할 수 없도록 자동으로 막아두었습니다.",
    )

    alpha_matting_erode_size_value = st.slider(
        "경계 침식(erode) 크기",
        min_value=0,
        max_value=30,
        value=5,
        disabled=not enable_alpha_matting,
        help="값이 작을수록 얇은 테두리가 덜 잘려나가지만, 배경 잔여물이 남을 수 있습니다.",
    )

    enable_fill_interior_holes = st.checkbox(
        "사물 내부 구멍 채우기",
        value=True,
        help="달력의 흰 칸처럼 사물 안쪽의 밝은 영역이 배경으로 오인되어 지워질 때, "
             "테두리와 연결되지 않은 투명 영역을 원래 색상으로 복원합니다.",
    )

    hole_bridging_size_value = st.slider(
        "내부 구멍 - 좁은 틈 메우기 강도",
        min_value=0,
        max_value=10,
        value=3,
        disabled=not enable_fill_interior_holes,
        help="내부 구멍이 얇은 틈으로 바깥 배경과 이어져 복원되지 않을 때 값을 높여보세요. "
             "너무 높이면 사물 내부의 실제 뚫린 부분(예: 링 구멍)까지 채워질 수 있습니다.",
    )

    alpha_cleanup_threshold_value = st.slider(
        "경계 잔여 얼룩 정리 강도",
        min_value=0,
        max_value=60,
        value=8,
        help="경계 부근에 희미하게 남는 반투명 배경 흔적을 지웁니다. "
             "값이 클수록 더 확실히 지우지만, 그릇 테두리나 머리카락처럼 명암 대비가 낮은 사물 경계도 "
             "함께 잘릴 수 있습니다. 문제가 없다면 낮게, 얼룩이 남으면 조금씩만 올려보세요.",
    )

# ------------------------------------------------------------------
# 2단계: 배경 제거 처리 실행
# ------------------------------------------------------------------
st.header("2. 배경 제거 처리")

start_processing_button = st.button("배경 제거 시작", type="primary", disabled=not uploaded_files)

if start_processing_button and uploaded_files:
    st.session_state.processed_results = []

    progress_bar = st.progress(0)
    status_text = st.empty()
    error_messages = []

    total_count = len(uploaded_files)

    for index, uploaded_file in enumerate(uploaded_files, start=1):
        status_text.info(build_progress_text(index, total_count, uploaded_file.name))

        # 지원하지 않는 파일 형식 검사
        if not is_supported_image_file(uploaded_file.name):
            error_messages.append(
                build_error_message(uploaded_file.name, "지원하지 않는 파일 형식입니다.")
            )
            progress_bar.progress(index / total_count)
            continue

        try:
            original_image = Image.open(uploaded_file).convert("RGBA")
            result_image = remove_background_from_image(
                original_image,
                model_name=selected_model_name,
                use_alpha_matting=enable_alpha_matting,
                alpha_matting_erode_size=alpha_matting_erode_size_value,
                fill_interior_holes_enabled=enable_fill_interior_holes,
                hole_bridging_size=hole_bridging_size_value,
                alpha_cleanup_threshold=alpha_cleanup_threshold_value,
            )

            st.session_state.processed_results.append(
                {
                    "original_file_name": uploaded_file.name,
                    "original_image": original_image,
                    "result_image": result_image,
                }
            )
        except Exception as processing_error:
            error_messages.append(
                build_error_message(uploaded_file.name, str(processing_error))
            )

        progress_bar.progress(index / total_count)

    status_text.empty()

    success_count = len(st.session_state.processed_results)
    fail_count = len(error_messages)

    if success_count > 0:
        st.success(f"처리 완료! 성공 {success_count}건 / 실패 {fail_count}건")
    else:
        st.error("처리에 성공한 이미지가 없습니다.")

    if error_messages:
        with st.expander(f"오류 목록 보기 ({fail_count}건)"):
            for error_message in error_messages:
                st.write(f"⚠️ {error_message}")

# ------------------------------------------------------------------
# 3단계: 결과 미리보기 (Before / After 비교)
# ------------------------------------------------------------------
if st.session_state.processed_results:
    st.header("3. 결과 미리보기")

    for result_item in st.session_state.processed_results:
        st.subheader(result_item["original_file_name"])
        preview_column_before, preview_column_after = st.columns([2, 4])

        with preview_column_before:
            st.caption("원본")
            st.image(result_item["original_image"], width=160)

        with preview_column_after:
            st.caption("배경 제거 결과")
            st.image(result_item["result_image"])

        # 개별 파일 다운로드 버튼
        result_file_name = build_result_file_name(result_item["original_file_name"])
        image_bytes = convert_image_to_png_bytes(result_item["result_image"])
        st.download_button(
            label=f"'{result_file_name}' 다운로드",
            data=image_bytes,
            file_name=result_file_name,
            mime="image/png",
            key=f"download_{result_item['original_file_name']}",
            type="primary",
        )
        st.divider()

    # ------------------------------------------------------------------
    # 4단계: 전체 결과 ZIP 일괄 다운로드
    # ------------------------------------------------------------------
    st.header("4. 전체 결과 다운로드")
    zip_file_bytes = build_zip_file_from_results(st.session_state.processed_results)
    st.download_button(
        label=f"전체 결과 ZIP으로 다운로드 ({len(st.session_state.processed_results)}건)",
        data=zip_file_bytes,
        file_name="배경제거_결과_전체.zip",
        mime="application/zip",
        type="primary",
    )
