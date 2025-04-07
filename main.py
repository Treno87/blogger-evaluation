import requests
from bs4 import BeautifulSoup
import os
import json
from dotenv import load_dotenv
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from anthropic import Anthropic
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Google Sheets 연동 설정 (open_by_key 사용)
def connect_to_sheet_by_id():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(os.getenv("GSHEET_CREDENTIALS_JSON"), scope)
    client_gspread = gspread.authorize(creds)
    spreadsheet_id = os.getenv("GSHEET_SPREADSHEET_ID")
    sheet = client_gspread.open_by_key(spreadsheet_id).worksheet("Dashboard")
    return sheet

# 1. 블로그 제목 추출 함수
def extract_naver_blog_title(blog_url):
    # 모바일 URL을 PC URL로 변환
    if 'm.blog.naver.com' in blog_url:
        blog_url = blog_url.replace('m.blog.naver.com', 'blog.naver.com')
        
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(blog_url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    # 1. og:title 메타태그 우선 시도
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    # 2. iframe 방식 대응
    iframe = soup.find("iframe")
    if iframe and "src" in iframe.attrs:
        real_url = "https://blog.naver.com" + iframe["src"]
        res = requests.get(real_url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()

    # 3. fallback: <title> 태그
    return soup.title.string.strip() if soup.title else None

# 2. Claude로 메인/서브 키워드 추출
def extract_keywords_from_title(title):
    # 지역명 JSON 구조
    region_keywords = {
        "강남구": {
            "priority": 1,
            "keywords": ["강남", "강남역", "삼성", "삼성역", "역삼", "역삼역", "논현", "논현역", "청담", "청담동", "청담역", "신사", "신사역", "가로수길", "압구정", "압구정역", "대치", "대치역"],
            "synonyms": {
                "강남역": ["강남역사거리"],
                "압구정": ["압구정동", "압구정로데오"],
                "신사": ["신사동"],
                "논현": ["논현동"],
                "청담": ["청담동"],
                "역삼": ["역삼동"]
            }
        },
        "서초구": {
            "priority": 2,
            "keywords": ["서초", "서초역", "교대", "교대역", "방배", "방배역", "잠원", "잠원역", "반포", "반포역"],
            "synonyms": {
                "서초": ["서초동"],
                "교대": ["교대역사거리"],
                "방배": ["방배동"],
                "잠원": ["잠원동"],
                "반포": ["반포동"]
            }
        },
        "송파구": {
            "priority": 3,
            "keywords": ["잠실", "잠실역", "석촌", "석촌역", "송파", "송파역", "방이", "방이동", "방이역"],
            "synonyms": {
                "잠실": ["잠실동"],
                "석촌": ["석촌동"],
                "송파": ["송파동"],
                "방이": ["방이동"]
            }
        },
        "성동구": {
            "priority": 4,
            "keywords": ["성수", "성수역", "뚝섬", "뚝섬역"],
            "synonyms": {
                "성수": ["성수동"],
                "뚝섬": ["뚝섬유원지"]
            }
        },
        "영등포구": {
            "priority": 5,
            "keywords": ["여의도", "여의도역", "영등포", "영등포역", "당산", "당산역"],
            "synonyms": {
                "여의도": ["여의도동"],
                "영등포": ["영등포동"],
                "당산": ["당산동"]
            }
        },
        "마포구": {
            "priority": 6,
            "keywords": ["홍대", "홍대입구", "홍대입구역", "상수", "상수역", "합정", "합정역", "아현", "아현역", "대흥", "대흥역", "마포", "마포역", "망원", "망원역"],
            "synonyms": {
                "홍대": ["홍대입구", "홍대거리"],
                "상수": ["상수동"],
                "합정": ["합정동"],
                "아현": ["아현동"],
                "대흥": ["대흥동"],
                "마포": ["마포동"],
                "망원": ["망원동"]
            }
        },
        "종로구": {
            "priority": 7,
            "keywords": ["종로", "종로역", "명동", "명동역", "동대문", "동대문역", "광화문", "광화문역", "을지로", "을지로입구역", "을지로3가역", "을지로4가역", "남대문", "충무로", "충무로역"],
            "synonyms": {
                "종로": ["종로구"],
                "명동": ["명동거리"],
                "동대문": ["동대문역사문화공원"],
                "광화문": ["광화문광장"],
                "을지로": ["을지로입구"]
            }
        },
        "서대문구": {
            "priority": 8,
            "keywords": ["신촌", "신촌역", "이대", "이대역"],
            "synonyms": {
                "신촌": ["신촌거리"],
                "이대": ["이화여대"]
            }
        },
        "용산구": {
            "priority": 9,
            "keywords": ["한남", "이태원", "이태원역", "경리단길"],
            "synonyms": {
                "한남": ["한남동"],
                "이태원": ["이태원동"]
            }
        },
        "성북구": {
            "priority": 10,
            "keywords": ["왕십리", "왕십리역", "상왕십리", "상왕십리역", "신당", "신당역", "한양대", "한양대역", "회기", "회기역", "청량리", "청량리역"],
            "synonyms": {
                "왕십리": ["왕십리역사거리"],
                "상왕십리": ["상왕십리역사거리"],
                "신당": ["신당동"],
                "한양대": ["한양대학교"],
                "회기": ["회기역사거리"],
                "청량리": ["청량리역사거리"]
            }
        },
        "노원구": {
            "priority": 11,
            "keywords": ["노원", "노원역", "미아사거리", "미아사거리역", "태릉입구", "태릉입구역"],
            "synonyms": {
                "노원": ["노원구"],
                "미아사거리": ["미아역사거리"],
                "태릉입구": ["태릉입구역사거리"]
            }
        },
        "금호": {
            "priority": 12,
            "keywords": ["금호", "금호역"],
            "synonyms": {
                "금호": ["금호동"]
            }
        },
        "양천구": {
            "priority": 13,
            "keywords": ["목동", "목동역"],
            "synonyms": {
                "목동": ["목동구"]
            }
        },
        "마곡": {
            "priority": 14,
            "keywords": ["상암", "상암역", "화곡", "화곡역", "마곡", "마곡역"],
            "synonyms": {
                "상암": ["상암동"],
                "화곡": ["화곡동"],
                "마곡": ["마곡동"]
            }
        },
        "관악구": {
            "priority": 15,
            "keywords": ["서울대입구", "서울대입구역", "사당", "사당역"],
            "synonyms": {
                "서울대입구": ["서울대학교입구"],
                "사당": ["사당동"]
            }
        }
    }
    
    # 제목에서 지역명 추출
    found_region = None
    for region_group in region_keywords.values():
        for region in region_group["keywords"]:
            if region in title:
                found_region = region
                # 동의어가 있는지 확인
                if region in region_group["synonyms"]:
                    for synonym in region_group["synonyms"][region]:
                        if synonym in title:
                            found_region = synonym
                            break
                break
        if found_region:
            break

    prompt = f"""
    너는 네이버 블로그 SEO 키워드 전문가야.

    아래 블로그 제목을 분석해서,
    - 메인 키워드 1개, 메인 키워드는 지역명 + 메인키워드
    - 서브 키워드 3~5개 (브랜드명 제외)
    - 서브 키워드 각각에 지역명을 조합한 키워드 (지역명이 있는 경우에만)

    를 JSON 형식으로 추출해줘.
    
    제목: "{title}"

    {f'지역명: "{found_region}"' if found_region else '지역명: 없음'}
    
    키워드 규칙
    - 메인 키워드는 지역명 + 시술명 조합으로 해줘. '미용실'은 키워드에서 제외.
    - 지역명은 반드시 "~역" 또는 "~동" 형식으로 써. 예를 들어 "강남"이면 "강남역"으로 써. 
    - 모든 키워드에서 브랜드명 제외, 일반적인 단어, 불필요한 수식어, 뜻을 알 수 없는 단어, 무의미한 단어, 특수문자나 이모지 제외
    - 키워드는 제공한 {title}에 포함된 단어와 단어들의 조합으로 만들어. 
    - 키워드는 서술어만 있으면 안돼. 예를 들어 '깔끔한'은 키워드가 될 수 없음.  
    - 키워드는 완결된 형태로 해. 예를 들어 '깔끔한 남자머리'처럼 완결된 형태로 해. 
    - 네이버SEO에 최적화된 키워드를 추출해줘.
    - 메인 키워드와 서브키워드는 중복되지 않게 해.
    - 디자이너, 디자이너 바로 앞,뒤 단어, 미용실, 추천, 후기 제외
    - 키워드를 추출하고 난 뒤 최종적으로 뜻을 알 수 없는 단어가 있으면 제외해
    
    
    형식 예시:
    {{
        "main_keyword": "키워드",
        "sub_keywords": ["키워드1", "키워드2", "키워드3"],
        "sub_keywords_with_region": ["지역명 키워드1", "지역명 키워드2", "지역명 키워드3"]
    }}

    참고: {f'제목에서 추출된 지역명은 "{found_region}"입니다. 이 지역명을 사용하여 키워드를 생성해주세요.' if found_region else '제목에서 지역명을 찾을 수 없습니다. 지역명을 포함하지 않은 키워드만 생성해주세요.'}
    """

    response = client.messages.create(
        model="claude-3-7-sonnet-20250219",
        max_tokens=1000,
        system="너는 마케팅 키워드 전문가야. JSON 형식으로만 응답해줘.",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    result_text = response.content[0].text
    
    # 마크다운 코드 블록 제거
    result_text = result_text.replace("```json", "").replace("```", "").strip()
    
    try:
        return json.loads(result_text)
    except json.JSONDecodeError as e:
        print(f"JSON 파싱 실패: {e}")
        print(f"원본 텍스트: {result_text}")
        return None

# 3. 네이버 검색에서 블로그 순위 확인 (Selenium)
def get_post_rank(keyword, target_url):
    try:
        # 모바일 URL을 PC URL로 변환
        if 'm.blog.naver.com' in target_url:
            target_url = target_url.replace('m.blog.naver.com', 'blog.naver.com')
            
        # Chrome 옵션 설정
        chrome_options = Options()
        chrome_options.add_argument('--headless')  # 헤드리스 모드
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        # 프로젝트 폴더의 chromedriver.exe 사용
        service = Service('./chromedriver.exe')
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # 네이버 블로그 검색
        search_url = f"https://search.naver.com/search.naver?where=blog&query={keyword}"
        driver.get(search_url)
        time.sleep(2)  # 페이지 로딩 대기
        
        # 검색 결과에서 URL 추출 (여러 CSS 선택자 시도)
        post_elements = []
        selectors = [
            'a.api_txt_lines.total_tit',  # 기본 선택자
            'a.title_link',  # 대체 선택자
            'a[class*="title"]',  # title이 포함된 클래스
            'a[href*="blog.naver.com"]'  # 네이버 블로그 링크
        ]
        
        for selector in selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                post_elements = elements
                print(f"검색 결과를 찾았습니다 (선택자: {selector})")
                break
        
        if not post_elements:
            print(f"검색 결과를 찾을 수 없습니다. 페이지 소스:")
            print(driver.page_source)
            driver.quit()
            return None
            
        print(f"검색된 결과 수: {len(post_elements)}")
        
        for rank, element in enumerate(post_elements, 1):
            post_url = element.get_attribute('href')
            print(f"검색 결과 {rank}위 URL: {post_url}")
            
            # URL 정규화
            target_url_clean = target_url.split('?')[0]  # 쿼리 파라미터 제거
            post_url_clean = post_url.split('?')[0]  # 쿼리 파라미터 제거
            
            # URL 비교
            if target_url_clean in post_url_clean:  # URL 포함 여부로 비교
                print(f"URL 매칭 성공:")
                print(f"  - 키워드: {keyword}")
                print(f"  - 타겟 URL: {target_url_clean}")
                print(f"  - 검색된 URL: {post_url_clean}")
                print(f"  - 순위: {rank}위")
                driver.quit()
                return rank
        
        print(f"URL 매칭 실패:")
        print(f"  - 키워드: {keyword}")
        print(f"  - 타겟 URL: {target_url}")
        print(f"  - 상위 5개 검색 결과:")
        for i, p in enumerate(post_elements[:5]):
            print(f"    {i+1}. {p.get_attribute('href')}")
        
        driver.quit()
        return None  # 노출되지 않음
        
    except Exception as e:
        print(f"키워드 '{keyword}' 검색 중 오류 발생: {str(e)}")
        return None

# 4. 전체 실행 흐름 + Google Sheets 저장 (모든 시트 행 반복 처리)
def analyze_all_blog_posts(sheet):
    # ChromeDriver 설정을 한 번만 수행
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    service = Service('./chromedriver.exe')
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # 실제 데이터가 있는 행만 가져오기
        all_rows = sheet.get_all_records()
        rows_to_process = 0
        
        for i, row in enumerate(all_rows, start=2):
            # E열의 URL 확인
            blog_url = sheet.cell(i, 5).value  # E열은 5번째 열
            if not blog_url:  # URL이 없는 행은 건너뛰기
                continue

            # L열(12번째 열)의 최종평점 확인 (이전 K열)
            final_score = sheet.cell(i, 12).value
            if final_score:  # 값이 있으면 (N/A 포함) 건너뛰기
                print(f"[{i}] 이미 최종평점 있음 ({final_score}) → 건너뜀")
                continue

            rows_to_process += 1
            print(f"\n[{i}] 처리 대상 발견 → 블로그 URL: {blog_url}")

            title = extract_naver_blog_title(blog_url)
            if not title:
                print(f"[{i}] 제목 추출 실패")
                continue

            print(f"[{i}] 제목: {title}")  # 제목 출력 추가

            keywords = extract_keywords_from_title(title)
            if not keywords:
                print(f"[{i}] 키워드 추출 실패")
                continue

            main_keyword = keywords['main_keyword']
            sub_keywords = keywords['sub_keywords']
            sub_keywords_with_region = keywords['sub_keywords_with_region']

            print(f"\n[{i}] 추출된 키워드:")
            print(f"  - 메인 키워드: {main_keyword}")
            print(f"  - 서브 키워드: {', '.join(sub_keywords)}")
            print(f"  - 지역 포함 서브 키워드: {', '.join(sub_keywords_with_region)}")

            print(f"\n[{i}] 키워드 순위 확인 시작:")
            main_rank = get_post_rank(main_keyword, blog_url)
            print(f"[{i}] 메인 키워드 '{main_keyword}' 순위: {main_rank if main_rank else '노출 안됨'}")

            # 서브 키워드 순위 확인
            sub_ranks = []
            ranked_keywords = []
            non_ranked_keywords = []
            print(f"[{i}] 서브 키워드 순위 확인:")
            
            # 일반 서브 키워드 순위 확인
            print(f"  [일반 서브 키워드]")
            for kw in sub_keywords:
                r = get_post_rank(kw, blog_url)
                print(f"  - '{kw}': {r if r else '노출 안됨'}")
                if r:
                    ranked_keywords.append((kw, r))
                    sub_ranks.append(r)
                else:
                    non_ranked_keywords.append(kw)

            # 지역 포함 서브 키워드 순위 확인
            print(f"  [지역 포함 서브 키워드]")
            for kw in sub_keywords_with_region:
                r = get_post_rank(kw, blog_url)
                print(f"  - '{kw}': {r if r else '노출 안됨'}")
                if r:
                    ranked_keywords.append((kw, r))
                    sub_ranks.append(r)
                else:
                    non_ranked_keywords.append(kw)

            # 노출된 키워드의 평균 순위 계산 (노출된 키워드만 고려)
            avg_sub_rank = None
            if sub_ranks:  # 노출된 키워드가 있는 경우에만 평균 계산
                avg_sub_rank = sum(sub_ranks) / len(sub_ranks)
                print(f"[{i}] 서브 키워드 평균 순위: {round(avg_sub_rank, 1)} ({len(sub_ranks)}개 노출 키워드 평균)")
            else:
                print(f"[{i}] 노출된 서브 키워드가 없습니다.")

            # 메인 키워드가 노출되지 않더라도 점수 계산
            if main_rank:
                main_score = (30 - main_rank) / 30 * 40
            else:
                main_score = 0  # 메인 키워드가 노출되지 않으면 0점

            # 노출된 서브 키워드가 없으면 0점, 있으면 평균 순위로 점수 계산
            if avg_sub_rank:
                sub_score = (30 - avg_sub_rank) / 30 * 60
            else:
                sub_score = 0

            score = round(main_score + sub_score, 2)

            # Google Sheets 업데이트 (올바른 범위 지정)
            sheet.update_cell(i, 7, title)  # G열 (이전 F열)
            sheet.update_cell(i, 8, main_keyword)  # H열 (이전 G열)
            sheet.update_cell(i, 9, main_rank if main_rank else "노출 안됨")  # I열 (이전 H열)
            
            # 순위가 있는 키워드를 순위 기준으로 정렬 (낮은 순위가 앞으로)
            ranked_keywords.sort(key=lambda x: x[1])
            # 키워드와 순위를 함께 표시 (예: "키워드(1)")
            sorted_ranked_keywords = [f"{kw}({rank})" for kw, rank in ranked_keywords]

            # 순위가 있는 키워드와 없는 키워드를 "/"로 구분하여 합치기
            if sorted_ranked_keywords and non_ranked_keywords:
                all_sub_keywords = ", ".join(sorted_ranked_keywords) + " / " + ", ".join(non_ranked_keywords)
            elif sorted_ranked_keywords:
                all_sub_keywords = ", ".join(sorted_ranked_keywords)
            else:
                all_sub_keywords = ", ".join(non_ranked_keywords)
                
            sheet.update_cell(i, 10, all_sub_keywords)  # J열 (이전 I열)
            
            # 평균 순위에 노출된 키워드 수 표시 (예: "2.5(4개 평균)")
            if avg_sub_rank:
                avg_sub_rank_display = f"{round(avg_sub_rank, 1)}({len(sub_ranks)}개 평균)"
            else:
                avg_sub_rank_display = "노출 안됨"
                
            sheet.update_cell(i, 11, avg_sub_rank_display)  # K열 (이전 J열)
            sheet.update_cell(i, 12, score)  # L열 (이전 K열)

            print(f"[{i}] 완료 - 메인:{main_rank}, 서브평균:{avg_sub_rank_display if avg_sub_rank else '노출 안됨'}, 점수:{score}")

            # 5초 대기
            time.sleep(5)

        if rows_to_process == 0:
            print("\n분석할 행이 없습니다. 모든 행이 이미 분석되었거나 URL이 없습니다.")

    finally:
        # ChromeDriver 종료
        driver.quit()

if __name__ == "__main__":
    sheet = connect_to_sheet_by_id()
    analyze_all_blog_posts(sheet)
