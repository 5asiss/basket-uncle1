# --------------------------------------------------------------------------------
# 당근마켓 비즈프로필 소식 자동 포스팅 (Selenium)
# - 농수산물 가격 변동, 오늘의 특가 등을 매일 아침 비즈프로필 소식에 올리는 봇
# - 환경변수: DAANGN_LOGIN_PHONE, DAANGN_LOGIN_PASSWORD, DAANGN_BIZ_PROFILE_URL
# - DAANGN_TODAY_MESSAGE: 고정 메시지
# - DAANGN_USE_UTILS=1 이면 utils.get_daangn_today_message() 사용 (DAANGN_EXTRA_LINE으로 특가 문구 추가 가능)
# - 실행: python scripts/daangn_auto_post.py [메시지 텍스트]
# --------------------------------------------------------------------------------
# pyright: reportMissingImports=false
import os
import sys
import time

def main():
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        print("Selenium이 필요합니다: pip install selenium")
        sys.exit(1)

    phone = os.getenv("DAANGN_LOGIN_PHONE", "").strip()
    password = os.getenv("DAANGN_LOGIN_PASSWORD", "").strip()
    profile_url = os.getenv("DAANGN_BIZ_PROFILE_URL", "https://business.daangn.com").strip()
    message = (sys.argv[1:] and sys.argv[1]) or os.getenv("DAANGN_TODAY_MESSAGE", "").strip()
    if not message and os.getenv("DAANGN_USE_UTILS", "").strip() == "1":
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from utils import get_daangn_today_message
            extra = os.getenv("DAANGN_EXTRA_LINE", "").strip()
            message = get_daangn_today_message(extra_line=extra)
        except Exception:
            pass
    if not message:
        message = "[바구니삼촌] 오늘도 신선한 농수산으로 찾아뵙겠습니다. 문의 환영합니다."

    if not phone:
        print("DAANGN_LOGIN_PHONE 환경변수를 설정하세요.")
        sys.exit(1)

    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    if os.getenv("DAANGN_HEADLESS", "0") == "1":
        options.add_argument("--headless")

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(10)
        wait = WebDriverWait(driver, 15)

        # 1) 로그인 페이지
        login_url = "https://business.daangn.com/profile/login"
        driver.get(login_url)
        time.sleep(2)

        # 전화번호 입력 (실제 셀렉터는 당근 비즈 페이지 구조에 맞게 수정 필요)
        try:
            phone_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='tel'], input[name*='phone'], input[placeholder*='전화']")))
            phone_input.clear()
            phone_input.send_keys(phone)
        except Exception as e:
            print("전화번호 입력 필드를 찾지 못했습니다. 페이지 구조가 변경되었을 수 있습니다.", e)

        # 비밀번호가 있다면 입력 (당근은 휴대폰 인증일 수 있음)
        if password:
            try:
                pw_input = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                if pw_input:
                    pw_input[0].send_keys(password)
            except Exception:
                pass

        # 로그인 버튼 클릭
        try:
            btn = driver.find_elements(By.XPATH, "//button[contains(.,'로그인') or contains(.,'다음')]")
            if btn:
                btn[0].click()
        except Exception:
            pass

        time.sleep(3)
        # OTP 등 추가 인증이 필요하면 여기서 대기 후 수동 처리하거나, 별도 플로우 구현

        # 2) 비즈프로필 소식 페이지로 이동
        if profile_url:
            driver.get(profile_url)
        time.sleep(2)

        # 3) 소식 발행 버튼 또는 글쓰기 영역 (실제 셀렉터는 개발자도구로 확인 후 수정)
        try:
            write_btn = driver.find_elements(By.XPATH, "//a[contains(.,'소식') or contains(.,'글쓰기') or contains(.,'발행')]")
            if write_btn:
                write_btn[0].click()
            time.sleep(2)
        except Exception:
            pass

        # 4) 본문 입력
        try:
            textarea = driver.find_elements(By.CSS_SELECTOR, "textarea, [contenteditable='true']")
            if textarea:
                textarea[0].clear()
                textarea[0].send_keys(message)
                time.sleep(1)
        except Exception as e:
            print("본문 입력 요소를 찾지 못했습니다.", e)

        # 5) 발행/등록 버튼
        try:
            submit = driver.find_elements(By.XPATH, "//button[contains(.,'발행') or contains(.,'등록') or contains(.,'올리기')]")
            if submit:
                submit[0].click()
                print("소식 발행 요청을 보냈습니다.")
        except Exception:
            pass

        time.sleep(2)
        print("작업을 마쳤습니다. 브라우저를 확인하세요.")

    except Exception as e:
        print("오류:", e)
        sys.exit(1)
    finally:
        if driver and os.getenv("DAANGN_KEEP_OPEN", "0") == "1":
            input("엔터를 누르면 브라우저를 닫습니다.")
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
