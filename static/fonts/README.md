# 한글 폰트 (이미지 다운로드용)

**배송집계·조회결과상세·판매상품명별 총합계·발주서** 이미지 다운로드 시 한글이 정상 표시되려면 한글 지원 폰트가 필요합니다.

## 자동 설치 (서버 포함)

- 서버에 한글 폰트가 없으면 **첫 이미지 생성 시** 이 폴더(`static/fonts/`)에 **나눔고딕**이 자동으로 다운로드됩니다. 별도 설정 없이 한글이 표시됩니다.
- (네트워크가 차단된 환경이면 아래 방법 1로 수동으로 넣어 주세요.)

## 방법 1: 이 폴더에 폰트 넣기 (권장, 수동)

- 이 폴더(`static/fonts/`)에 **아무 한글 TrueType 폰트**나 넣으면 자동으로 사용됩니다.
- **권장 파일**: `NanumGothic.ttf`  
  - 나눔고딕(무료): https://hangeul.naver.com/2017/nanum
- Windows에서 사용 중인 `malgun.ttf`를 복사해 `malgun.ttf`로 저장해도 됩니다.
- 지원 확장자: `.ttf`, `.ttc`, `.otf`

파일을 넣은 뒤 서버를 재시작하면 이미지 다운로드 시 한글이 정상 표시됩니다.

## 방법 2: Linux 서버 (시스템 폰트)

- **fontconfig**가 있으면 시스템에 설치된 한글 폰트를 자동으로 찾습니다.  
  예: `sudo apt install fonts-nanum` (Ubuntu/Debian)  
  또는 Noto CJK: `sudo apt install fonts-noto-cjk`
- 폰트 설치 후 `fc-list :lang=ko` 로 한글 폰트가 나오면 이미지 생성 시 사용됩니다.
