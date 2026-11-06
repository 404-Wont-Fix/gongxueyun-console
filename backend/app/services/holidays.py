"""Three-source annual calendars; never infer holidays from weekdays.

All upstream text is untrusted. URLs are allowlisted, sizes/timeouts bounded,
whole-year data validated, and disagreements never replace an accepted snapshot.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import threading
from html import unescape
from urllib.parse import urlparse, urljoin

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Account, CalendarOverride, CalendarYear, utcnow
from ..settings import get_settings

log = logging.getLogger(__name__)
CN_URL = "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json"
TIMOR_URL = "https://timor.tech/api/holiday/year/{year}"
# Bootstrap discovery only. Following years are discovered from holiday-cn papers
# and retained government source URLs; parsed dates are never hard-coded here.
GOV_PAPERS = {2026: "https://www.gov.cn/zhengce/zhengceku/202511/content_7047091.htm"}
HOSTS = {"raw.githubusercontent.com", "timor.tech", "www.timor.tech", "www.gov.cn"}
_lock = threading.Lock()
_worker: BackgroundScheduler | None = None


class CalendarError(ValueError):
    pass


def fetch_text(url: str) -> str:
    """No account data or credentials are sent to calendar providers."""
    for _ in range(4):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise CalendarError("日历来源 URL 不在允许范围")
        with requests.get(url, timeout=(5, 12), stream=True, allow_redirects=False,
                          headers={"User-Agent": "gongxueyun-console/0.1 holiday-calendar", "Accept": "application/json,text/html"}) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    raise CalendarError("日历响应过大")
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8-sig")
    raise CalendarError("日历重定向次数过多")


def _date(value: str, year: int) -> str:
    day = dt.date.fromisoformat(value)
    if day.year != year or day.isoformat() != value:
        raise CalendarError("日期不属于请求年份")
    return value


def validate_days(days: dict, year: int) -> dict:
    # Reject unpublished, partial, and malformed years instead of guessing that
    # all missing days are workdays. Modern annual notices contain all festivals.
    if not 20 <= len(days) <= 80:
        raise CalendarError("年度日历为空或不完整（待公布/待核对）")
    off = 0
    for key, item in days.items():
        _date(key, year)
        if type(item.get("off")) is not bool or not isinstance(item.get("name"), str) or not item["name"]:
            raise CalendarError("日期性质或名称无效")
        off += item["off"]
    if off < 20 or not any(d.startswith(f"{year}-01") for d in days) or not any(d.startswith(f"{year}-10") for d in days):
        raise CalendarError("缺少完整年度放假安排")
    return dict(sorted(days.items()))


def parse_cn(data: dict, year: int) -> tuple[dict, list[str]]:
    if data.get("year") != year or not isinstance(data.get("days"), list):
        raise CalendarError("holiday-cn 年份或结构不正确")
    days = {}
    for item in data["days"]:
        day = _date(item["date"], year)
        if day in days:
            raise CalendarError("holiday-cn 日期重复")
        days[day] = {"name": item["name"], "off": item["isOffDay"]}
    papers = [u for u in data.get("papers", []) if isinstance(u, str) and
              urlparse(u).scheme == "https" and urlparse(u).hostname == "www.gov.cn"]
    return validate_days(days, year), papers


def parse_timor(data: dict, year: int) -> dict:
    if data.get("code") != 0 or not isinstance(data.get("holiday"), dict):
        raise CalendarError("提莫接口未返回年度日历")
    days = {}
    for item in data["holiday"].values():
        day = _date(item["date"], year)
        if day in days:
            raise CalendarError("提莫日期重复")
        days[day] = {"name": item.get("target") or item["name"], "off": item["holiday"]}
    return validate_days(days, year)


DATE_SPAN = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日(?:至(?:(\d{4})年)?(?:(\d{1,2})月)?(\d{1,2})日)?")


def parse_gov(html: str, year: int) -> dict:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    text = unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"\s+", "", text)
    if f"国务院办公厅关于{year}年部分节假日安排的通知" not in text:
        raise CalendarError("政府页面不是指定年份的年度放假通知")
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    if not all(name in text for name in ("元旦", "春节", "清明", "劳动", "端午", "中秋", "国庆")):
        raise CalendarError("政府通知缺少完整节假日章节")
    # Ignore the sign-off/footer and duplicated SEO summary. Their publication
    # date is not a holiday clause even when the summary contains “放假”.
    start = text.find("一、")
    if start < 0:
        raise CalendarError("政府通知缺少正文编号")
    text = text[start:].split("国务院办公厅", 1)[0]
    days = {}
    parsed_festivals: set[str] = set()
    sections = re.findall(r"[一二三四五六七八九十]+、([^：]+)：(.*?)(?=[一二三四五六七八九十]+、|$)", text)
    for name, paragraph in sections:
        if not any(x in name for x in ("元旦", "春节", "清明", "劳动", "端午", "中秋", "国庆")):
            continue
        section_off = 0
        for sentence in re.split(r"[。；]", paragraph):
            if "放假" not in sentence and "上班" not in sentence:
                continue
            off = "放假" in sentence
            if off and "上班" in sentence:
                raise CalendarError("政府日期表述需要人工核对")
            date_part = sentence.split("放假" if off else "上班")[0]
            if not re.search(r"\d+月", date_part):
                continue  # unrelated footer prose is not a date clause
            matches = list(DATE_SPAN.finditer(date_part))
            residue = DATE_SPAN.sub("", date_part).strip("、，,和及")
            if not matches or residue:
                raise CalendarError("政府日期格式变化，需要核对")
            span_days = 0
            for match in matches:
                y1, m1, d1, y2, m2, d2 = match.groups()
                first_year = int(y1 or year)
                last_month = int(m2 or m1)
                if d2 and int(m1) > last_month and not y1:
                    first_year = year - 1
                first = dt.date(first_year, int(m1), int(d1))
                last = dt.date(int(y2 or (first_year + (last_month < int(m1)))), last_month, int(d2)) if d2 else first
                if not 0 <= (last - first).days <= 15:
                    raise CalendarError("政府日期区间异常")
                span_days += (last - first).days + 1
                for offset in range((last - first).days + 1):
                    day = first + dt.timedelta(days=offset)
                    if day.year != year:
                        continue
                    key = day.isoformat()
                    value = {"name": name[:40], "off": off}
                    if key in days and days[key]["off"] != off:
                        raise CalendarError("政府通知存在冲突日期")
                    days[key] = value
            if off:
                section_off += span_days
                stated = re.search(r"共(\d+)天", sentence)
                if stated and int(stated[1]) != span_days:
                    raise CalendarError("政府放假天数与解析区间不一致")
        if section_off:
            parsed_festivals.update(n for n in ("元旦", "春节", "清明", "劳动", "端午", "中秋", "国庆") if n in name)
    if len(parsed_festivals) != 7:
        raise CalendarError("政府通知部分节日日期未解析，拒绝采用残缺年度")
    return validate_days(days, year)


def signature(days: dict) -> dict:
    # Names differ (e.g. 春节 vs 初一); only date/off affects scheduling.
    return {day: item["off"] for day, item in days.items()}


def accept_candidates(row: CalendarYear, candidates: dict[str, dict], sources: dict) -> None:
    row.sources = sources
    row.checked_at = utcnow()
    values = list(candidates.values())
    if values and any(signature(item) != signature(values[0]) for item in values[1:]):
        row.status = "conflict"
        row.message = "来源日期冲突；保留上次可信缓存，不采用本次变更。"
        return
    if "gov" in candidates or len(candidates) >= 2:
        row.days = candidates.get("gov") or candidates.get("holiday_cn") or values[0]
        row.accepted_at = utcnow()
        row.status = "ready" if len(candidates) == 3 else "degraded"
        row.message = "三源日期核对一致" if row.status == "ready" else "部分来源不可用；已由政府原文或两结构化源一致性核对。"
    else:
        row.status = "stale" if row.accepted_at else "missing"
        row.message = "暂未取得可信完整年度数据；使用旧缓存。" if row.accepted_at else "待公布或来源不可用，自动日历排班暂停；可设置单日覆盖。"


def sync_year(year: int) -> dict:
    if not 2020 <= year <= dt.datetime.now(get_settings().tz).year + 1:
        raise CalendarError("年份超出同步范围")
    if not _lock.acquire(blocking=False):
        raise CalendarError("已有日历同步任务，请稍后刷新")
    try:
        # Network access happens outside the database transaction.
        with SessionLocal() as db:
            existing = db.get(CalendarYear, year)
            prior = (existing.sources or {}).get("gov", {}).get("urls", []) if existing else []
        candidates, sources, papers = {}, {}, []
        for key, template, parser in (("holiday_cn", CN_URL, parse_cn), ("timor", TIMOR_URL, parse_timor)):
            url = template.format(year=year)
            try:
                raw = fetch_text(url)
                parsed = parser(json.loads(raw), year)
                if key == "holiday_cn":
                    parsed, papers = parsed
                candidates[key] = parsed
                sources[key] = {"status": "ok", "urls": [url], "days": len(parsed), "sha256": hashlib.sha256(raw.encode()).hexdigest()}
            except Exception as exc:
                sources[key] = {"status": "error", "urls": [url], "error": str(exc)[:240]}
        urls = list(dict.fromkeys(papers + prior + ([GOV_PAPERS[year]] if year in GOV_PAPERS else [])))[:3]
        try:
            if not urls:
                raise CalendarError("尚未发现该年度中国政府网公告链接")
            merged = {}
            hashes = []
            for url in urls:
                if urlparse(url).hostname != "www.gov.cn":
                    raise CalendarError("政府来源域名不正确")
                raw = fetch_text(url)
                parsed = parse_gov(raw, year)
                if merged and signature(merged) != signature(parsed):
                    raise CalendarError("多份政府公告需要核对")
                merged = parsed
                hashes.append(hashlib.sha256(raw.encode()).hexdigest())
            candidates["gov"] = merged
            sources["gov"] = {"status": "ok", "urls": urls, "days": len(merged), "sha256": hashes}
        except Exception as exc:
            sources["gov"] = {"status": "error", "urls": urls, "error": str(exc)[:240]}
        with SessionLocal() as db:
            row = db.get(CalendarYear, year) or CalendarYear(year=year)
            accept_candidates(row, candidates, sources)
            db.add(row)
            db.commit()
            return year_view(row, year)
    finally:
        _lock.release()


def year_view(row: CalendarYear | None, year: int) -> dict:
    return {"year": year, "status": row.status if row else "missing", "has_cache": bool(row and row.accepted_at),
            "message": row.message if row else "尚无年度日历，等待自动同步",
            "checked_at": row.checked_at.isoformat() + ("Z" if row.checked_at.tzinfo is None else "") if row and row.checked_at else None,
            "accepted_at": row.accepted_at.isoformat() + ("Z" if row.accepted_at.tzinfo is None else "") if row and row.accepted_at else None,
            "sources": row.sources if row else {}}


def day_schedule(db: Session, account: Account, day: dt.date) -> dict:
    override = db.get(CalendarOverride, (account.id, day.isoformat()))
    source, reason = "weekly", "账号每周设置"
    mode = "work" if not account.weekdays or str(day.isoweekday()) in account.weekdays.split(",") else "skip"
    if override:
        mode, source, reason = override.mode, "override", override.note or "单日自定义"
    elif account.calendar_enabled:
        calendar = db.get(CalendarYear, day.year)
        if not calendar or not calendar.accepted_at:
            mode, source, reason = "unknown", "calendar", "年度日历未就绪，暂停自动打卡"
        elif item := (calendar.days or {}).get(day.isoformat()):
            mode, source = ("holiday" if item["off"] else "work"), "calendar"
            reason = item["name"] + ("放假" if item["off"] else "调休上班")
    slots = []
    if mode == "holiday":
        slots = [{"kind": "HOLIDAY", "time": account.morning_time}]
    elif mode == "work":
        if account.morning_enabled:
            slots.append({"kind": "START", "time": account.morning_time})
        if account.evening_enabled:
            slots.append({"kind": "END", "time": account.evening_time})
    return {"mode": mode, "source": source, "reason": reason, "slots": slots,
            "automatic": account.enabled and account.auto_clock_in}


def sync_current_years() -> None:
    year = dt.datetime.now(get_settings().tz).year
    for target in (year, year + 1):
        try:
            sync_year(target)
        except Exception:
            log.exception("calendar sync failed: %s", target)


def start_calendar_sync() -> None:
    global _worker
    if get_settings().app_env == "test" or _worker:
        return
    _worker = BackgroundScheduler(timezone=get_settings().tz, daemon=True)
    _worker.add_job(sync_current_years, "interval", hours=24, max_instances=1, coalesce=True,
                    next_run_time=dt.datetime.now(get_settings().tz))
    _worker.start()


def stop_calendar_sync() -> None:
    global _worker
    if _worker:
        _worker.shutdown(wait=False)
        _worker = None
