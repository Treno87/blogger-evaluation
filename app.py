from flask import Flask, request, jsonify
import os
import sys
import traceback
import json
import time
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime
from functools import wraps
from marshmallow import Schema, fields, validate, ValidationError

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 필수 환경 변수 정의
REQUIRED_ENV_VARS = [
    'GSHEET_CREDENTIALS_JSON',
    'API_KEY'
]

def check_env_vars():
    missing_vars = [var for var in REQUIRED_ENV_VARS if var not in os.environ]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Flask 앱 초기화
app = Flask(__name__)

# 시작 시 환경 변수 체크
check_env_vars()
logger.info("All required environment variables are present")

# 구글 API 인증 설정
def get_sheets_service():
    # API 스코프 설정
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    
    try:
        credentials_json = os.environ.get('GSHEET_CREDENTIALS_JSON')
        
        # JSON 문자열을 파이썬 딕셔너리로 변환
        service_account_info = json.loads(credentials_json)
        
        # 서비스 계정 인증 정보 생성
        creds = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=SCOPES)
        
        # Sheets API 서비스 생성
        service = build('sheets', 'v4', credentials=creds)
        logger.info("Successfully created Google Sheets service")
        return service
    except Exception as e:
        logger.error(f"Error during authentication: {str(e)}", exc_info=True)
        return None

# 포스팅 평가 함수
def evaluate_posting(posting_url):
    try:
        # 여기에 실제 평가 로직 구현
        # 예: 웹 스크래핑, 컨텐츠 분석 등
        
        # 테스트용 임시 로직 (랜덤 점수 생성)
        import random
        time.sleep(2)  # 평가 작업 시뮬레이션
        score = round(random.uniform(60, 100), 1)
        
        logger.info(f"Successfully evaluated posting: {posting_url}, score: {score}")
        return {
            'score': score,
            'success': True,
            'message': '평가 완료'
        }
    except Exception as e:
        logger.error(f"Error evaluating posting {posting_url}: {str(e)}", exc_info=True)
        return {
            'score': None,
            'success': False,
            'message': f'평가 중 오류 발생: {str(e)}'
        }

# 구글 시트 업데이트 함수
def update_spreadsheet(spreadsheet_id, sheet_name, row, results):
    try:
        service = get_sheets_service()
        
        if not service:
            logger.error("Failed to get Google Sheets service")
            return False
            
        # 최종평점 업데이트 (L열 = 12번째 열)
        range_name = f'{sheet_name}!L{row}'
        value_input_option = 'USER_ENTERED'
        
        values = [[results['score']]]
        body = {
            'values': values
        }
        
        result = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=range_name,
            valueInputOption=value_input_option, body=body).execute()
            
        logger.info(f"Successfully updated spreadsheet: {result.get('updatedCells')} cells updated")
        return True
    except Exception as e:
        logger.error(f"Error updating spreadsheet: {str(e)}", exc_info=True)
        return False

# API 키 인증 데코레이터
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key != os.environ.get('API_KEY'):
            logger.warning("Unauthorized API access attempt")
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

# 요청 검증 스키마
class PostEvaluationSchema(Schema):
    postingUrl = fields.Url(required=True, error_messages={'required': '포스팅 URL은 필수입니다.'})
    spreadsheetId = fields.Str(required=True, validate=validate.Length(min=1), error_messages={'required': '스프레드시트 ID는 필수입니다.'})
    sheetName = fields.Str(required=True, validate=validate.Length(min=1), error_messages={'required': '시트 이름은 필수입니다.'})
    row = fields.Int(required=True, validate=validate.Range(min=1), error_messages={'required': '행 번호는 필수입니다.', 'invalid': '행 번호는 1 이상이어야 합니다.'})

schema = PostEvaluationSchema()

# 웹훅 엔드포인트
@app.route('/evaluate-post', methods=['POST'])
@require_api_key
def webhook():
    try:
        # 요청 데이터 검증
        try:
            data = schema.load(request.json)
        except ValidationError as err:
            logger.error(f"Validation error: {err.messages}")
            return jsonify({"error": err.messages}), 400
        
        posting_url = data['postingUrl']
        spreadsheet_id = data['spreadsheetId']
        sheet_name = data['sheetName']
        row = data['row']
        
        logger.info(f"Processing evaluation request for posting: {posting_url}")
        
        # 포스팅 평가
        results = evaluate_posting(posting_url)
        
        # 결과가 성공적이면 구글 시트 업데이트
        if results['success']:
            update_success = update_spreadsheet(spreadsheet_id, sheet_name, row, results)
            if not update_success:
                logger.error("Failed to update spreadsheet")
                return jsonify({'error': '시트 업데이트 중 오류가 발생했습니다.'}), 500
        else:
            logger.error(f"Evaluation failed: {results['message']}")
            return jsonify({'error': results['message']}), 500
        
        logger.info(f"Successfully completed evaluation for posting: {posting_url}")
        return jsonify({'message': '평가 완료', 'score': results['score']}), 200
    
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# 구글 시트 연결 상태 확인
def check_google_sheets_connection():
    try:
        service = get_sheets_service()
        if service:
            return True
        return False
    except Exception:
        return False

# 상태 확인 엔드포인트
@app.route('/health', methods=['GET'])
def health_check():
    status = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'google_sheets_api': check_google_sheets_connection(),
        'version': os.environ.get('APP_VERSION', '1.0.0')
    }
    return jsonify(status)

# 루트 경로에 간단한 상태 확인 페이지 추가
@app.route('/', methods=['GET'])
def index():
    return "포스팅 평가 웹훅 서버가 실행 중입니다. /evaluate-post 엔드포인트로 POST 요청을 보내세요."

if __name__ == '__main__':
    # 환경 변수에서 포트 가져오기 (Heroku는 PORT 환경 변수 제공)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)