"""Collect one verified KAMIS retail series, preserving monthly source responses."""

from __future__ import annotations

import argparse
import calendar
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
DEFAULT_START = date(2023, 1, 1)
DEFAULT_END = date(2025, 12, 31)
PAGE_URL = "https://www.kamis.or.kr/customer/price/agricultureRetail/period.do"
CHART_URL = PAGE_URL + "?action=dailyChartByAjax&rank=1"
CONDITIONS = {
    "countycode": "1101",  # Seoul; verified against Busan and all-region responses.
    "itemcategorycode": "200",
    "itemcode": "226",
    "kindcode": "00",
    "productrankcode": "1",  # Website rank, not Open API grade code 04.
    "convert_kg_yn": "N",
    "marketclscode": "",
    "marketcode": "",
    "kindcode_all_yn": "N",
}
LABELS = {
    "item": "딸기", "region": "서울", "variety": "설향", "grade": "상품",
    "unit": "원/500g", "aggregation": "KAMIS 제공 평균(전통시장·유통업체)",
}
FIELDS = ["date", "price", *LABELS, "source_file"]


def write_text(path: Path, value: str) -> None:
    """Replace generated outputs atomically inside the project."""
    path = path.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("출력 경로는 프로젝트 폴더 내부여야 합니다.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="")
    temporary.replace(path)


def write_json(path: Path, value: object) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def monthly_ranges(start: date, end: date):
    if start > end:
        raise ValueError("시작일이 종료일보다 늦습니다.")
    cursor = start
    while cursor <= end:
        last = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        finish = min(last, end)
        yield cursor, finish
        cursor = finish + timedelta(days=1)


def parse_chart(payload: dict, start: date, end: date, source_file: str) -> list[dict]:
    """Resolve month/day labels only within a single requested calendar month."""
    if start.year != end.year or start.month != end.month:
        raise ValueError("차트 파싱은 같은 연월 안에서만 가능합니다.")
    if not isinstance(payload, dict):
        raise ValueError("예상한 KAMIS JSON 객체가 아닙니다.")
    caption = payload.get("caption", "")
    if not all(word in caption for word in ("소매가격", "딸기", "설향", "상품", "500g")):
        raise ValueError("품목·품종·등급·단위가 확인된 응답이 아닙니다.")
    categories, series = payload.get("categories"), payload.get("data")
    if not isinstance(categories, list) or not isinstance(series, list):
        raise ValueError("KAMIS 응답 필드가 변경되었습니다: categories/data 확인 필요.")
    if not categories:
        if any(item.get("data") for item in series):
            raise ValueError("가격은 있으나 날짜가 없는 응답입니다.")
        return []
    averages = [item for item in series if item.get("name") == "평균"]
    if len(averages) != 1 or len(averages[0].get("data", [])) != len(categories):
        raise ValueError("평균 계열이 하나가 아니거나 날짜와 가격의 길이가 다릅니다.")
    rows, seen = [], set()
    for label, price in zip(categories, averages[0]["data"], strict=True):
        match = re.fullmatch(r"(\d{1,2})월\s*(\d{1,2})일", str(label).strip())
        if not match:
            raise ValueError(f"알 수 없는 조사일 표기: {label!r}")
        observed = date(start.year, int(match[1]), int(match[2]))
        if not start <= observed <= end or observed in seen:
            raise ValueError(f"범위 밖 또는 중복 조사일: {observed}")
        seen.add(observed)
        if isinstance(price, (bool, list, dict)):
            raise ValueError("가격 필드의 자료형이 변경되었습니다.")
        rows.append({"date": observed.isoformat(), "price": "" if price is None else price,
                     **LABELS, "source_file": source_file})
    return rows


def verify_page(content: bytes, params: dict) -> None:
    """Reject silent changes to the site's selected query conditions."""
    soup = BeautifulSoup(content, "html.parser")
    form = soup.select_one("#frm_search")
    if form is None:
        raise ValueError("공식 조회 폼을 찾을 수 없습니다.")
    for key in ("startday", "endday", *CONDITIONS):
        field = form.find("input", attrs={"name": key})
        if field is None or field.get("value", "") != params[key]:
            raise ValueError(f"조회 조건이 서버에서 변경되었습니다: {key}")


def collect(start: date, end: date, offline: bool = False) -> dict:
    manifest_path = DATA / "source_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text("utf-8"))
        if manifest.get("start") != str(start) or manifest.get("end") != str(end):
            raise ValueError("저장된 수집 기간과 다릅니다. 기존 원본 보존을 위해 중단합니다.")
        if manifest.get("conditions") != CONDITIONS or manifest.get("labels") != LABELS:
            raise ValueError("저장된 수집 조건이 현재 조건과 다릅니다.")
    elif offline:
        raise ValueError("오프라인 재현에 필요한 data/source_manifest.json이 없습니다.")
    else:
        manifest = {"provider": "한국농수산식품유통공사(aT) KAMIS", "page_url": PAGE_URL,
                    "chart_url": CHART_URL, "start": str(start), "end": str(end),
                    "conditions": CONDITIONS, "labels": LABELS, "requests": []}

    rows, collection_rows = [], []
    with requests.Session() as session:
        session.headers["User-Agent"] = "StrawberryPriceAnalysis/1.0 (educational research)"
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 502, 503, 504],
                      allowed_methods=frozenset(["GET", "POST"]))
        session.mount("https://", HTTPAdapter(max_retries=retry))
        for begin, finish in monthly_ranges(start, end):
            name = f"{begin:%Y-%m}-{begin.day:02d}-{finish.day:02d}"
            relative = f"data/source/{name}.json"
            path = ROOT / relative
            params = {**CONDITIONS, "startday": str(begin), "endday": str(finish)}
            entries = [entry for entry in manifest["requests"] if entry["file"] == relative]
            if entries:
                if len(entries) != 1 or entries[0].get("params") != params:
                    raise ValueError(f"원본 메타데이터 불일치: {relative}")
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != entries[0]["sha256"]:
                    raise ValueError(f"원본 SHA-256 불일치: {relative}")
            elif offline:
                raise ValueError(f"저장된 월별 원본이 없습니다: {relative}")
            else:
                if path.exists():
                    raise ValueError(f"출처 기록 없는 기존 원본을 덮어쓰지 않습니다: {relative}")
                page = session.get(PAGE_URL, params={"action": "daily", **params}, timeout=(10, 30))
                page.raise_for_status()
                verify_page(page.content, params)
                response = session.post(CHART_URL, data=params, timeout=(10, 30))
                response.raise_for_status()
                raw = response.content
                # Validate before preserving a successful response.
                parse_chart(response.json(), begin, finish, relative)
                SOURCE.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                page_path = SOURCE / f"{name}.html"
                page_path.write_bytes(page.content)
                manifest["requests"].append({
                    "file": relative, "page_file": page_path.relative_to(ROOT).as_posix(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "page_sha256": hashlib.sha256(page.content).hexdigest(),
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "method": "POST", "url": CHART_URL, "params": params,
                    "http_status": response.status_code,
                })
                write_json(manifest_path, manifest)
                time.sleep(0.25)
            page_path = ROOT / entries[0]["page_file"] if entries else SOURCE / f"{name}.html"
            entry = entries[0] if entries else manifest["requests"][-1]
            page_raw = page_path.read_bytes()
            if hashlib.sha256(page_raw).hexdigest() != entry["page_sha256"]:
                raise ValueError("조회 조건 확인용 HTML의 SHA-256이 다릅니다.")
            verify_page(page_raw, params)
            month_rows = parse_chart(json.loads(raw), begin, finish, relative)
            rows.extend(month_rows)
            collection_rows.append({"month": f"{begin:%Y-%m}", "requested_start": str(begin),
                                    "requested_end": str(finish), "returned_rows": len(month_rows),
                                    "status": "observations_returned" if month_rows else "no_observations_returned",
                                    "source_file": relative})
            print(f"{begin:%Y-%m}: {len(month_rows)}개 조사일", flush=True)

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    write_text(DATA / "strawberry_raw.csv", output.getvalue())
    collection_output = io.StringIO(newline="")
    collection_writer = csv.DictWriter(collection_output, fieldnames=list(collection_rows[0]))
    collection_writer.writeheader()
    collection_writer.writerows(collection_rows)
    write_text(DATA / "monthly_collection.csv", collection_output.getvalue())
    summary = {"raw_rows": len(rows), "unique_dates": len({r["date"] for r in rows}),
               "requested_start": str(start), "requested_end": str(end),
               "requested_months": len(collection_rows),
               "months_with_observations": sum(row["returned_rows"] > 0 for row in collection_rows)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="KAMIS 서울·설향·상품·500g 소매가격 수집")
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--offline", action="store_true", help="저장된 원본만 검증해 CSV 재생성")
    args = parser.parse_args()
    try:
        collect(args.start, args.end, args.offline)
    except (ValueError, OSError, requests.RequestException) as exc:
        print(f"수집 실패: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
