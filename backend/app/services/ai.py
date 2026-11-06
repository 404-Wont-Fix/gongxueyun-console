"""AI writing assistant (OpenAI-compatible Chat Completions).

Configuration is resolved in this order:

1. database ``app_settings['ai']`` (editable in the web UI, key encrypted);
2. environment variables ``AI_BASE_URL`` / ``AI_API_KEY`` / ``AI_MODEL``.

The prompts are deliberately narrow: the AI drafts *text* from the user's real
position/responsibilities and the generated outline. It is told not to invent
metrics, clients or awards, and the result is always a draft the user reviews
before submission.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from sqlalchemy.orm import Session

from ..models import Account, AppSetting
from ..security import decrypt_secret, encrypt_secret
from ..settings import get_settings

logger = logging.getLogger(__name__)

SETTING_KEY = "ai"
TYPE_LABEL = {"day": "日报", "week": "周报", "month": "月报", "summary": "总结"}


class AIError(RuntimeError):
    """AI is unavailable or returned something unusable."""


@dataclass
class AIConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.6
    timeout: float = 60.0
    configured: bool = False
    source: str = "none"

    def public(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "configured": self.configured,
            "source": self.source,
            "has_key": bool(self.api_key),
        }


def _env_config() -> AIConfig:
    settings = get_settings()
    base_url = (settings.ai.get("base_url") or "").strip()
    model = (settings.ai.get("model") or "").strip()
    api_key = (settings.ai.get("api_key") or "").strip()
    configured = bool(base_url and model and api_key)
    return AIConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=0.6,
        timeout=float(settings.ai.get("timeout") or 60),
        configured=configured,
        source="env" if configured else "none",
    )


def resolve_config(db: Session | None) -> AIConfig:
    env = _env_config()
    if db is None:
        return env
    row = db.get(AppSetting, SETTING_KEY)
    data = dict(row.value or {}) if row else {}
    if not data:
        return env
    base_url = str(data.get("base_url") or "").strip()
    model = str(data.get("model") or "").strip()
    api_key = ""
    if data.get("api_key_enc"):
        try:
            api_key = decrypt_secret(str(data["api_key_enc"]))
        except ValueError:
            api_key = ""
    api_key = api_key or env.api_key
    configured = bool(str(data.get("enabled", True)) not in {"False", "0"} and base_url and model and api_key)
    return AIConfig(
        base_url=base_url or env.base_url,
        api_key=api_key,
        model=model or env.model,
        temperature=float(data.get("temperature") if data.get("temperature") is not None else env.temperature),
        timeout=float(data.get("timeout") if data.get("timeout") is not None else env.timeout),
        configured=configured,
        source="database" if configured else env.source,
    )


def save_config(db: Session, payload: dict[str, Any]) -> AIConfig:
    row = db.get(AppSetting, SETTING_KEY)
    current = dict(row.value or {}) if row else {}
    data = {
        "base_url": str(payload.get("base_url", current.get("base_url", "")) or "").strip(),
        "model": str(payload.get("model", current.get("model", "")) or "").strip(),
        "temperature": float(payload.get("temperature", current.get("temperature", 0.6)) or 0.6),
        "timeout": float(payload.get("timeout", current.get("timeout", 60)) or 60),
        "enabled": bool(payload.get("enabled", current.get("enabled", True))),
        "api_key_enc": current.get("api_key_enc", ""),
    }
    if payload.get("api_key"):
        data["api_key_enc"] = encrypt_secret(str(payload["api_key"]).strip())
    if payload.get("clear_key"):
        data["api_key_enc"] = ""
    if row is None:
        row = AppSetting(key=SETTING_KEY, value=data)
    else:
        row.value = data
    db.add(row)
    db.commit()
    return resolve_config(db)


def clear_config(db: Session) -> None:
    row = db.get(AppSetting, SETTING_KEY)
    if row is not None:
        db.delete(row)
        db.commit()


def chat(db: Session | None, messages: list[dict[str, str]], *, max_tokens: int = 1200, temperature: float | None = None) -> str:
    config = resolve_config(db)
    if not config.configured:
        raise AIError("未配置 AI（设置页填写 Base URL / 模型 / Key）")
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.model,
                "messages": messages,
                "temperature": config.temperature if temperature is None else temperature,
                "max_tokens": max_tokens,
            },
            timeout=config.timeout,
        )
    except requests.RequestException as exc:
        raise AIError(f"AI 请求失败：{type(exc).__name__}") from exc
    if response.status_code >= 400:
        message = ""
        try:
            body = response.json()
            message = str((body.get("error") or {}).get("message") or body.get("message") or "")
        except ValueError:
            message = response.text[:200]
        raise AIError(f"AI 返回 HTTP {response.status_code}：{message[:200]}")
    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIError("AI 响应结构无法识别") from exc
    text = _strip_code_fence(str(content or "")).strip()
    if not text:
        raise AIError("AI 返回了空内容")
    return text


def test_connection(db: Session | None, override: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        if override and override.get("base_url") and override.get("model"):
            # Test unsaved form values without persisting them.
            api_key = str(override.get("api_key") or "")
            if not api_key and db is not None:
                api_key = resolve_config(db).api_key
            config = AIConfig(
                base_url=str(override["base_url"]).rstrip("/"),
                api_key=api_key,
                model=str(override["model"]),
                configured=True,
            )
            if not config.api_key:
                raise AIError("测试连接需要填写 API Key")
            url = f"{config.base_url}/chat/completions"
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {config.api_key}"},
                json={
                    "model": config.model,
                    "messages": [{"role": "user", "content": "只回复两个字：可用"}],
                    "max_tokens": 8,
                },
                timeout=20,
            )
            if response.status_code >= 400:
                raise AIError(f"HTTP {response.status_code}")
            reply = _strip_code_fence(str(response.json()["choices"][0]["message"]["content"])).strip()
        else:
            reply = chat(db, [{"role": "user", "content": "只回复两个字：可用"}], max_tokens=8)
        return {"ok": True, "latency_ms": int((time.time() - started) * 1000), "reply": reply[:40]}
    except (AIError, requests.RequestException, ValueError, KeyError, IndexError) as exc:
        return {"ok": False, "message": str(exc)[:300], "latency_ms": int((time.time() - started) * 1000)}


# --------------------------------------------------------------------- prompts
def _profile_block(account: Account) -> str:
    profile = account.profile or {}
    location = account.location or {}
    lines = [
        f"岗位：{profile.get('position') or '实习生'}",
        f"单位：{profile.get('company') or (account.plan or {}).get('createName') or '实习单位'}",
        f"部门：{profile.get('department') or '未填写'}",
        f"指导老师：{profile.get('mentor') or '未填写'}",
        f"日常职责：{profile.get('responsibilities') or '未填写'}",
        f"常用工具/技能：{profile.get('tools') or '未填写'}",
        f"写作风格：{profile.get('tone') or '平实、简洁、第一人称'}",
        f"需要避免：{profile.get('avoid') or '不编造具体数据、客户名称和奖励'}",
        f"工作地点：{location.get('address') or '未填写'}",
    ]
    return "\n".join(lines)


_OUTLINE_SYSTEM = (
    "你是一名中文实习写作助理。你只输出 JSON，不要 Markdown、不要解释、不要代码块。"
    "内容必须贴合岗位职责，具体、可执行，不夸大，不编造数据、客户名称或奖项。"
)

_REPORT_SYSTEM = (
    "你是一名正在实习的学生，正在写实习报告正文。"
    "只输出正文，不要标题、不要 Markdown、不要代码块、不要列表符号。"
    "语气平实、第一人称，内容贴合岗位职责，不夸大成果，不编造具体数据、客户名称或奖励。"
)


def generate_outline(
    db: Session | None,
    account: Account,
    *,
    kind: str,
    start_date: str,
    end_date: str,
    dates: list[str],
    notes: str = "",
) -> tuple[str, list[dict[str, Any]], str]:
    """Return (title, items, source). Raises AIError when unusable."""
    if kind not in {"week", "month"}:
        raise AIError("大纲只支持 week 或 month")
    if not dates:
        raise AIError("所选周期内没有可写的日期")

    user = f"""请为下面这位实习生制定一份{TYPE_LABEL['week'] if kind == 'week' else '月'}写作计划。

