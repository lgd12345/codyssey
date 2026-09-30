import argparse
import json
import os
from datetime import datetime

import requests
from dotenv import load_dotenv


# Naito API 기본 설정
NAITO_URL = "https://copa.codyssey.kr/v1/chat/completions"
NAITO_MODEL = "gpt-5.5"

# Kakao Local API 기본 설정
KAKAO_LOCAL_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

# 대한민국 광역자치단체 목록
KOREA_REGIONS = (
    "서울특별시",
    "부산광역시",
    "대구광역시",
    "인천광역시",
    "광주광역시",
    "대전광역시",
    "울산광역시",
    "세종특별자치시",
    "경기도",
    "강원특별자치도",
    "충청북도",
    "충청남도",
    "전북특별자치도",
    "전라남도",
    "경상북도",
    "경상남도",
    "제주특별자치도",
)


# 입력한 날짜가 올바른 날짜인지 확인하고 YYYY-MM-DD 형식으로 정규화
def validate_date(value):
    try:
        parsed_date = datetime.strptime(value, "%Y-%m-%d")
        return parsed_date.strftime("%Y-%m-%d")

    except ValueError:
        raise argparse.ArgumentTypeError(
            "날짜는 YYYY-MM-DD 형식의 올바른 날짜여야 합니다."
        )


# CLI에서 -date 또는 --date 옵션을 받는 함수
def parse_args():
    parser = argparse.ArgumentParser(
        description="국내 여행지 추천 프로그램"
    )

    parser.add_argument(
        "-date",
        "--date",
        dest="date",
        required=True,
        type=validate_date,
        metavar="YYYY-MM-DD",
        help="여행 날짜 (예: 2026-10-15)"
    )

    return parser.parse_args()


# API 키를 .env 파일에서 불러오는 함수
def load_api_keys():
    load_dotenv()

    naito_api_key = os.getenv("NAITO_API_KEY")
    kakao_api_key = os.getenv("KAKAO_API_KEY")

    missing_keys = []

    if not naito_api_key:
        missing_keys.append("NAITO_API_KEY")

    if not kakao_api_key:
        missing_keys.append("KAKAO_API_KEY")

    # 하나라도 API 키가 없으면 API 호출 전에 프로그램 종료
    if missing_keys:
        raise SystemExit(
            "API 키가 설정되지 않았습니다.\n"
            f"누락된 키: {', '.join(missing_keys)}\n"
            ".env 파일에 해당 API 키를 설정해주세요."
        )

    return naito_api_key, kakao_api_key


# Naito API 연결
def call_naito(api_key, messages):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "model": NAITO_MODEL,
        "messages": messages
    }

    try:
        # LLM에게 데이터를 보내 결과를 생성하므로 POST 요청 사용
        response = requests.post(
            NAITO_URL,
            headers=headers,
            json=data,
            timeout=30
        )

        response.raise_for_status()

        result = response.json()

        # OpenAI 호환 응답 구조에서 실제 LLM 답변만 반환
        return result["choices"][0]["message"]["content"]

    except requests.HTTPError as error:
        status_code = error.response.status_code

        if status_code in (401, 403):
            message = f"Naito API 인증에 실패했습니다. HTTP {status_code}"
        elif status_code == 429:
            message = "Naito API 요청 한도를 초과했습니다. HTTP 429"
        else:
            message = f"Naito API 요청에 실패했습니다. HTTP {status_code}"

        raise SystemExit(message)

    except requests.RequestException as error:
        raise SystemExit(
            f"Naito API 요청에 실패했습니다: {error}"
        )

    except (KeyError, IndexError, ValueError) as error:
        raise SystemExit(
            f"Naito API 응답을 처리하지 못했습니다: {error}"
        )


# 여행 날짜를 기준으로 1차 여행 추천을 요청하는 함수
def get_travel_recommendation(api_key, date):
    messages = [
        {
            "role": "user",
            "content": f"""
입력 날짜: {date}

해당 시기에 대한민국 국내에서 여행하기 좋은 지역 1곳을 추천하세요.

반드시 아래 조건을 지켜주세요.
- 유효한 JSON 객체만 출력하세요.
- Markdown 코드블록을 사용하지 마세요.
- JSON 앞뒤에 설명 문장을 작성하지 마세요.
- recommended_city는 반드시 대한민국 국내 행정구역이어야 합니다. 시/군/구 수준의 구체적인 지역으로 작성하세요.
- weather는 해당 시기의 날씨 특징을 1~2문장 작성하세요.
- events는 해당 시기의 실제 행사 또는 축제 이름만 1~3개 작성하세요.
- reason은 추천 근거를 2~4문장으로 작성하세요.

events에는 산책, 감상, 탐방 같은 일반 여행 활동을 넣지 마세요.
해외 지역을 추천하지 마세요.

출력 형식:
{{
  "recommended_city": "string",
  "weather": "string",
  "events": ["string"],
  "reason": "string"
}}
"""
        }
    ]

    return call_naito(api_key, messages)


