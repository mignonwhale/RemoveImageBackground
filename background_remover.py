"""
배경 제거 처리 모듈
- rembg AI 모델을 사용하여 이미지의 배경을 제거한다
- 정밀한 경계 처리를 위해 BiRefNet 계열 모델과 알파매팅(Alpha Matting) 후처리를 지원한다
- 사물 내부의 흰색/밝은 영역이 배경으로 오인되어 지워지는 문제를 막기 위해
  '테두리와 연결되지 않은 투명 구멍'을 원래 색상으로 복원하는 후처리를 지원한다
- 경계에 남는 희미한 배경 잔여물(반투명 얼룩)을 정리하는 후처리를 지원한다
- 입력: PIL Image 객체
- 출력: 배경이 제거된 PIL Image 객체 (투명 배경 PNG)
"""

import numpy as np
from PIL import Image
from rembg import remove, new_session
from scipy.ndimage import binary_fill_holes, binary_closing, generate_binary_structure

# 모델 세션을 모델 이름별로 캐싱하여 재사용한다 (반복 로딩 방지로 속도 개선)
_background_removal_session_cache = {}

# 기본 사용 모델: 사진처럼 배경이 복잡한 이미지에서도 경계 인식 정확도가 가장 높은 모델
DEFAULT_MODEL_NAME = "birefnet-general"


def get_background_removal_session(model_name: str = DEFAULT_MODEL_NAME):
    """배경 제거용 AI 모델 세션을 반환한다. 모델별로 최초 호출 시에만 로딩한다."""
    if model_name not in _background_removal_session_cache:
        _background_removal_session_cache[model_name] = new_session(model_name)
    return _background_removal_session_cache[model_name]


def fill_interior_holes(
    original_image: Image.Image,
    result_image: Image.Image,
    hole_bridging_size: int = 3,
) -> Image.Image:
    """
    배경 제거 결과에서 '사물 내부에 생긴 구멍'을 원래 색상으로 복원한다.

    이미지 테두리와 맞닿아 이어진 투명 영역은 실제 배경으로 간주하여 그대로 두고,
    테두리와 단절되어 사물 안쪽에 고립된 투명 영역(예: 흰색 달력 칸이 배경으로 오인된 경우)만
    원본 이미지의 색상으로 다시 채운다.

    내부 구멍이 아주 좁은 틈(1~수 픽셀)을 통해 바깥 배경과 살짝 이어져 있으면 '완전히 막힌 구멍'으로
    인식되지 않아 복원되지 않는 문제가 있다. 이를 막기 위해 구멍을 찾기 전에 모폴로지 닫힘(closing)
    연산으로 좁은 틈을 먼저 메운 뒤 구멍 채우기를 적용한다.

    Args:
        original_image: 배경 제거 전 원본 PIL Image 객체
        result_image: 배경 제거 후 결과 PIL Image 객체 (RGBA)
        hole_bridging_size: 좁은 틈을 메우는 정도. 값이 클수록 더 넓은 틈까지 메워서 복원하지만,
            실제 배경과 사물 사이의 좁은 틈(예: 링 사이 구멍)도 함께 메워질 위험이 커진다.

    Returns:
        내부 구멍이 복원된 PIL Image 객체 (RGBA)
    """
    result_array = np.array(result_image.convert("RGBA"))
    alpha_channel = result_array[:, :, 3]

    # 불투명 픽셀(전경)을 True로 하는 이진 마스크 생성
    foreground_mask = alpha_channel > 10

    if hole_bridging_size > 0:
        # 모폴로지 닫힘 연산(팽창 후 침식)으로 좁은 틈을 임시로 메워
        # 내부 구멍이 바깥 배경과 좁은 틈으로 이어져 있어도 '막힌 구멍'으로 인식되게 한다
        connectivity_structure = generate_binary_structure(2, 2)
        bridging_mask = binary_closing(
            foreground_mask,
            structure=connectivity_structure,
            iterations=hole_bridging_size,
        )
    else:
        bridging_mask = foreground_mask

    # 틈이 메워진 마스크를 기준으로 구멍을 채운다
    filled_mask = binary_fill_holes(bridging_mask)

    # 이번에 새로 채워진 영역(=내부 구멍 및 메워진 좁은 틈)만 추출
    newly_filled_area = filled_mask & (~foreground_mask)

    if not newly_filled_area.any():
        return result_image  # 복원할 내부 구멍이 없으면 원본 결과 그대로 반환

    original_array = np.array(original_image.convert("RGBA"))

    # 구멍 영역은 원본 이미지의 RGB 색상으로 복원하고, 알파값은 불투명(255)으로 설정
    result_array[newly_filled_area, 0:3] = original_array[newly_filled_area, 0:3]
    result_array[newly_filled_area, 3] = 255

    return Image.fromarray(result_array, mode="RGBA")


