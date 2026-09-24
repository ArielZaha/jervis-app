"""Google Classroom: open it in the learning account and report the work that has not been turned in.

Classroom is read the way a person would: its "Missing" and "Assigned" to-do pages are opened in the school Chrome profile
and the assignments listed there are read from the page. (The Classroom API is not used because school accounts usually
block third-party apps.) On macOS this needs Chrome's  View > Developer > Allow JavaScript from Apple Events  switched on
for the school profile; without it the page is still opened and shown, and Jervis says how to turn that on.
"""
import json
import os
import time

import chrome_profiles
import google_accounts
import paths

MISSING_URL = "https://classroom.google.com/a/missing/all"    # overdue work that was not turned in
ASSIGNED_URL = "https://classroom.google.com/a/not-turned-in/all"  # work that is assigned and not turned in yet
MAX_LISTED = 8

# Every assignment in Classroom's lists is a link like /c/<class>/a/<assignment>/details; its list row holds the title,
# the class and the due date as separate lines of text.
EXTRACT_JS = r"""(function () {
  var u = location.href;
  if (location.hostname.indexOf('accounts.google') >= 0) return JSON.stringify({state: 'signin', url: u});
  var seen = {}, items = [];
  document.querySelectorAll('a[href*="/c/"]').forEach(function (a) {
    var found = /\/c\/[^\/]+\/a\/[^\/?#]+/.exec(a.getAttribute('href') || '');
    if (!found || seen[found[0]]) return;
    seen[found[0]] = 1;
    var row = a.closest('li,[role=listitem],[role=row]') || a;
    var lines = (row.innerText || '').split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
    items.push({lines: lines.slice(0, 6)});
  });
  var body = (document.body && document.body.innerText) || '';
  return JSON.stringify({state: 'page', url: u, title: document.title, count: items.length,
                         items: items.slice(0, 40), length: body.length, text: body.slice(0, 1500)});
})()"""


def read_page(ids, wait: float = 16.0, poll: float = 1.5) -> dict:
    """Read the assignments of the Classroom page open in a tab, waiting for the page to finish loading.

    Returns {"ok": True, "items": [[lines...]], "text": page text} or {"ok": False, "reason": "js-disabled" | "signin" | ...}."""
    deadline, started = time.time() + wait, time.time()
    last, steady = None, 0
    while True:
        ok, value = chrome_profiles.run_js(ids, EXTRACT_JS)
        if not ok:
            return {"ok": False, "reason": value}
        try:
            page = json.loads(value)
        except ValueError:
            page = {"state": "loading", "items": [], "length": 0}
        if page.get("state") == "signin":
            return {"ok": False, "reason": "signin"}
        signature = (page.get("count", 0), page.get("length", 0))
        steady = steady + 1 if signature == last else 0
        last = signature
        settled = steady >= 1 and (page.get("count", 0) > 0 or (page.get("length", 0) > 300 and time.time() - started >= 6))
        if settled or time.time() >= deadline:
            items = [item.get("lines", []) for item in page.get("items", []) if item.get("lines")]
            return {"ok": True, "items": items, "text": page.get("text", ""), "loaded": page.get("length", 0) > 300,
                    "url": page.get("url", "")}
        time.sleep(poll)


def _save_debug(result: dict) -> None:
    """Keep what was read (logs/classroom_last.json), so a wrong answer can be looked at and the reading refined."""
    try:
        folder = paths.logs_dir()
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "classroom_last.json"), "w", encoding="utf-8") as f:
            json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S"), **result}, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _open_learning(url: str):
    """Open a Classroom page in the school profile. Returns the tab's ids (None if it couldn't be identified)."""
    chrome_profiles.last_tab["ids"] = None
    google_accounts.open_page(url, "classroom homework", force_kind="learning")
    return chrome_profiles.last_tab["ids"]


def check_unsubmitted() -> dict:
    """Open Classroom and read the missing and the assigned-but-not-turned-in work.

    Returns {"status": "ok" | "opened" | "js-disabled" | "signin" | "unsupported", "missing": [...], "assigned": [...]},
    where each work item is the list of text lines Classroom shows for it (title, class, due date)."""
    if chrome_profiles.SYSTEM != "Darwin":
        google_accounts.open_page(MISSING_URL, "classroom homework", force_kind="learning")
        return {"status": "unsupported", "missing": [], "assigned": []}
    ids = _open_learning(ASSIGNED_URL)
    if not ids:
        return {"status": "opened", "missing": [], "assigned": []}
    assigned = read_page(ids)
    if not assigned["ok"]:
        return {"status": assigned["reason"] if assigned["reason"] in ("js-disabled", "signin") else "opened",
                "missing": [], "assigned": []}
    account = google_accounts.account_for("classroom.google.com", "classroom", "learning")
    chrome_profiles.goto(ids, google_accounts.with_account(MISSING_URL, account) if account else MISSING_URL)
    time.sleep(1.0)
    missing = read_page(ids)
    result = {"status": "ok" if missing["ok"] else "opened",
              "missing": missing.get("items", []), "assigned": assigned["items"],
              "missing_loaded": missing.get("loaded", False), "assigned_loaded": assigned.get("loaded", False),
              "missing_text": missing.get("text", ""), "assigned_text": assigned.get("text", "")}
    _save_debug(result)
    return result


def _describe(lines: list) -> str:
    """One work item in words: its title, then the class and due date lines, without repeats."""
    parts, seen = [], set()
    for line in lines[:3]:
        key = line.lower()
        if key not in seen:
            seen.add(key)
            parts.append(line if len(line) <= 90 else line[:87] + "...")
    return ", ".join(parts)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _list(items: list) -> str:
    shown = [f"- {_describe(item)}" for item in items[:MAX_LISTED]]
    if len(items) > MAX_LISTED:
        shown.append(f"- and {len(items) - MAX_LISTED} more")
    return "\n".join(shown)


def summary(result: dict) -> str:
    status = result["status"]
    if status == "unsupported":
        return "I opened Google Classroom for you. Reading your assignments only works on a Mac for now, so check the Missing tab there."
    if status == "js-disabled":
        return ("I opened Classroom, but Chrome won't let me read the page yet. In Chrome, open the View menu, then Developer, "
                "and turn on Allow JavaScript from Apple Events. Do that in the school profile window, then ask me again.")
    if status == "signin":
        return "I opened Classroom, but it is asking you to sign in. Sign in there, then ask me again."
    if status == "opened":
        return "I opened Google Classroom for you, but I couldn't read the assignments from the page. Check the Missing tab there."
    missing, assigned = result["missing"], result["assigned"]
    if not missing and not assigned:
        if not (result.get("missing_loaded") and result.get("assigned_loaded")):
            return "I opened Google Classroom, but the page hadn't finished loading, so I couldn't read it. Ask me again in a moment."
        return "I don't see any missing work or anything left to turn in on Google Classroom."
    lines = []
    if missing:
        lines.append(f"You have {_plural(len(missing), 'missing assignment')} on Google Classroom, work that is overdue and not turned in:\n{_list(missing)}")
    else:
        lines.append("You have no missing assignments on Google Classroom.")
    if assigned:
        lines.append(f"And {_plural(len(assigned), 'assignment')} still to turn in:\n{_list(assigned)}")
    return "\n\n".join(lines)
