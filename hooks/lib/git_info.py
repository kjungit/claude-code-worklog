"""Best-effort git commit lookup used as a corroborating signal during Map (docs 4.2, 22.4).

Branch attribution comes from each record's own `git_branch` field (already
captured at Stop-hook time), not from git log -- so this module only needs
to fetch commit messages for a date, not work out which branch they're on.
Anything that can't be determined is reported in `data_gaps` rather than
silently dropped (docs 9, section on daily-work-log's "explicit reporting"
principle).
"""

import datetime
import subprocess


def _run_git(args, cwd, timeout=15):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _is_git_repo(project_path):
    try:
        proc = _run_git(["rev-parse", "--is-inside-work-tree"], project_path)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _current_user_email(project_path):
    try:
        proc = _run_git(["config", "user.email"], project_path)
    except (OSError, subprocess.TimeoutExpired):
        return None
    email = proc.stdout.strip()
    return email or None


def get_commits_for_date(project_path, date_str):
    """Returns (commit_lines, data_gaps) for one project on one calendar day."""
    if not project_path:
        return [], ["프로젝트 경로를 알 수 없음 — 커밋 이력 확인 불가"]

    if not _is_git_repo(project_path):
        return [], ["git 저장소 아님 — 커밋 이력 확인 불가"]

    data_gaps = []
    email = _current_user_email(project_path)
    if not email:
        data_gaps.append("git user.email 미설정 — 작성자 필터링 없이 전체 커밋 수집됨")

    day = datetime.date.fromisoformat(date_str)
    next_day = (day + datetime.timedelta(days=1)).isoformat()
    args = [
        "log",
        "--all",
        "--since=%sT00:00:00" % date_str,
        "--until=%sT00:00:00" % next_day,
        "--pretty=format:%h %s",
    ]
    if email:
        args.append("--author=%s" % email)

    try:
        proc = _run_git(args, project_path)
    except (OSError, subprocess.TimeoutExpired):
        return [], data_gaps + ["git log 실행 실패 — 커밋 이력 확인 불가"]

    if proc.returncode != 0:
        return [], data_gaps + ["git log 실행 실패 — 커밋 이력 확인 불가"]

    commits = [line for line in proc.stdout.splitlines() if line.strip()]
    return commits, data_gaps
