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