{_profile_block(account)}

周期：{start_date} 至 {end_date}
需要覆盖的日期（只写这些天）：{', '.join(dates)}
补充说明：{notes or '无'}

要求：
1. 每一天给出一个主题 theme、2-4 条具体工作事项 tasks、一句要点 key_points。
2. 事项要贴合岗位职责，具体到"做什么"，不要每天重复同一件事。
3. 按时间推进：前期熟悉/上手，中期独立完成任务，后期总结/复盘。
4. 不要编造具体数据、客户名称、奖项。
5. 只输出 JSON：
{{"title":"计划标题","items":[{{"date":"YYYY-MM-DD","theme":"主题","tasks":["事项1","事项2"],"key_points":"要点"}}]}}
"""
    raw = chat(
        db,
        [{"role": "system", "content": _OUTLINE_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=1800,
        temperature=0.7,
    )
    payload = _extract_json(raw)
    items = _normalise_items(payload.get("items"), dates)
    if len(items) < max(1, len(dates) // 2):
        raise AIError("AI 大纲覆盖的日期过少")
    title = str(payload.get("title") or f"{start_date} 实习写作计划")[:200]
    return title, items, "ai"


def write_report(
    db: Session | None,
    account: Account,
    *,
    report_type: str,
    day: str,
    plan_item: dict[str, Any] | None = None,
    period_items: list[dict[str, Any]] | None = None,
    recent: list[str] | None = None,
    notes: str = "",
) -> str:
    label = TYPE_LABEL.get(report_type, "报告")
    sections: list[str] = [_profile_block(account), f"报告日期：{day}", f"报告类型：{label}"]
    if plan_item:
        tasks = "；".join(str(item) for item in (plan_item.get("tasks") or []))
        sections.append(
            "当天的计划：\n"
            f"主题：{plan_item.get('theme') or ''}\n"
            f"事项：{tasks or '无'}\n"
            f"要点：{plan_item.get('key_points') or ''}"
        )
    if period_items:
        lines = []
        for item in period_items[:31]:
            tasks = "、".join(str(t) for t in (item.get("tasks") or []))
            lines.append(f"- {item.get('date')}：{item.get('theme') or ''}（{tasks}）")
        if lines:
            sections.append("本周期计划完成的工作：\n" + "\n".join(lines))
    if recent:
        sections.append("最近已经写过的内容（避免重复，不要照抄）：\n" + "\n".join(recent[:4]))
    if notes:
        sections.append(f"补充要点：{notes}")

    user = "\n\n".join(sections) + f"""

