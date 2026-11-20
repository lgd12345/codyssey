"""Checks for data loss, ambiguous observations, and forecast leakage."""

from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

from analysis import add_features, clean_data, naive_validation
from collect_data import (CONDITIONS, DEFAULT_START, DEFAULT_END, LABELS, ROOT,
                          collect, monthly_ranges, parse_chart, verify_page)


def example_rows(prices, dates=None):
    if dates is None:
        dates = pd.bdate_range("2025-01-01", periods=len(prices)).strftime("%Y-%m-%d")
    return pd.DataFrame([{"date": day, "price": price, **LABELS}
                         for day, price in zip(dates, prices, strict=True)])


class CleaningTests(unittest.TestCase):
    def clean(self, raw):
        return clean_data(raw, date(2025, 1, 1), date(2025, 1, 31))

    def test_missing_zero_negative_and_infinite_are_not_zero_filled(self):
        clean, audit = self.clean(example_rows([1000, "-", 0, -1, float("inf"), "1,200"]))
        self.assertEqual(clean.price.tolist(), [1000, 1200])
        self.assertEqual(audit["excluded"]["missing_or_nonfinite_price"], 2)
        self.assertEqual(audit["excluded"]["nonpositive_price"], 2)

    def test_conflicting_prices_on_one_date_fail(self):
        raw = example_rows([1000, 2000], ["2025-01-02", "2025-01-02"])
        with self.assertRaisesRegex(ValueError, "서로 다른 가격"):
            self.clean(raw)

    def test_identical_duplicates_do_not_inflate_count(self):
        clean, audit = self.clean(example_rows([1000, 1000], ["2025-01-02"]*2))
        self.assertEqual(len(clean), 1)
        self.assertEqual(audit["excluded"]["exact_duplicate"], 1)

    def test_mixed_units_fail(self):
        raw = example_rows([1000, 2000])
        raw.loc[1, "unit"] = "원/kg"
        with self.assertRaisesRegex(ValueError, "unit"):
            self.clean(raw)

    def test_invalid_and_outside_dates_are_excluded_separately(self):
        clean, audit = self.clean(example_rows([1000, 1200, 1500], ["bad", "2024-12-31", "2025-01-02"]))
        self.assertEqual(len(clean), 1)
        self.assertEqual(audit["excluded"]["invalid_date"], 1)
        self.assertEqual(audit["excluded"]["outside_requested_range"], 1)

    def test_real_large_change_is_retained_as_candidate(self):
        clean, _ = self.clean(example_rows([1000, 1500]))
        features = add_features(clean)
        self.assertEqual(len(features), 2)
        self.assertTrue(features.outlier_candidate.iloc[-1])

    def test_seven_observations_are_not_seven_calendar_days(self):
        clean, _ = self.clean(example_rows([100, 200, 300, 400, 500, 600, 700, 800]))
        features = add_features(clean)
        self.assertTrue(features.moving_average_7.iloc[:6].isna().all())
        self.assertEqual(features.moving_average_7.iloc[6], 400)
        self.assertEqual(features.moving_average_7.iloc[7], 500)
        self.assertGreater((features.date.iloc[6] - features.date.iloc[0]).days, 6)

    def test_change_uses_previous_observation_across_gap(self):
        clean, _ = self.clean(example_rows([1000, 1100], ["2025-01-03", "2025-01-06"]))
        features = add_features(clean)
        self.assertAlmostEqual(features.change_pct.iloc[1], 10)
        self.assertEqual(features.gap_days.iloc[1], 3)

    def test_season_gap_is_flagged_without_filling_prices(self):
        clean, _ = clean_data(example_rows([5000, 12000], ["2024-05-01", "2024-12-01"]),
                              date(2024,1,1), date(2024,12,31))
        features = add_features(clean)
        self.assertEqual(len(features), 2)
        self.assertTrue(features.long_gap.iloc[1])
        self.assertAlmostEqual(features.change_pct.iloc[1], 140)