def clean_up_faint_residue(result_image: Image.Image, alpha_cleanup_threshold: int = 15) -> Image.Image:
    """
    배경 제거 경계 부근에 남아있는 희미한 반투명 배경 잔여물(얼룩)을 정리한다.

    알파값이 낮은(거의 투명에 가까운) 픽셀은 완전히 투명하게 만들어,
    미세하게 남아있는 흐릿한 배경 흔적을 깔끔하게 지운다.

    Args:
        result_image: 배경 제거 후 결과 PIL Image 객체 (RGBA)
        alpha_cleanup_threshold: 이 값 이하의 알파값을 가진 픽셀은 완전히 투명 처리한다 (0~255)

    Returns:
        잔여 얼룩이 정리된 PIL Image 객체 (RGBA)
    """
    if alpha_cleanup_threshold <= 0:
        return result_image

    result_array = np.array(result_image.convert("RGBA"))
    alpha_channel = result_array[:, :, 3]

    faint_residue_area = alpha_channel <= alpha_cleanup_threshold
    result_array[faint_residue_area, 3] = 0

    return Image.fromarray(result_array, mode="RGBA")


def remove_background_from_image(
    input_image: Image.Image,
    model_name: str = DEFAULT_MODEL_NAME,
    use_alpha_matting: bool = False,
    alpha_matting_foreground_threshold: int = 240,
    alpha_matting_background_threshold: int = 10,
    alpha_matting_erode_size: int = 5,
    fill_interior_holes_enabled: bool = True,
    hole_bridging_size: int = 3,
    alpha_cleanup_threshold: int = 8,
) -> Image.Image:
    """
    입력 이미지에서 배경을 제거하고 투명 배경(RGBA) 이미지를 반환한다.

    Args:
        input_image: 배경을 제거할 원본 PIL Image 객체
        model_name: 사용할 배경 제거 모델 이름 (기본값: birefnet-general)
        use_alpha_matting: 경계선 정밀 보정(알파매팅) 사용 여부
        alpha_matting_foreground_threshold: 전경으로 확실히 판단하는 밝기 임계값 (0~255)
        alpha_matting_background_threshold: 배경으로 확실히 판단하는 밝기 임계값 (0~255)
        alpha_matting_erode_size: 경계 침식 크기. 값이 작을수록 얇은 테두리가 덜 잘려나간다
        fill_interior_holes_enabled: 사물 내부의 오인 삭제 영역(구멍)을 복원할지 여부
        hole_bridging_size: 내부 구멍 복원 시 좁은 틈을 메우는 정도
        alpha_cleanup_threshold: 경계에 남는 희미한 배경 잔여물을 정리하는 임계값

    Returns:
        배경이 제거된 PIL Image 객체 (RGBA 모드)

    Raises:
        Exception: 모델 처리 중 오류가 발생한 경우
    """
    session = get_background_removal_session(model_name)
    result_image = remove(
        input_image,
        session=session,
        alpha_matting=use_alpha_matting,
        alpha_matting_foreground_threshold=alpha_matting_foreground_threshold,
        alpha_matting_background_threshold=alpha_matting_background_threshold,
        alpha_matting_erode_size=alpha_matting_erode_size,
    )

    if fill_interior_holes_enabled:
        result_image = fill_interior_holes(input_image, result_image, hole_bridging_size)

    result_image = clean_up_faint_residue(result_image, alpha_cleanup_threshold)

    return result_image