请写一篇 {label} 正文，要求：
1. 300-500 字，分 4-5 个自然段（概况、主要工作、收获、问题与改进、下一步）。
2. 围绕上面的职责和计划展开，具体但不要罗列清单。
3. 不编造数据、金额、客户名称或奖励；不确定的内容用概括表述。
4. 不要标题，不要 Markdown，不要出现"作为AI"之类的字样。
"""
    content = chat(
        db,
        [{"role": "system", "content": _REPORT_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=1200,
        temperature=0.7,
    )
    return _clean_body(content)


# -------------------------------------------------------------------- helpers
def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = _strip_code_fence(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise AIError("AI 没有返回 JSON")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except ValueError as exc:
        raise AIError("AI 返回的 JSON 无法解析") from exc
    if not isinstance(payload, dict):
        raise AIError("AI 返回的 JSON 不是对象")
    return payload


def _normalise_items(raw: Any, dates: list[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    allowed = set(dates)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        day = str(entry.get("date") or "").strip()
        if day not in allowed or day in seen:
            continue
        tasks = entry.get("tasks")
        if isinstance(tasks, str):
            tasks = [tasks]
        if not isinstance(tasks, list):
            tasks = []
        clean_tasks = [str(task).strip()[:120] for task in tasks if str(task).strip()][:5]
        items.append(
            {
                "date": day,
                "theme": str(entry.get("theme") or "").strip()[:80] or "日常工作",
                "tasks": clean_tasks or ["按计划完成岗位日常工作"],
                "key_points": str(entry.get("key_points") or "").strip()[:160],
            }
        )
        seen.add(day)
    items.sort(key=lambda item: item["date"])
    return items


def _clean_body(text: str) -> str:
    body = _strip_code_fence(text).strip()
    body = re.sub(r"^#+\s*", "", body, flags=re.MULTILINE)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body[:6000]