class ForecastTests(unittest.TestCase):
    def test_first_validation_prediction_uses_last_training_value(self):
        clean, _ = clean_data(example_rows([100, 200, 300, 400, 500]), date(2025,1,1), date(2025,1,31))
        predicted = naive_validation(clean, size=2)
        self.assertEqual(predicted.prediction.tolist(), [300, 400])
        self.assertEqual(predicted.absolute_error.mean(), 100)
        self.assertTrue((predicted.previous_observation_date < predicted.date).all())

    def test_changing_future_actual_does_not_change_its_prediction(self):
        clean, _ = clean_data(example_rows([100, 200, 300, 400, 500]), date(2025,1,1), date(2025,1,31))
        before = naive_validation(clean, size=2)
        clean.loc[4, "price"] = 99999
        after = naive_validation(clean, size=2)
        self.assertEqual(before.prediction.tolist(), after.prediction.tolist())

    def test_no_training_history_fails(self):
        with self.assertRaises(ValueError):
            naive_validation(example_rows([100, 200]), size=2)


class SourceContractTests(unittest.TestCase):
    def setUp(self):
        self.payload = {"caption": "소매가격 딸기 설향 상품 단위 : 500g",
                        "categories": ["01월 02일", "01월 03일"],
                        "data": [{"name": "평균", "data": [1000, None]}]}

    def test_null_price_is_preserved_for_cleaning(self):
        rows = parse_chart(self.payload, date(2025,1,1), date(2025,1,31), "source.json")
        self.assertEqual([r["price"] for r in rows], [1000, ""])
        self.assertEqual(rows[0]["date"], "2025-01-02")

    def test_mismatched_categories_and_prices_fail(self):
        self.payload["data"][0]["data"].pop()
        with self.assertRaises(ValueError):
            parse_chart(self.payload, date(2025,1,1), date(2025,1,31), "source.json")

    def test_wrong_unit_or_rank_caption_fails(self):
        for caption in ("소매가격 딸기 설향 상품 단위 : 1kg", "소매가격 딸기 설향 중품 단위 : 500g"):
            with self.subTest(caption=caption), self.assertRaises(ValueError):
                parse_chart({**self.payload, "caption": caption}, date(2025,1,1), date(2025,1,31), "source.json")

    def test_cross_year_labels_are_not_guessed(self):
        with self.assertRaises(ValueError):
            parse_chart(self.payload, date(2024,12,1), date(2025,1,31), "source.json")

    def test_duplicate_response_date_fails(self):
        self.payload["categories"][1] = self.payload["categories"][0]
        with self.assertRaises(ValueError):
            parse_chart(self.payload, date(2025,1,1), date(2025,1,31), "source.json")

    def test_month_chunks_have_no_gap_at_year_boundary(self):
        self.assertEqual(list(monthly_ranges(date(2024,12,30), date(2025,1,2))),
                         [(date(2024,12,30), date(2024,12,31)), (date(2025,1,1), date(2025,1,2))])

    def test_three_year_range_has_all_36_months_and_leap_day(self):
        chunks = list(monthly_ranges(DEFAULT_START, DEFAULT_END))
        self.assertEqual(len(chunks), 36)
        self.assertEqual(chunks[0], (date(2023,1,1), date(2023,1,31)))
        self.assertIn((date(2024,2,1), date(2024,2,29)), chunks)
        self.assertEqual(chunks[-1], (date(2025,12,1), date(2025,12,31)))

    def test_empty_month_is_not_fabricated_as_zero_price(self):
        payload = {**self.payload, "categories": [], "data": [{"name": "평균", "data": []}]}
        self.assertEqual(parse_chart(payload, date(2023,7,1), date(2023,7,31), "empty.json"), [])

    def test_server_changes_to_region_fail(self):
        html = "<form id='frm_search'><input name='countycode' value='2100'></form>"
        with self.assertRaises(ValueError):
            verify_page(html.encode(), {**CONDITIONS, "startday": "2025-01-01", "endday": "2025-01-31"})


