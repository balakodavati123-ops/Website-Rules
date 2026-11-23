"""The CEO's inbox: instructions arrive as GitHub issues whose title starts with "CEO", opened from buttons on the dashboard.

Only the repository owner's issues are obeyed (the repository is public, so anyone could open one); others are closed with a note.
Recognised titles: CEO APPROVE <request id>, CEO REJECT <request id>, CEO PAUSE <team>, CEO RESUME <team>, CEO CLOSE <trade id>; anything else is passed to the
COO as a note. The COO's reply is posted as a comment and the issue is closed.
"""
from __future__ import annotations

import json
import urllib.request

API = "https://api.github.com"


def _call(method: str, url: str, token: str, body: dict | None = None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "desk-bot", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read() or b"null")


def parse(title: str, body: str = "") -> dict | None:
    w = title.strip().split()
    if not w or w[0].upper().rstrip(":") != "CEO":
        return None
    verb = w[1].lower() if len(w) > 1 else "note"
    if verb in ("approve", "reject", "pause", "resume", "close") and len(w) > 2:
        return {"kind": verb, "arg": " ".join(w[2:])}
    return {"kind": "note", "arg": " ".join(w[1:]), "text": (" ".join(w[1:]) + (" — " + body.strip() if body and body.strip() else ""))[:500]}


def poll(token: str, repo: str, call=_call) -> list[dict]:
    """Open CEO issues as commands: [{kind, arg, text, issue, owner}]. Issues not opened by the owner come back with owner=False."""
    owner = repo.split("/")[0].lower()
    out = []
    for i in call("GET", f"{API}/repos/{repo}/issues?state=open&per_page=30", token) or []:
        if i.get("pull_request"):
            continue
        cmd = parse(i.get("title") or "", i.get("body") or "")
        if cmd:
            cmd.update(issue=i["number"], owner=(i.get("author_association") == "OWNER" or str((i.get("user") or {}).get("login", "")).lower() == owner))
            out.append(cmd)
    return out


def reply(token: str, repo: str, number: int, text: str, call=_call) -> None:
    call("POST", f"{API}/repos/{repo}/issues/{number}/comments", token, {"body": text + "\n\n---\n_Reply from the Balaji Trading Desk COO (automated)._"})
    call("PATCH", f"{API}/repos/{repo}/issues/{number}", token, {"state": "closed"})
