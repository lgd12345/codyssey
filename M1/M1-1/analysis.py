"""Reproduce the strawberry price analysis from preserved official responses."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache" / "matplotlib"))

import matplotlib
matplotlib.use("Agg")
from matplotlib import dates as mdates, font_manager, pyplot as plt, ticker
import numpy as np
import pandas as pd

from collect_data import DATA, LABELS, collect, write_json, write_text

MIN_OBSERVATIONS = 100
OUTLIER_THRESHOLD = 20.0  # Screening candidate only; never an automatic deletion rule.
VALIDATION_SIZE = 20
LONG_GAP_DAYS = 30
NAVY, PINK, CREAM, GRAY, GREEN = "#151B21", "#D84F6D", "#FFF8F1", "#E8EEF2", "#376854"


def clean_data(raw: pd.DataFrame, start: date, end: date) -> tuple[pd.DataFrame, dict]:
    required = {"date", "price", *LABELS}
    if not required.issubset(raw.columns):
        raise ValueError(f"필수 열 누락: {sorted(required - set(raw.columns))}")
    for column, expected in LABELS.items():
        if not raw[column].eq(expected).all():
            raise ValueError(f"일관되지 않은 수집 조건: {column}")
    frame = raw.copy()
    frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="coerce")
    text = frame["price"].astype("string").str.replace(",", "", regex=False).str.strip()
    frame["price"] = pd.to_numeric(text, errors="coerce").astype(float)
    reasons = pd.Series("", index=frame.index, dtype="string")
    masks = {
        "invalid_date": frame["date"].isna(),
        "outside_requested_range": ~frame["date"].between(pd.Timestamp(start), pd.Timestamp(end)),
        "missing_or_nonfinite_price": ~np.isfinite(frame["price"]),
        "nonpositive_price": frame["price"].le(0),
    }
    excluded = {}
    for reason, mask in masks.items():
        selected = mask & reasons.eq("")
        excluded[reason] = int(selected.sum())
        reasons.loc[selected] = reason
    valid = frame.loc[reasons.eq("")].copy()
    # Same date and same price are exact analytical duplicates; different prices are ambiguous.
    exact = valid.duplicated(subset=["date", "price", *LABELS])
    excluded["exact_duplicate"] = int(exact.sum())
    valid = valid.loc[~exact].sort_values("date").reset_index(drop=True)
    if valid["date"].duplicated().any():
        raise ValueError("같은 날짜에 서로 다른 가격이 있습니다. 원본 확인 전 집계하지 않습니다.")
    audit = {
        "requested_start": str(start), "requested_end": str(end),
        "raw_rows": len(raw), "condition_matched_rows": len(raw),
        "raw_unique_dates": int(frame["date"].nunique()),
        "raw_missing_or_nonfinite_prices": int((~np.isfinite(frame["price"])).sum()),
        "raw_nonpositive_prices": int(frame["price"].le(0).sum()),
        "raw_duplicate_date_rows": int(frame["date"].duplicated().sum()),
        "excluded": excluded, "clean_rows": len(valid),
        "valid_unique_dates": int(valid["date"].nunique()),
    }
    return valid, audit


def add_features(clean: pd.DataFrame) -> pd.DataFrame:
    frame = clean.copy()
    frame["moving_average_7"] = frame["price"].rolling(7, min_periods=7).mean()
    frame["change_pct"] = frame["price"].pct_change(fill_method=None) * 100
    frame["gap_days"] = frame["date"].diff().dt.days
    frame["long_gap"] = frame["gap_days"].gt(LONG_GAP_DAYS)
    frame["outlier_candidate"] = frame["change_pct"].abs().gt(OUTLIER_THRESHOLD)
    return frame


def naive_validation(frame: pd.DataFrame, size: int = VALIDATION_SIZE) -> pd.DataFrame:
    if size < 1 or len(frame) <= size:
        raise ValueError("검증 구간 앞에 적어도 1개의 과거 관측값이 필요합니다.")
    result = frame[["date", "price"]].copy()
    result["prediction"] = result["price"].shift(1)
    result["previous_observation_date"] = result["date"].shift(1)
    result = result.tail(size).copy().reset_index(drop=True)
    result["absolute_error"] = (result["price"] - result["prediction"]).abs()
    return result


def independent_checks(frame: pd.DataFrame) -> list[dict]:
    checks = []
    for position in (6, len(frame) // 2, len(frame) - 1):
        row = frame.iloc[position]
        values = [Decimal(str(v)) for v in frame.iloc[position - 6:position + 1]["price"]]
        average = sum(values) / Decimal(7)
        previous = Decimal(str(frame.iloc[position - 1]["price"]))
        change = (Decimal(str(row["price"])) / previous - 1) * 100
        if not math.isclose(float(average), row["moving_average_7"], abs_tol=1e-8):
            raise ValueError("이동평균 독립 검산 불일치")
        if not math.isclose(float(change), row["change_pct"], abs_tol=1e-8):
            raise ValueError("변화율 독립 검산 불일치")
        checks.append({"date": row["date"].date().isoformat(), "window_prices": [float(v) for v in values],
                       "previous_price": float(previous), "price": float(row["price"]),
                       "moving_average_7_decimal": str(average),
                       "change_pct_decimal": str(change), "passed": True})
    return checks


def record(frame: pd.DataFrame, index: int) -> dict:
    row = frame.loc[index]
    result = {"date": str(row["date"].date()), "price": float(row["price"])}
    if pd.notna(row["change_pct"]):
        result.update(change_pct=float(row["change_pct"]), gap_days=int(row["gap_days"]))
        previous = frame.loc[index - 1]
        result.update(previous_date=str(previous["date"].date()), previous_price=float(previous["price"]))
    return result


def configure_fonts() -> bool:
    names = {font.name for font in font_manager.fontManager.ttflist}
    for name in ("Malgun Gothic", "AppleGothic", "Noto Sans CJK KR", "NanumGothic"):
        if name in names:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return True
    print("한글 폰트 확인 안 됨: 그래프 레이블에 영문을 사용합니다.")
    plt.rcParams["font.family"] = "DejaVu Sans"
    return False


def make_chart(number: str, title: str, subtitle: str, note: str):
    fig = plt.figure(figsize=(12.8, 7.4), facecolor=CREAM)
    ax = fig.add_axes([0.09, 0.19, 0.86, 0.48], facecolor=CREAM)
    fig.text(0.065, 0.92, "STRAWBERRY MARKET", color=NAVY, fontsize=12, weight="bold")
    fig.text(0.94, 0.92, f"RESEARCH / {number}", color=GREEN, fontsize=10, ha="right")
    fig.text(0.065, 0.815, title, color=NAVY, fontsize=24, weight="bold")
    fig.text(0.065, 0.755, subtitle, color="#5A6266", fontsize=10)
    fig.text(0.065, 0.075, note, color="#5A6266", fontsize=9)
    fig.text(0.94, 0.032, "SOURCE  aT / KAMIS", color="#5A6266", fontsize=8, ha="right")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#D8D3CE")
    ax.tick_params(colors="#5A6266", labelsize=10, length=0, pad=10)
    ax.grid(axis="y", color="#DEDAD4", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))
    ax.set_ylabel("KRW / 500g", color="#5A6266", labelpad=12, fontsize=10)
    return fig, ax


def plot_results(frame: pd.DataFrame, monthly: pd.DataFrame, predictions: pd.DataFrame,
                 start: date, end: date) -> None:
    korean = configure_fonts()
    images = ROOT / "images"
    images.mkdir(exist_ok=True)
    subtitle = (f"서울 · 설향 · 상품 · 500g  |  유효 관측일 {len(frame)}개  |  "
                f"{frame.date.min():%Y.%m.%d} - {frame.date.max():%Y.%m.%d}") if korean else (
                f"Seoul / Seolhyang / high grade / 500g  |  {len(frame)} observations")
    daily = frame.set_index("date").reindex(pd.date_range(start, end, freq="D"))

    def finish(fig, ax, filename, temporal=True):
        if temporal:
            interval = 3 if (end - start).days > 730 else 1
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=interval))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y.%m"))
            ax.set_xlim(pd.Timestamp(start), pd.Timestamp(end))
        ax.set_ylim(bottom=0)
        fig.savefig(images / filename, dpi=180, facecolor=CREAM)
        plt.close(fig)

    note = "빈 날짜는 값을 채우지 않고 선을 끊었습니다. 평균·최고·최저는 실제 관측값 기준입니다." if korean else "Missing dates remain blank. Summary statistics use observed prices only."
    fig, ax = make_chart("01", "딸기 소매가격, 3년의 흐름" if korean else "Three years of strawberry prices", subtitle, note)
    ax.plot(daily.index, daily.price, color=PINK, linewidth=2.1, marker="o", markersize=2.4)
    for label, index, offset in (("최고" if korean else "HIGH", frame.price.idxmax(), (12, 16)),
                                 ("최저" if korean else "LOW", frame.price.idxmin(), (-110, 25))):
        row = frame.loc[index]
        ax.scatter(row.date, row.price, color=NAVY, s=24, zorder=4)
        ax.annotate(f"{label}  {row.price:,.0f}\n{row.date:%Y.%m.%d}", (row.date, row.price),
                    xytext=offset, textcoords="offset points", fontsize=9, color=NAVY,
                    arrowprops={"arrowstyle": "-", "color": NAVY, "lw": 0.7})
    ax.set_ylim(0, frame.price.max() * 1.22)
    ax.text(0.99, 0.94, f"MEAN  {frame.price.mean():,.0f} KRW / 500g", transform=ax.transAxes,
            ha="right", fontsize=10, color=GREEN)
    finish(fig, ax, "01_price_trend.png")

    fig, ax = make_chart("02", "단기 변동 너머의 가격 추세" if korean else "Beyond short-term fluctuations", subtitle,
                         "최근 7개 유효 관측일 기준입니다. 장기 공백 전 가격이 계산창에 포함될 수 있습니다." if korean else "Mean uses 7 valid observations; its window may span long calendar gaps.")
    ax.plot(daily.index, daily.price, color=PINK, alpha=0.5, linewidth=1.2, marker="o", markersize=2,
            label="관측가격" if korean else "Observed")
    ax.plot(daily.index, daily.moving_average_7, color=GREEN, linewidth=2.3,
            label="7관측일 이동평균" if korean else "7-observation mean")
    ax.legend(frameon=False, loc="upper right", fontsize=10)
    ax.set_ylim(0, frame.price.max() * 1.3)
    finish(fig, ax, "02_moving_average.png")

    fig, unused_ax = make_chart("03", "월별 평균, 같은 눈금으로 비교" if korean else "Monthly means on the same scale", subtitle,
                                "— : 유효 관측 없음(0원이 아님)  ·  n : 유효 관측일 수  ·  사선 : n=1" if korean else "Dash: no valid observation, not zero price. n: valid days. Hatch: n=1.")
    unused_ax.remove()
    fig.set_size_inches(12.8, 10.8)
    years = sorted(monthly["month"].str[:4].unique())
    for year, bottom in zip(years, np.linspace(0.54, 0.14, len(years)), strict=True):
        ax = fig.add_axes([0.09, bottom, 0.86, 0.15], facecolor=CREAM)
        subset = monthly.loc[monthly["month"].str.startswith(year)].reset_index(drop=True)
        positions = np.arange(len(subset))
        bars = ax.bar(positions, subset["mean"], width=0.6, color=PINK, alpha=0.88)
        for bar, row in zip(bars, subset.itertuples(), strict=True):
            if row.count == 0:
                ax.text(bar.get_x()+bar.get_width()/2, 400, "—", ha="center", color="#777777", fontsize=12)
                continue
            if row.count == 1:
                bar.set_hatch("///")
            ax.text(bar.get_x()+bar.get_width()/2, row.mean+350, f"{row.mean:,.0f}\nn={row.count}",
                    ha="center", color=NAVY, fontsize=8)
        ax.set_title(year, loc="left", fontsize=13, weight="bold", color=GREEN, pad=11)
        ax.set_xticks(positions, subset["month"].str[-2:])
        ax.set_ylim(0, monthly["mean"].max()*1.4)
        ax.yaxis.set_major_locator(ticker.MaxNLocator(4))
        ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))
        ax.set_ylabel("KRW / 500g", fontsize=8, color="#5A6266")
        ax.grid(axis="y", color="#DEDAD4", linewidth=0.7)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#D8D3CE")
        ax.tick_params(colors="#5A6266", labelsize=9, length=0, pad=6)
    fig.savefig(images / "03_monthly_average.png", dpi=180, facecolor=CREAM)
    plt.close(fig)

    fig, ax = make_chart("04", "직전 가격으로 예측하면" if korean else "Predicting with the last observed price", subtitle,
                         "마지막 20개 관측값에서 매번 직전 관측가격으로 1-step 예측합니다. 장기 고정 예측이 아닙니다." if korean else "Rolling 1-step forecasts on the final 20 observations; not a fixed multi-step forecast.")
    ax.plot(predictions.date, predictions.price, color=PINK, linewidth=2, marker="o", markersize=4,
            label="실제 가격" if korean else "Actual")
    ax.plot(predictions.date, predictions.prediction, color=NAVY, linewidth=1.6, linestyle="--",
            label="직전 관측가격 예측" if korean else "Previous-price forecast")
    mae = predictions.absolute_error.mean()
    ax.text(0.02, 0.93, f"MAE  {mae:,.2f} KRW / 500g", transform=ax.transAxes, color=GREEN, fontsize=11, weight="bold")
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    ax.set_ylim(0, max(predictions.price.max(), predictions.prediction.max()) * 1.3)
    ax.set_xlim(predictions.date.min()-pd.Timedelta(days=1), predictions.date.max()+pd.Timedelta(days=1))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m.%d"))
    finish(fig, ax, "04_baseline_prediction.png", temporal=False)


def run() -> dict:
    manifest = json.loads((DATA / "source_manifest.json").read_text("utf-8"))
    start, end = date.fromisoformat(manifest["start"]), date.fromisoformat(manifest["end"])
    # Verify source hashes and selected conditions, then rebuild the raw CSV offline.
    collect(start, end, offline=True)
    raw = pd.read_csv(DATA / "strawberry_raw.csv", keep_default_na=False)
    clean, audit = clean_data(raw, start, end)
    if len(clean) < MIN_OBSERVATIONS:
        raise ValueError(f"유효 관측일이 {len(clean)}개입니다. 100개 미만이므로 분석을 중단합니다.")
    frame = add_features(clean)
    audit.update(outlier_threshold_pct=OUTLIER_THRESHOLD,
                 outlier_candidate_count=int(frame.outlier_candidate.sum()),
                 max_absolute_change_pct=float(frame.change_pct.abs().max()),
                 max_gap_days=int(frame.gap_days.max()),
                 long_gap_threshold_days=LONG_GAP_DAYS,
                 long_gap_count=int(frame.long_gap.sum()))
    coverage = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    appeared = pd.to_datetime(raw.date, errors="coerce")
    coverage["status"] = np.where(coverage.date.isin(frame.date), "price_observed",
                                 np.where(coverage.date.isin(appeared), "price_missing", "no_record_in_response"))
    audit["calendar_coverage"] = {status: int(coverage.status.eq(status).sum())
                                  for status in ("price_observed", "price_missing", "no_record_in_response")}
    audit["requested_calendar_days"] = len(coverage)
    monthly = (frame.assign(month=frame.date.dt.strftime("%Y-%m")).groupby("month")["price"]
               .agg(["count", "mean", "median", "min", "max"]))
    months = pd.period_range(start, end, freq="M").astype(str)
    monthly = monthly.reindex(months).rename_axis("month").reset_index()
    monthly["count"] = monthly["count"].fillna(0).astype(int)
    annual = (frame.assign(year=frame.date.dt.year).groupby("year")["price"]
              .agg(["count", "mean", "median", "min", "max"]).reset_index())
    predictions = naive_validation(frame)
    checks = independent_checks(frame)
    summary = {
        "conditions": LABELS, "audit": audit,
        "first": record(frame, 0), "last": record(frame, len(frame)-1),
        "minimum": record(frame, frame.price.idxmin()), "maximum": record(frame, frame.price.idxmax()),
        "overall_change_pct": float((frame.price.iloc[-1]/frame.price.iloc[0]-1)*100),
        "mean_price": float(frame.price.mean()),
        "largest_increase": record(frame, frame.change_pct.idxmax()),
        "largest_decrease": record(frame, frame.change_pct.idxmin()),
        "monthly": json.loads(monthly.to_json(orient="records", double_precision=15)),
        "annual": annual.to_dict(orient="records"),
        "counterexample_last_20": {"first": record(frame, len(frame)-20),
                                   "last": record(frame, len(frame)-1),
                                   "change_pct": float((frame.price.iloc[-1]/frame.price.iloc[-20]-1)*100)},
        "prediction": {"method": "rolling one-step naive", "training_observations": len(frame)-VALIDATION_SIZE,
                       "validation_observations": VALIDATION_SIZE,
                       "validation_start": str(predictions.date.iloc[0].date()),
                       "validation_end": str(predictions.date.iloc[-1].date()),
                       "mae": float(predictions.absolute_error.mean())},
        "independent_checks": checks,
    }
    for name, table in (("strawberry_clean.csv", clean), ("analysis_results.csv", frame),
                        ("monthly_summary.csv", monthly), ("annual_summary.csv", annual),
                        ("baseline_predictions.csv", predictions), ("calendar_coverage.csv", coverage)):
        write_text(DATA / name, table.to_csv(index=False, date_format="%Y-%m-%d", float_format="%.10g"))
    write_json(DATA / "quality_report.json", audit)
    write_json(DATA / "analysis_summary.json", summary)
    plot_results(frame, monthly, predictions, start, end)
    print(f"\n분석 완료: 유효 관측일 {len(frame)}개 / 그래프 4개 / MAE {summary['prediction']['mae']:,.2f}원/500g")
    return summary


if __name__ == "__main__":
    try:
        run()
    except (ValueError, OSError, KeyError) as exc:
        print(f"분석 실패: {exc}", file=sys.stderr)
        raise SystemExit(1)
