from __future__ import annotations

import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import AppConfig, SearchConfig
from .models import JobTask, OperationType


def _find_job_lists(value: Any) -> list[list[dict[str, Any]]]:
    found: list[list[dict[str, Any]]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() == "joblist" and isinstance(child, list):
                found.append([item for item in child if isinstance(item, dict)])
            else:
                found.extend(_find_job_lists(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_find_job_lists(child))
    return found


def parse_joblist_response(body: Any, query: str = "") -> list[dict[str, Any]]:
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return []
    if not isinstance(body, dict) or body.get("code") not in (None, 0):
        return []
    jobs: list[dict[str, Any]] = []
    for job_list in _find_job_lists(body):
        for raw in job_list:
            job_id = str(raw.get("encryptJobId") or raw.get("jobId") or "").strip()
            if not job_id:
                continue
            jobs.append({
                "job_id": job_id,
                "title": str(raw.get("jobName") or "").strip(),
                "salary": str(raw.get("salaryDesc") or "").strip(),
                "degree": str(raw.get("jobDegree") or "").strip(),
                "experience": str(raw.get("jobExperience") or "").strip(),
                "company": str(raw.get("brandName") or "").strip(),
                "city": str(raw.get("cityName") or raw.get("cityname") or "").strip(),
                "district": str(raw.get("areaDistrict") or "").strip(),
                "boss_name": str(raw.get("bossName") or "").strip(),
                "boss_title": str(raw.get("bossTitle") or "").strip(),
                "industry": str(raw.get("brandIndustry") or raw.get("industryName") or "").strip(),
                "company_size": str(raw.get("brandScaleName") or raw.get("scaleName") or "").strip(),
                "financing": str(raw.get("brandStageName") or raw.get("stageName") or "").strip(),
                "skills": list(raw.get("skills") or raw.get("jobLabels") or []),
                "job_description": str(raw.get("postDescription") or raw.get("jobDescription") or "").strip(),
                "query": query,
                "url": f"https://www.zhipin.com/job_detail/{job_id}.html",
                "raw": raw,
            })
    return jobs


def salary_meets_minimum(text: str, minimum_k: int) -> bool:
    normalized = (text or "").strip().upper()
    if not normalized or "面议" in normalized or "元/天" in normalized:
        return True
    match = re.search(r"(\d+)\s*(?:K)?\s*[-~至]\s*(\d+)\s*K", normalized)
    if match:
        return int(match.group(1)) >= minimum_k
    single = re.search(r"(\d+)\s*K", normalized)
    return not single or int(single.group(1)) >= minimum_k


class BossJobScanner:
    """复用 boss-tool 的 joblist 监听方式，不依赖 jsonpath 第三方包。"""

    def __init__(self, page: Any, config: SearchConfig, *, rng=None, sleeper=time.sleep, reporter=print):
        self.page = page
        self.config = config
        self.rng = rng or random.Random()
        self.sleeper = sleeper
        self.reporter = reporter
        self.last_raw_jobs: list[dict[str, Any]] = []

    def _packet_jobs(self, query: str) -> list[dict[str, Any]]:
        try:
            for packet in self.page.listen.steps(timeout=self.config.listen_timeout_seconds):
                jobs = parse_joblist_response(packet.response.body, query)
                if jobs:
                    return jobs
        except Exception as exc:
            self.reporter(f"[SEARCH] joblist 监听失败：{type(exc).__name__}: {exc}")
        return []

    def scan(self) -> list[dict[str, Any]]:
        started_at = time.monotonic()
        queries = self.config.keywords or ("",)
        maximum_pages = len(queries) * self.config.max_pages_per_keyword
        self.reporter(
            f"[SEARCH] 计划：{len(queries)} 个搜索入口，最多 {maximum_pages} 页；"
            f"每次滚动等待 {self.config.scroll_min_seconds:.0f}-{self.config.scroll_max_seconds:.0f} 秒"
        )
        collected: dict[str, dict[str, Any]] = {}
        for query in queries:
            self.reporter(f"[SEARCH] 关键词：{query or '空关键词（BOSS 个性化推荐）'}")
            self.page.listen.start("joblist")
            url = (
                "https://www.zhipin.com/web/geek/job?"
                f"city={self.config.city_code}&query={quote(query)}"
            )
            self.page.get(url)
            page_number = 0
            while page_number < self.config.max_pages_per_keyword:
                jobs = self._packet_jobs(query)
                if not jobs:
                    break
                before = len(collected)
                for job in jobs:
                    collected.setdefault(job["job_id"], job)
                page_number += 1
                self.reporter(
                    f"[SEARCH] {query} 第 {page_number}/{self.config.max_pages_per_keyword} 页，"
                    f"新增 {len(collected) - before}，累计 {len(collected)}，"
                    f"耗时 {(time.monotonic() - started_at) / 60:.1f} 分钟"
                )
                if page_number >= self.config.max_pages_per_keyword:
                    break
                self.page.run_js("window.scrollTo(0, document.body.scrollHeight);")
                self.sleeper(self.rng.uniform(self.config.scroll_min_seconds, self.config.scroll_max_seconds))
        self.last_raw_jobs = list(collected.values())
        result = self.filter(self.last_raw_jobs)
        self.reporter(
            f"[SEARCH] 搜索完成：{len(result)} 条候选，总耗时 "
            f"{(time.monotonic() - started_at) / 60:.1f} 分钟"
        )
        return result

    def filter(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for job in jobs:
            title = job.get("title", "")
            if any(keyword in title for keyword in self.config.exclude_title_keywords):
                continue
            if job.get("company", "") in self.config.company_blacklist:
                continue
            if not salary_meets_minimum(job.get("salary", ""), self.config.min_salary_k):
                continue
            result.append(job)
        self.reporter(f"[SEARCH] 原始 {len(jobs)}，筛选后 {len(result)}")
        return result


def jobs_to_tasks(jobs: list[dict[str, Any]], config: AppConfig) -> list[JobTask]:
    resume_name = config.resume.options[0].display_name or config.resume.options[0].key
    return [JobTask.from_dict({
        "task_id": f"scan-{job['job_id']}", "job_id": job["job_id"],
        "job_url": job["url"], "job_title": job.get("title", ""),
        "company": job.get("company", ""), "job_category": job.get("query", ""),
        "job_description": job.get("job_description", ""),
        "match_score": float(job.get("match_score") or 0),
        "greeting": config.search.greeting, "resume_name": resume_name,
        "operation_type": OperationType.COMMUNICATION.value,
    }) for job in jobs]


def save_tasks(path: Path, tasks: list[JobTask]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{
        "task_id": task.task_id, "job_url": task.job_url, "job_id": task.job_id,
        "job_title": task.job_title, "company": task.company,
        "job_category": task.job_category, "greeting": task.greeting,
        "job_description": task.job_description, "match_score": task.match_score,
        "resume_name": task.resume_name, "operation_type": task.operation_type.value,
    } for task in tasks]
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
