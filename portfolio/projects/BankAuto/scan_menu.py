import pyautogui
import time
import warnings
warnings.filterwarnings('ignore')

print("진행중: 3초 대기...")
time.sleep(3)

print("진행중: 우클릭...")
pyautogui.rightClick(960, 582)
time.sleep(1.5)

print("진행중: 스크린샷 저장...")
pyautogui.screenshot('D:/AI/Claude/BankAuto/menu_capture.png')

print("진행중: ESC 닫기...")
pyautogui.press('escape')
print("완료: menu_capture.png 저장됨")
