# Reality Check

Job-market predictions, checked against the real data. UK first, US alongside.

Double-click **`run.bat`** (or run `py -3 server.py`). It opens at
<http://127.0.0.1:8780/>. It uses only the Python standard library: no pip
install, no build step, no account and no API key.

## What's in it

| Tab | What it does |
|---|---|
| **Overview** | Latest UK and US figures (unemployment, youth unemployment, vacancies, software job postings, pay versus inflation), each compared with a year earlier. |
| **Famous predictions** | 12 researched predictions about jobs and AI, from Frey & Osborne (2013) to Amodei (2025). Each one is turned into an explicit rule and scored automatically against official data. |
| **Official forecasts** | Every OBR forecast since 2010 (UK unemployment, employment, earnings) and every Survey of Professional Forecasters forecast since 1968 (US unemployment), graded against the outturn: average miss by horizon, bias, biggest misses, and the forecasts still open. |
| **Salaries** | Median and percentile pay by occupation, UK (ONS ASHE) against US (BLS OEWS), 2014–2025. Pounds at the market rate or at purchasing power, in nominal or today's prices. |
| **Explore data** | Chart any series, including Indeed job postings for 49 sectors in each country. Series in different units are indexed to 100. |
| **My predictions** | Log your own. Tie each one to a series and a threshold, give a deadline and your confidence, and the app scores it when the data arrives. Once predictions resolve, you get a Brier score showing how well your confidence matched reality. |

## How a prediction is checked

Every prediction becomes one of three rules, and the rule is always shown:

- **reach**: the series hits a threshold at any point in a window (for example, US unemployment ≥ 10% between May 2026 and May 2030)
- **change**: the series moves by at least X% between two dates (for example, UK employment lower in 2034 than in 2014)
- **level**: the value on the deadline is above or below a threshold

The possible verdicts are *Came true*, *Didn't happen*, *Too early*, *Waiting for data* (deadline passed, official figure not out yet), *No deadline* (tracked, never scored) and *Can't be scored*.

Many famous predictions weren't precise ("47% of jobs at risk"). For those, the rule the app applies is written out under "Why this rule", so you can disagree with the rule rather than with the data. To add or edit one, change `content/famous.json`; the tests check its shape.

## Data sources

| Source | Used for | Refreshed |
|---|---|---|
| [ONS](https://www.ons.gov.uk/) time series | UK unemployment, youth unemployment, employment, vacancies, pay, CPI | every 12 h |
| [ONS ASHE Table 14](https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours/datasets/occupation4digitsoc2010ashetable14) | UK pay by occupation | once per edition |
| [OBR Historical Official Forecasts Database](https://obr.uk/data/) | UK official forecasts | weekly |
| [FRED](https://fred.stlouisfed.org/) (BLS and Fed data) | US unemployment, payrolls, openings, pay, CPI, USD/GBP | every 12 h |
| [BLS OEWS](https://www.bls.gov/oes/tables.htm) | US pay by occupation | once per year |
| [Philadelphia Fed SPF](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/survey-of-professional-forecasters) | US professional forecasts | weekly |
| [Indeed Hiring Lab](https://github.com/hiring-lab/job_postings_tracker) (CC BY 4.0) | UK and US job postings, overall and by sector | daily |
| [World Bank](https://data.worldbank.org/indicator/PA.NUS.PRVT.PP) | Purchasing-power parity rate | monthly |

Downloads are cached in `data/cache/` and requests to the same site are spaced out, because ONS rate-limits bursts. If a source is down, the last good copy is shown and marked as stale. **Refresh data** re-fetches everything (about a minute). Nothing is sent anywhere except these requests for public files.

On first run the salary tables download in the background: 12 ONS editions of about 11 MB each, plus 12 small BLS files. Only the extracted numbers are kept.

## Caveats worth knowing

- ONS published ASHE as `.xls` until 2024, so `reality/xls.py` is a small standard-library reader for that format.
- UK occupation codes changed in 2021 (SOC 2010 to SOC 2020). Each occupation maps both codes, and the chart marks the break. US codes also changed in 2019 and 2021.
- UK salary figures are full-time employees. US figures are hourly pay × 2,080 hours. BLS doesn't publish exact values above its top limit (about $239k), so those are left out.
- Indeed sector postings aren't seasonally adjusted, and are relative to 1 Feb 2020 rather than a count of jobs.
- In OBR outturns, the latest year comes from the ONS annual average. Earnings outturns come only from the OBR.

## Files

```
server.py            web server + API (localhost only; cross-site writes refused)
reality/series.py    catalog of data series and their loaders
reality/forecasts.py OBR and SPF forecast parsing and scoring
reality/salaries.py  ASHE + OEWS download, parsing, conversions
reality/checks.py    the prediction rules and Brier score
reality/net.py       cached, rate-limited downloads
reality/xlsx.py, xls.py   spreadsheet readers
content/famous.json  the researched predictions
web/                 the page (plain HTML/CSS/JS, hand-written SVG charts)
data/                cache + your predictions (data/mine.json)
tests/               py -3 -m unittest discover -s tests
```

Environment variables: `REALITY_PORT`, `REALITY_DATA` (use a different data
folder, useful for testing), `REALITY_NO_BROWSER=1`, `REALITY_OFFLINE=1`
(cache only), `REALITY_NO_PREFETCH=1`.
