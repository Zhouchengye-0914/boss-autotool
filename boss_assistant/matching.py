from __future__ import annotations

import re
from dataclasses import dataclass

from .talent_data import JobTaxonomyItem, ProfileSnapshot


PROFILE_TERMS = (
    "Python", "SQL", "MySQL", "Power BI", "Excel", "数据分析", "数据挖掘",
    "机器学习", "深度学习", "AI", "大模型", "Agent", "RAG", "产品", "运营",
    "业务分析", "自动化", "Linux", "项目管理", "可视化", "数据建模",
)


@dataclass(frozen=True)
class MatchResult:
    score: float
    reasons: tuple[str, ...]
    eligible: bool


def recommend_titles(profile: ProfileSnapshot, taxonomy: list[JobTaxonomyItem], limit: int = 12) -> list[str]:
    text = profile.full_text.lower()
    preferred = {
        "数据分析师": 100, "数据产品经理": 92, "AI 产品经理": 90,
        "数据挖掘": 86, "Python": 82, "机器学习": 78,
        "项目专员 / 助理": 70, "需求分析工程师": 76,
        "数据治理": 74, "数据采集": 68, "软件测试": 62,
    }
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for item in taxonomy:
        if item.title in seen: continue
        seen.add(item.title)
        score = float(preferred.get(item.title, 0))
        if item.title.lower() in text: score += 20
        if item.category in {"人工智能", "数据", "产品经理", "技术项目管理"}: score += 12
        if any(term.lower() in item.title.lower() for term in ("销售", "客服", "教师", "柜员")):
            score -= 100
        if score > 0: scored.append((score, item.title))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [title for _, title in scored[:limit]]


def match_job(job: dict, profile: ProfileSnapshot, threshold: float = 58.0) -> MatchResult:
    title = str(job.get("title") or "")
    body = " ".join((title, str(job.get("job_description") or ""),
                     " ".join(job.get("skills") or []))).lower()
    profile_text = profile.full_text.lower()
    reasons: list[str] = []
    score = 0.0
    directions = {
        "数据分析": 32, "数据运营": 30, "业务运营": 26, "AI产品": 30,
        "AI 产品": 30, "数据产品": 30, "Python": 24, "机器学习": 22,
        "人工智能": 20, "需求分析": 20, "项目助理": 16, "管培生": 14,
    }
    matched_directions = [(term, weight) for term, weight in directions.items()
                          if term.lower() in body]
    if matched_directions:
        term, weight = max(matched_directions, key=lambda pair: pair[1])
        score += weight; reasons.append(f"岗位方向匹配：{term}")
    skills = [term for term in PROFILE_TERMS if term.lower() in body and term.lower() in profile_text]
    if skills:
        skill_score = min(30, 6 * len(skills)); score += skill_score
        reasons.append("技能重合：" + "、".join(skills[:5]))
    degree = str(job.get("degree") or "")
    if not degree or any(x in degree for x in ("不限", "本科", "大专")):
        score += 10; reasons.append("学历要求可满足")
    experience = str(job.get("experience") or "")
    if not experience or any(x in experience for x in ("不限", "应届", "在校", "1年以内")):
        score += 12; reasons.append("经验要求适合应届生")
    elif "1-3年" in experience:
        score += 3; reasons.append("经验要求略高")
    if any(word in title for word in ("高级", "资深", "专家", "负责人", "总监")):
        score -= 28; reasons.append("职级明显偏高")
    if any(word in title for word in ("销售", "客服", "主播", "保险", "信贷")):
        score -= 60; reasons.append("不符合求职方向")
    if re.search(r"[3-9]-[1-9]0年|5-10年|10年以上", experience):
        score -= 25; reasons.append("工作年限不匹配")
    score = max(0.0, min(100.0, score))
    return MatchResult(score, tuple(reasons), score >= threshold)