# 첫 번째 JSON 응답이 잘못됐을 때 1회 재요청하는 함수
def retry_travel_recommendation(api_key, date):
    messages = [
        {
            "role": "user",
            "content": f"""
입력 날짜: {date}

이전 응답은 JSON 파싱 또는 스키마 검증에 실패했습니다.

아래 4개 키만 포함한 유효한 JSON 객체를 다시 출력하세요.

- recommended_city: string
- weather: string
- events: string 배열 1~3개
- reason: string 2~4문장

추가 조건:
- JSON 객체만 출력하세요.
- Markdown 코드블록을 사용하지 마세요.
- JSON 앞뒤에 설명 문장을 작성하지 마세요.
- recommended_city: 대한민국 광역자치단체명을 포함한 시/군/구
- weather: 해당 시기의 날씨 특징을 1~2문장
- events: 해당 시기의 행사/축제 이름만 1~3개
- reason: 이 지역을 추천하는 이유 2~4문장

events에는 산책, 감상, 탐방 같은 일반 여행 활동을 넣지 마세요.
해외 지역을 추천하지 마세요.

출력 형식:
{{
  "recommended_city": "string",
  "weather": "string",
  "events": ["string"],
  "reason": "string"
}}
"""
        }
    ]

    return call_naito(api_key, messages)


# 1차 추천 JSON의 필수 키와 타입을 검사하는 함수
def validate_recommendation(data):
    # JSON 객체인지 확인
    if not isinstance(data, dict):
        return False

    required_fields = {
        "recommended_city": str,
        "weather": str,
        "events": list,
        "reason": str
    }

    # 지정한 4개 키만 있는지 확인
    if set(data.keys()) != set(required_fields.keys()):
        return False

    # 각 값의 타입 확인
    for key, expected_type in required_fields.items():
        if not isinstance(data[key], expected_type):
            return False

    # 문자열 값이 비어 있으면 실패
    if not data["recommended_city"].strip():
        return False

    if not data["weather"].strip():
        return False

    if not data["reason"].strip():
        return False

    # events는 1~3개만 허용
    if not 1 <= len(data["events"]) <= 3:
        return False

    # events 내부 값도 비어 있지 않은 문자열인지 확인
    if not all(
        isinstance(event, str) and event.strip()
        for event in data["events"]
    ):
        return False

    # 대한민국 광역자치단체인지 확인
    if not data["recommended_city"].startswith(KOREA_REGIONS):
        return False

    return True


# LLM 응답 문자열을 JSON으로 변환하고 스키마를 검증하는 함수
def parse_recommendation(text):
    try:
        data = json.loads(text)

    except json.JSONDecodeError:
        return None

    # JSON 파싱에 성공해도 필수 키나 타입이 잘못되면 실패 처리
    if not validate_recommendation(data):
        return None

    return data


# 1차 추천 생성 전체 과정을 담당하는 함수
def create_recommendation(api_key, date, errors):
    # 첫 번째 추천 요청
    recommendation_text = get_travel_recommendation(
        api_key,
        date
    )

    recommendation = parse_recommendation(
        recommendation_text
    )

    # 정상적인 JSON이면 바로 반환
    if recommendation is not None:
        return recommendation

    print("1차 추천 JSON 검증 실패 - 재시도합니다.")

    # 첫 응답이 실패하면 더 제한된 프롬프트로 딱 1회 재요청
    retry_text = retry_travel_recommendation(
        api_key,
        date
    )

    recommendation = parse_recommendation(
        retry_text
    )

    if recommendation is not None:
        return recommendation

    # 재시도까지 실패하면 errors 목록에 오류 기록
    errors.append({
        "step": "recommendation",
        "type": "JSON_PARSE_ERROR",
        "message": "LLM JSON parsing or schema validation failed after one retry"
    })

    return None


