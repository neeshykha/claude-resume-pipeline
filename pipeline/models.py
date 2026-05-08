"""
Shared data models for the job pipeline.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
import json
import os


@dataclass
class Job:
    """A single job posting."""
    title: str
    company: str
    location: str
    url: str
    source: str
    description: str = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    company_size: Optional[str] = None
    date_posted: Optional[str] = None
    # Set after scoring
    fit_score: float = 0.0
    score_reasons: list = field(default_factory=list)
    # Set after tailoring
    resume_path: Optional[str] = None
    cover_letter_path: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def save_jobs(jobs: list[Job], path: str):
    """Save a list of jobs to JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump([j.to_dict() for j in jobs], f, indent=2, default=str)


def load_jobs(path: str) -> list[Job]:
    """Load jobs from JSON."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [Job.from_dict(d) for d in json.load(f)]
