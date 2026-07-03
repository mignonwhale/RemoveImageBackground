"""
exe 실행 진입점(런처) 스크립트
- PyInstaller로 묶인 실행 파일이 더블클릭되면 이 파일이 먼저 실행된다
- 콘솔 창 없이(--noconsole) 조용히 실행되며, 대신 로딩 화면(스플래시)을 보여준다
- Streamlit 서버가 준비되면 로딩 화면을 자동으로 닫고 브라우저를 연다
- 개발자가 아닌 사용자를 위해, 실행 중 오류가 발생하면 콘솔 대신 팝업창으로 안내한다
"""

import os
import sys
import socket
import threading
import time

# --noconsole(창 없는 모드)로 빌드되면 sys.stdout/stderr가 None이 되어,
# 내부 라이브러리가 print()를 호출할 때 프로그램이 죽을 수 있다. 미리 안전한 값으로 채워둔다.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# Streamlit 최초 실행 시 나오는 이메일 입력 안내와 사용 통계 수집을 비활성화한다.
os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
os.environ["STREAMLIT_SERVER_HEADLESS"] = "false"

STREAMLIT_SERVER_PORT = 8501


def resolve_bundled_path(relative_path: str) -> str:
    """PyInstaller로 묶인 실행 파일 내부에서도, 개발 중인 소스 코드 상태에서도 동일하게 경로를 찾는다."""
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def show_fatal_error_popup(error_message: str) -> None:
    """콘솔 창이 없는 환경에서, 치명적 오류를 사용자에게 팝업창(한글)으로 안내한다."""
    try:
        import ctypes
        MB_ICONERROR = 0x10
        ctypes.windll.user32.MessageBoxW(
            0,
            f"프로그램 실행 중 오류가 발생했습니다:\n\n{error_message}",
            "이미지 배경 제거 프로그램 - 오류",
            MB_ICONERROR,
        )
    except Exception:
        # 팝업조차 띄울 수 없는 경우(Windows가 아닌 환경 등) 콘솔에 출력만 시도한다
        print(f"[치명적 오류] {error_message}")


def wait_for_server_and_close_splash() -> None:
    """
    Streamlit 서버가 응답할 때까지 대기한 뒤, 로딩 화면(스플래시)을 닫는다.
    --splash 옵션 없이 빌드된 경우(예: 개발 중 실행)에는 아무 동작도 하지 않는다.
    """
    try:
        import pyi_splash
    except ImportError:
        return

    pyi_splash.update_text("AI 모델을 준비하고 있습니다...")

    max_wait_seconds = 180
    waited_seconds = 0
    server_is_ready = False

    while waited_seconds < max_wait_seconds:
        try:
            with socket.create_connection(("127.0.0.1", STREAMLIT_SERVER_PORT), timeout=1):
                server_is_ready = True
                break
        except OSError:
            time.sleep(1)
            waited_seconds += 1

    if server_is_ready:
        pyi_splash.update_text("브라우저를 여는 중입니다...")
        time.sleep(1)
    else:
        pyi_splash.update_text("서버 준비가 지연되고 있습니다. 잠시만 더 기다려주세요...")

    pyi_splash.close()


def main() -> None:
    """Streamlit 앱(app.py)을 실행한다."""
    app_file_path = resolve_bundled_path("app.py")

    # exe로 패키징되어 실행 중일 때만 로딩 화면 감시 스레드를 띄운다
    if getattr(sys, "frozen", False):
        watcher_thread = threading.Thread(target=wait_for_server_and_close_splash, daemon=True)
        watcher_thread.start()

    try:
        from streamlit.web import cli as streamlit_cli

        sys.argv = [
            "streamlit",
            "run",
            app_file_path,
            "--global.developmentMode=false",
            "--browser.gatherUsageStats=false",
            f"--server.port={STREAMLIT_SERVER_PORT}",
        ]
        sys.exit(streamlit_cli.main())
    except Exception as fatal_error:
        show_fatal_error_popup(str(fatal_error))
        sys.exit(1)


if __name__ == "__main__":
    main()
