"""GitHub GraphQL client for issue-scout."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import requests

from . import __version__
from .models import Comment, IssueInfo, LinkedPR


class IssueScoutError(Exception):
    """Base error for issue-scout."""


class AuthError(IssueScoutError):
    pass


class RateLimitError(IssueScoutError):
    pass


class NetworkError(IssueScoutError):
    pass


class GraphQLError(IssueScoutError):
    pass


GRAPHQL_URL = "https://api.github.com/graphql"

_BOT_LOGIN_RE = re.compile(r"(\[bot\]$|-bot$|^dependabot|^renovate)", re.IGNORECASE)

_ISSUE_FIELDS = """
  number
  title
  url
  labels(first: 20) { nodes { name } }
  assignees(first: 10) { nodes { login } }
  comments(last: 10) {
    nodes {
      author { login __typename }
      bodyText
      createdAt
    }
  }
  timelineItems(last: 30, itemTypes: [CROSS_REFERENCED_EVENT]) {
    nodes {
      __typename
      ... on CrossReferencedEvent {
        source {
          __typename
          ... on PullRequest {
            number
            url
            state
            author { login }
          }
        }
      }
    }
  }
"""

_QUERY_WITH_LABELS = (
    f"""
    query($owner: String!, $repo: String!, $first: Int!, $cursor: String, $labels: [String!]) {{
      repository(owner: $owner, name: $repo) {{
        issues(states: OPEN, first: $first, after: $cursor, labels: $labels,
               orderBy: {{field: CREATED_AT, direction: DESC}}) {{
          nodes {{ {_ISSUE_FIELDS} }}
          pageInfo {{ endCursor hasNextPage }}
        }}
      }}
    }}
    """
)

_QUERY_NO_LABELS = (
    f"""
    query($owner: String!, $repo: String!, $first: Int!, $cursor: String) {{
      repository(owner: $owner, name: $repo) {{
        issues(states: OPEN, first: $first, after: $cursor,
               orderBy: {{field: CREATED_AT, direction: DESC}}) {{
          nodes {{ {_ISSUE_FIELDS} }}
          pageInfo {{ endCursor hasNextPage }}
        }}
      }}
    }}
    """
)


def _parse_iso(s: str) -> datetime:
    # GitHub returns ISO8601 with trailing Z; fromisoformat needs +00:00 on Py3.9/3.10
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _is_bot(login: str | None, typename: str | None) -> bool:
    if typename == "Bot":
        return True
    if not login:
        return True
    return bool(_BOT_LOGIN_RE.search(login))


class GitHubClient:
    def __init__(self, token: str, *, session: requests.Session | None = None) -> None:
        if not token:
            raise AuthError("GitHub token is required.")
        self.token = token
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"bearer {token}",
                "User-Agent": f"issue-scout/{__version__}",
                "Accept": "application/json",
            }
        )

    def fetch_issues(
        self,
        owner: str,
        repo: str,
        labels: list[str] | None = None,
        max_issues: int = 50,
    ) -> list[IssueInfo]:
        labels = labels or []
        results: list[IssueInfo] = []
        cursor: str | None = None
        remaining = max_issues

        while remaining > 0:
            page_size = min(50, remaining)
            variables: dict[str, Any] = {
                "owner": owner,
                "repo": repo,
                "first": page_size,
                "cursor": cursor,
            }
            if labels:
                variables["labels"] = labels
                query = _QUERY_WITH_LABELS
            else:
                query = _QUERY_NO_LABELS

            payload = self._post(query, variables)
            repo_data = (payload.get("data") or {}).get("repository")
            if not repo_data:
                raise GraphQLError(f"Repository not found: {owner}/{repo}")
            issues_block = repo_data["issues"]
            for node in issues_block["nodes"]:
                results.append(self._node_to_issue(node, owner, repo))
                if len(results) >= max_issues:
                    return results

            page_info = issues_block["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]
            remaining = max_issues - len(results)

        return results

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self.session.post(
                GRAPHQL_URL,
                json={"query": query, "variables": variables},
                timeout=30,
            )
        except requests.RequestException as e:
            raise NetworkError(f"Network error contacting GitHub: {e}") from e

        if resp.status_code == 401:
            raise AuthError("GitHub returned 401 Bad credentials. Check your GITHUB_TOKEN.")
        if resp.status_code == 403:
            body = resp.text.lower()
            if "rate limit" in body or "secondary rate limit" in body:
                raise RateLimitError(
                    "GitHub rate limit hit. Wait a bit or use a token with more headroom."
                )
            raise AuthError(f"GitHub returned 403: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise NetworkError(f"GitHub HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            payload = resp.json()
        except ValueError as e:
            raise NetworkError(f"Invalid JSON from GitHub: {e}") from e

        if payload.get("errors"):
            msg = "; ".join(e.get("message", "?") for e in payload["errors"])
            raise GraphQLError(f"GraphQL error: {msg}")
        return payload

    @staticmethod
    def _node_to_issue(node: dict[str, Any], owner: str, repo: str) -> IssueInfo:
        labels = [n["name"] for n in node["labels"]["nodes"]]
        assignees = [n["login"] for n in node["assignees"]["nodes"]]
        # GitHub doesn't expose __typename on assignee nodes here; treat all as humans
        # unless the login matches our bot pattern.
        assignee_is_bot_map = {a: _is_bot(a, None) for a in assignees}

        comments: list[Comment] = []
        for c in node["comments"]["nodes"]:
            author = c.get("author") or {}
            login = author.get("login") or "ghost"
            typename = author.get("__typename")
            comments.append(
                Comment(
                    author_login=login,
                    author_is_bot=_is_bot(login, typename),
                    body=c.get("bodyText") or "",
                    created_at=_parse_iso(c["createdAt"]),
                )
            )

        linked_prs: list[LinkedPR] = []
        for item in node["timelineItems"]["nodes"]:
            src = (item or {}).get("source") or {}
            if src.get("__typename") != "PullRequest":
                continue
            pr_author = (src.get("author") or {}).get("login") or "ghost"
            linked_prs.append(
                LinkedPR(
                    number=src["number"],
                    url=src["url"],
                    state=src["state"],
                    author_login=pr_author,
                )
            )

        return IssueInfo(
            number=node["number"],
            title=node["title"],
            url=node["url"],
            labels=labels,
            assignees=assignees,
            assignee_is_bot_map=assignee_is_bot_map,
            comments=comments,
            linked_prs=linked_prs,
            is_closed=False,  # states: OPEN guarantees this
            repo_owner=owner,
            repo_name=repo,
        )


REST_BASE = "https://api.github.com"


class AnonymousRESTClient:
    """Lightweight unauthenticated client used as a fallback for new users.

    Calls the public REST API (rate limit 60/h) and assembles IssueInfo objects
    so the rest of the pipeline (claim_detector, formatters) is unchanged.
    """

    def __init__(self, *, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"issue-scout/{__version__}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def fetch_issues(
        self,
        owner: str,
        repo: str,
        labels: list[str] | None = None,
        max_issues: int = 50,
    ) -> list[IssueInfo]:
        labels = labels or []
        results: list[IssueInfo] = []
        page = 1
        while len(results) < max_issues:
            per_page = min(50, max_issues - len(results))
            params = {
                "state": "open",
                "per_page": per_page,
                "page": page,
                "sort": "created",
                "direction": "desc",
            }
            if labels:
                params["labels"] = ",".join(labels)
            payload = self._get(f"/repos/{owner}/{repo}/issues", params=params)
            if not payload:
                break
            for raw in payload:
                if raw.get("pull_request"):
                    continue  # REST returns PRs in /issues; skip them
                if len(results) >= max_issues:
                    break
                results.append(self._build_issue(raw, owner, repo))
            if len(payload) < per_page:
                break
            page += 1
        return results

    def _get(self, path: str, *, params: dict | None = None) -> list | dict:
        url = REST_BASE + path
        try:
            resp = self.session.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            raise NetworkError(f"Network error contacting GitHub: {e}") from e
        if resp.status_code == 404:
            raise GraphQLError(f"Not found: {path}")
        if resp.status_code == 403:
            body = resp.text.lower()
            if "rate limit" in body or resp.headers.get("X-RateLimit-Remaining") == "0":
                raise RateLimitError(
                    "Anonymous rate limit hit (60/h). Run 'issue-scout login' "
                    "or set GITHUB_TOKEN to raise the limit to 5000/h."
                )
            raise AuthError(f"GitHub returned 403: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise NetworkError(f"GitHub HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as e:
            raise NetworkError(f"Invalid JSON from GitHub: {e}") from e

    def _build_issue(self, raw: dict, owner: str, repo: str) -> IssueInfo:
        number = raw["number"]
        labels = [
            (lbl.get("name") if isinstance(lbl, dict) else lbl) for lbl in raw.get("labels", [])
        ]
        assignees = [a["login"] for a in raw.get("assignees", []) if a.get("login")]
        assignee_is_bot_map = {
            a: _is_bot(a, "Bot" if (raw_a.get("type") == "Bot") else None)
            for a, raw_a in zip(assignees, raw.get("assignees", []))
        }

        comments = self._fetch_comments(owner, repo, number)
        linked_prs = self._fetch_linked_prs(owner, repo, number)

        return IssueInfo(
            number=number,
            title=raw.get("title", ""),
            url=raw.get("html_url", ""),
            labels=[lbl for lbl in labels if lbl],
            assignees=assignees,
            assignee_is_bot_map=assignee_is_bot_map,
            comments=comments,
            linked_prs=linked_prs,
            is_closed=raw.get("state") == "closed",
            repo_owner=owner,
            repo_name=repo,
        )

    def _fetch_comments(self, owner: str, repo: str, number: int) -> list[Comment]:
        data = self._get(
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            params={"per_page": 10},
        )
        comments: list[Comment] = []
        if not isinstance(data, list):
            return comments
        for c in data:
            user = c.get("user") or {}
            login = user.get("login") or "ghost"
            typename = "Bot" if user.get("type") == "Bot" else None
            comments.append(
                Comment(
                    author_login=login,
                    author_is_bot=_is_bot(login, typename),
                    body=c.get("body") or "",
                    created_at=_parse_iso(c["created_at"]),
                )
            )
        return comments

    def _fetch_linked_prs(self, owner: str, repo: str, number: int) -> list[LinkedPR]:
        data = self._get(
            f"/repos/{owner}/{repo}/issues/{number}/timeline",
            params={"per_page": 30},
        )
        prs: list[LinkedPR] = []
        if not isinstance(data, list):
            return prs
        for event in data:
            if event.get("event") != "cross-referenced":
                continue
            src = event.get("source") or {}
            issue = src.get("issue") or {}
            if not issue.get("pull_request"):
                continue  # only PRs, not plain issues
            pr_url = issue.get("pull_request", {}).get("html_url") or issue.get("html_url", "")
            state = "OPEN"
            if issue.get("state") == "closed":
                # REST timeline doesn't tell us merged vs closed cheaply; fall back
                # to fetching the PR to distinguish. One extra call per closed link.
                pr_state = self._fetch_pr_state(owner, repo, issue.get("number"))
                state = pr_state or "CLOSED"
            user_login = (issue.get("user") or {}).get("login") or "ghost"
            prs.append(
                LinkedPR(
                    number=issue["number"],
                    url=pr_url,
                    state=state,
                    author_login=user_login,
                )
            )
        return prs

    def _fetch_pr_state(self, owner: str, repo: str, number: int | None) -> str | None:
        if not number:
            return None
        data = self._get(f"/repos/{owner}/{repo}/pulls/{number}")
        if not isinstance(data, dict):
            return None
        if data.get("merged"):
            return "MERGED"
        return "CLOSED"