class PreservedDataTests(unittest.TestCase):
    """Independent calculations from source JSON, without using analysis helpers."""

    def test_real_source_checksums_and_decimal_results(self):
        manifest = json.loads((ROOT/"data/source_manifest.json").read_text("utf-8"))
        prices = {}
        for entry in manifest["requests"]:
            raw = (ROOT/entry["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
            payload = json.loads(raw)
            series = next(item for item in payload["data"] if item["name"] == "평균")
            year = entry["params"]["startday"][:4]
            for label, value in zip(payload["categories"], series["data"], strict=True):
                month, day = label.replace("월", " ").replace("일", "").split()
                if value is None or value == "":
                    continue
                price = Decimal(str(value).replace(",", ""))
                if price.is_finite() and price > 0:
                    key = f"{year}-{int(month):02d}-{int(day):02d}"
                    self.assertNotIn(key, prices)
                    prices[key] = price
        ordered = sorted(prices)
        self.assertGreaterEqual(len(ordered), 100)
        output = pd.read_csv(ROOT/"data/analysis_results.csv")
        for index in (6, len(ordered)//2, len(ordered)-1):
            day = ordered[index]
            row = output.loc[output.date.eq(day)].iloc[0]
            mean = sum(prices[k] for k in ordered[index-6:index+1])/7
            change = (prices[day]/prices[ordered[index-1]]-1)*100
            self.assertAlmostEqual(row.moving_average_7, float(mean), places=5)
            self.assertAlmostEqual(row.change_pct, float(change), places=7)

    def test_offline_collection_never_uses_network(self):
        with patch("requests.Session.request", side_effect=AssertionError("Network used")):
            result = collect(DEFAULT_START, DEFAULT_END, offline=True)
        self.assertGreaterEqual(result["unique_dates"], 100)
        self.assertEqual(result["requested_months"], 36)

    def test_all_months_are_recorded_even_without_observations(self):
        collection = pd.read_csv(ROOT/"data/monthly_collection.csv")
        monthly = pd.read_csv(ROOT/"data/monthly_summary.csv")
        self.assertEqual(collection.month.tolist(), pd.period_range("2023-01", "2025-12", freq="M").astype(str).tolist())
        self.assertEqual(monthly.month.tolist(), collection.month.tolist())
        empty = monthly.loc[monthly["count"].eq(0)]
        self.assertGreater(len(empty), 0)
        self.assertTrue(empty[["mean", "median", "min", "max"]].isna().all().all())
        self.assertTrue(collection.loc[collection.returned_rows.eq(0), "status"].eq("no_observations_returned").all())

    def test_modified_source_is_rejected_before_rebuilding_csv(self):
        temporary_root = ROOT / "tmp"
        temporary_root.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=temporary_root) as temporary:
            project = Path(temporary)
            data = project/"data"
            source = data/"source"
            source.mkdir(parents=True)
            (source/"sample.json").write_text('{"changed":true}', encoding="utf-8")
            manifest = {"start": "2025-01-01", "end": "2025-01-31", "conditions": CONDITIONS,
                        "labels": LABELS, "requests": [{"file": "data/source/2025-01-01-31.json",
                        "params": {**CONDITIONS, "startday": "2025-01-01", "endday": "2025-01-31"},
                        "sha256": hashlib.sha256(b"original source").hexdigest()}]}
            (source/"sample.json").rename(source/"2025-01-01-31.json")
            (data/"source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with patch("collect_data.ROOT", project), patch("collect_data.DATA", data):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    collect(date(2025,1,1), date(2025,1,31), offline=True)
            self.assertFalse((data/"strawberry_raw.csv").exists())

    def test_report_images_and_document_links_exist(self):
        for document in (ROOT/"README.md", ROOT/"REPORT.md", ROOT/"data/SOURCE.md"):
            for link in re.findall(r"\]\(([^)]+)\)", document.read_text("utf-8")):
                if not link.startswith(("https://", "http://", "#")):
                    self.assertTrue((document.parent/link.split("#")[0]).is_file(), link)
        image_links = re.findall(r"!\[[^]]*\]\(([^)]+)\)", (ROOT/"REPORT.md").read_text("utf-8"))
        self.assertEqual(len(image_links), 4)


if __name__ == "__main__":
    unittest.main()
