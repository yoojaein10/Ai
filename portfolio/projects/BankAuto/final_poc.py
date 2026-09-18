import pyautogui
import time
import os

def final_poc():
    print("--- Start Final Research PoC ---")
    
    # 분석된 아이디 필드 좌표 (Screen Coords)
    # L997, T538, R1172, B557 -> Center: 1084, 547
    target_x, target_y = 1084, 547
    
    try:
        print(f"Clicking ID Field at ({target_x}, {target_y})...")
        pyautogui.click(target_x, target_y)
        time.sleep(1)
        
        print("Typing 'KADC_TEST_SUCCESS'...")
        # 하나씩 타이핑하여 보안 모듈 우회성 테스트
        pyautogui.typewrite('KADC_TEST_SUCCESS', interval=0.1)
        time.sleep(1)
        
        # 결과 캡처
        result_path = "D:\\AI\\Claude\\BankAuto\\final_poc_result.png"
        pyautogui.screenshot(result_path)
        print(f"PoC Result saved to: {result_path}")
        print("--- Final Research PoC Complete ---")
        
    except Exception as e:
        print(f"PoC failed: {e}")

if __name__ == "__main__":
    final_poc()