# Kakao Local API를 이용해 추천 지역의 맛집을 검색하는 함수
def search_restaurants(api_key, city, errors):
    headers = {
        "Authorization": f"KakaoAK {api_key}"
    }

    params = {
        "query": f"{city} 맛집",
        "size": 5
    }

    try:
        # 기존 장소 데이터를 조회하므로 GET 요청 사용
        response = requests.get(
            KAKAO_LOCAL_URL,
            headers=headers,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        result = response.json()
        documents = result.get("documents", [])

    except requests.HTTPError as error:
        status_code = error.response.status_code

        if status_code in (401, 403):
            error_type = "AUTH_ERROR"
        elif status_code == 429:
            error_type = "QUOTA_ERROR"
        else:
            error_type = "API_ERROR"

        errors.append({
            "step": "place_search",
            "type": error_type,
            "message": f"HTTP {status_code}"
        })

        return []

    except requests.RequestException as error:
        # Kakao API 실패 시 프로그램을 종료하지 않고 errors에 기록
        errors.append({
            "step": "place_search",
            "type": "API_ERROR",
            "message": str(error)
        })

        return []

    except ValueError as error:
        errors.append({
            "step": "place_search",
            "type": "JSON_PARSE_ERROR",
            "message": str(error)
        })

        return []

    # 검색 결과가 0건이어도 프로그램은 계속 진행
    if not documents:
        errors.append({
            "step": "place_search",
            "type": "EMPTY_RESULT",
            "message": f"0 results for query={city} 맛집"
        })

        return []

    restaurants = []

    # Kakao 응답을 프로그램에서 사용할 공통 맛집 구조로 변환
    for place in documents:
        restaurants.append({
            "name": place.get("place_name", ""),
            "address": (
                place.get("road_address_name")
                or place.get("address_name", "")
            ),
            "category": place.get("category_name", ""),
            "url": place.get("place_url", ""),
            "lng": float(place["x"]) if place.get("x") else None,
            "lat": float(place["y"]) if place.get("y") else None
        })

    return restaurants


# 같은 여행 날짜의 기존 Raw JSON이 있으면 불러오는 함수
def load_cached_data(date):
    file_path = f"results/{date}_raw.json"

    # 같은 날짜의 파일이 없으면 캐시 없음
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            cached_data = json.load(file)

        # 캐시 안의 기본 구조 확인
        recommendation = cached_data.get("recommendation")
        restaurants = cached_data.get("restaurants")
        errors = cached_data.get("errors")

        if not isinstance(recommendation, dict):
            return None

        if not validate_recommendation(recommendation):
            return None

        if not isinstance(restaurants, list):
            return None

        if not isinstance(errors, list):
            return None

        return cached_data

    # 캐시 파일이 깨져 있으면 캐시를 사용하지 않고 새로 API 호출
    except (OSError, json.JSONDecodeError):
        return None


# 1차 추천 결과, 맛집 목록, 오류 정보를 Raw JSON 파일로 저장하는 함수
def save_raw_data(date, recommendation, restaurants, errors):
    # results 폴더가 없으면 자동 생성
    os.makedirs("results", exist_ok=True)

    raw_data = {
        "recommendation": recommendation,
        "restaurants": restaurants,
        "errors": errors
    }

    file_path = f"results/{date}_raw.json"

    try:
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(
                raw_data,
                file,
                ensure_ascii=False,
                indent=2
            )

    except OSError as error:
        raise SystemExit(
            f"Raw JSON 파일 저장에 실패했습니다: {error}"
        )

    return file_path


# 추천 정보와 맛집 목록을 이용해 최종 여행 리포트를 생성하는 함수
def generate_report(api_key, date, recommendation, restaurants, errors):
    input_data = {
        "date": date,
        "recommendation": recommendation,
        "restaurants": restaurants,
        "errors": errors
    }

    messages = [
        {
            "role": "user",
            "content": f"""
다음 json 데이터를 바탕으로 국내 여행 추천 리포트를 Markdown 형식으로 작성하세요.

입력 데이터:
{json.dumps(input_data, ensure_ascii=False, indent=2)}

반드시 아래 항목을 모두 포함하세요.

# {date} 국내 여행 추천 리포트

## 추천 지역

## 추천 이유

## 날씨 요약

## 행사/축제

## 맛집 추천

## 1일 일정 제안
- 오전
- 오후
- 저녁

## 오류 요약

작성 조건:
- 입력 데이터에 있는 내용을 기반으로 작성하세요.
- 입력 데이터에 없는 여행 지역, 행사, 맛집을 새로 만들지 마세요.
- 추천 지역과 추천 이유를 명확하게 정리하세요.
- 날씨 정보를 보기 좋게 요약하세요.
- 행사/축제는 recommendation의 events에 있는 내용만 사용하세요.
- 맛집은 restaurants에 있는 이름, 주소, 카테고리를 보기 좋게 정리하세요.
- 맛집 URL이 있으면 함께 표시하세요.
- 맛집 목록이 비어 있으면 "데이터 없음"이라고 작성하세요.
- 1일 일정은 오전, 오후, 저녁 수준으로 제안하세요.
- errors가 비어 있으면 오류 요약에 "없음"이라고 작성하세요.
- Markdown 본문만 출력하세요.
- Markdown 코드블록은 사용하지 마세요.
"""
        }
    ]

    return call_naito(api_key, messages)


# 최종 여행 리포트를 Markdown 파일로 저장하는 함수
def save_report(date, report):
    os.makedirs("results", exist_ok=True)

    file_path = f"results/{date}_travel_plan.md"

    try:
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(report)

    except OSError as error:
        raise SystemExit(
            f"Markdown 리포트 저장에 실패했습니다: {error}"
        )

    return file_path


# 프로그램 전체 실행 흐름
def main():
    # CLI 입력값 읽기
    args = parse_args()

    # .env 파일에서 API 키 불러오기
    naito_api_key, kakao_api_key = load_api_keys()

    # 실행 중 발생한 오류를 저장할 목록
    errors = []

    print(f"입력한 여행 날짜: {args.date}")
    print("API 키 설정 확인 완료")

    # 같은 여행 날짜로 이전에 생성한 Raw JSON이 있는지 확인
    cached_data = load_cached_data(args.date)

    if cached_data is not None:
        # 캐시가 있으면 Naito 1차 추천과 Kakao 검색을 생략
        print("기존 결과 캐시를 발견했습니다.")

        recommendation = cached_data["recommendation"]
        restaurants = cached_data["restaurants"]
        errors = cached_data["errors"]

        print(f"추천 지역: {recommendation['recommended_city']}")
        print(f"기존 맛집 데이터 {len(restaurants)}곳 사용")

    else:
        # 1단계: LLM을 이용한 여행지 추천
        print("[1/3] 1차 추천 생성 중(LLM)...")

        recommendation = create_recommendation(
            naito_api_key,
            args.date,
            errors
        )

        # 재시도까지 실패했다면 Kakao 검색에 사용할 지역이 없으므로 종료
        if recommendation is None:
            print("1차 추천 생성에 실패했습니다.")
            print(errors)
            return

        print("1차 추천 JSON 검증 완료")
        print(f"추천 지역: {recommendation['recommended_city']}")

        # 2단계: Kakao Local API를 이용한 맛집 검색
        print("[2/3] 맛집 검색 중(Kakao Local API)...")

        restaurants = search_restaurants(
            kakao_api_key,
            recommendation["recommended_city"],
            errors
        )

        if restaurants:
            print(f"맛집 {len(restaurants)}곳 검색 완료")

            for restaurant in restaurants:
                print(f"- {restaurant['name']}")

        else:
            print("맛집 검색 결과 없음 - 다음 단계로 진행합니다.")

        # Naito 추천 + Kakao 검색 결과를 Raw JSON으로 저장
        raw_path = save_raw_data(
            args.date,
            recommendation,
            restaurants,
            errors
        )

        print(f"원본 데이터 저장 완료: {raw_path}")

    # 3단계: 추천 정보와 맛집 데이터를 이용해 최종 리포트 생성
    print("[3/3] 최종 리포트 생성 중(LLM)...")

    report = generate_report(
        naito_api_key,
        args.date,
        recommendation,
        restaurants,
        errors
    )

    # 최종 Markdown 파일 저장
    report_path = save_report(
        args.date,
        report
    )

    print("최종 리포트 생성 완료")
    print(f"완료! {report_path} 를 확인하세요.")


# 이 Python 파일을 직접 실행했을 때만 main() 실행
if __name__ == "__main__":
    main()