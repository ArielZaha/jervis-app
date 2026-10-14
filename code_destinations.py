"""Where finished code goes: VS Code, a folder, a Word document, Apple Notes, Google Drive, a zip.

Every destination is one entry in DESTINATIONS with two functions, so adding another editor or service is adding an
entry, not changing the coding engine (coder.py knows nothing in this file):

    available() -> (True, "") or (False, "why not, fit to say")
    deliver(project, files) -> {"ok": bool, "message": str, "location": str, "opened": bool}

`project` is the engine's record ({"name", "path", "language", "summary", "run", "test", "needs"}); `files` is
{relative path: text}. The real source files are always in project["path"] already: Word and Notes get a readable
copy for people, never instead of the files. A delivery only says "ok" when the app, the file system or the service
confirmed it; "opened" only when the app really was asked to open it and didn't refuse.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime

import osal
import paths

IS_MAC = sys.platform == "darwin"


def _result(ok: bool, message: str, location: str = "", opened: bool = False, **more) -> dict:
    return {"ok": ok, "message": message, "location": location, "opened": opened, **more}


def _run(argv: list, seconds: int = 30, stdin: str = None) -> tuple:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=seconds, input=stdin,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return done.returncode, (done.stdout or "").strip(), (done.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return None, "", str(e)


def _mac_app(*names):
    """The path of an installed Mac app by name, or None."""
    for name in names:
        for folder in ("/Applications", os.path.expanduser("~/Applications"), "/System/Applications"):
            path = os.path.join(folder, f"{name}.app")
            if os.path.isdir(path):
                return path
    return None


def _open_with(app_path: str, target: str) -> bool:
    return _run(["open", "-a", app_path, target])[0] == 0


def reveal(path: str) -> bool:
    """Show a file or folder in Finder / Explorer."""
    if IS_MAC:
        return _run(["open", path])[0] == 0
    if osal.IS_WIN:
        try:
            os.startfile(path)   # noqa: S606 (a folder Jarvis itself just made)
            return True
        except OSError:
            return False
    return _run(["xdg-open", path])[0] == 0


# ---------------------------------------------------------------- VS Code
def vscode_command():
    """How to start VS Code here: ("cli", path to `code`) or ("app", the Mac app), or None when it isn't installed."""
    cli = shutil.which("code") or shutil.which("code.cmd")
    if cli:
        return "cli", cli
    if IS_MAC:
        app = _mac_app("Visual Studio Code", "Visual Studio Code - Insiders", "VSCodium")
        if app:
            inside = os.path.join(app, "Contents", "Resources", "app", "bin", "code")
            return ("cli", inside) if os.path.exists(inside) else ("app", app)
    if osal.IS_WIN:
        for base in (os.getenv("LOCALAPPDATA", ""), os.getenv("ProgramFiles", "")):
            candidate = os.path.join(base, "Programs" if base == os.getenv("LOCALAPPDATA", "") else "", "Microsoft VS Code", "bin", "code.cmd")
            if base and os.path.exists(candidate):
                return "cli", candidate
    return None


def _vscode_available():
    return (True, "") if vscode_command() else (False, "Visual Studio Code isn't installed on this computer.")


def _vscode(project: dict, files: dict) -> dict:
    found = vscode_command()
    path = project["path"]
    if not found:
        return _result(False, f"Visual Studio Code isn't installed on this computer, so I couldn't open it there. The project is saved in {path}.", path)
    kind, command = found
    entry = next((p for p in files if os.path.basename(p).lower() not in ("readme.md", ".gitignore")), None)
    if kind == "cli":
        argv = [command, path] + ([os.path.join(path, entry)] if entry else [])
        code, _out, err = _run(argv, seconds=40)
        ok = code == 0
    else:
        ok, err = _open_with(command, path), ""
    if not ok:
        return _result(False, f"The project is saved in {path}, but Visual Studio Code didn't open it" + (f" ({err[:120]})." if err else "."), path)
    return _result(True, f"It's open in Visual Studio Code. The project folder is {path}.", path, opened=True)


# ---------------------------------------------------------------- a folder on this computer
def _local(project: dict, files: dict) -> dict:
    path = project["path"]
    opened = reveal(path)
    return _result(True, f"The project is saved in {path}." + ("" if opened else " I couldn't open the folder for you."), path, opened=opened)


def _zip(project: dict, files: dict) -> dict:
    path = project["path"]
    target = os.path.join(os.path.dirname(path), f"{os.path.basename(path)}.zip")
    n = 2
    while os.path.exists(target):   # an earlier archive is kept, never overwritten
        target = os.path.join(os.path.dirname(path), f"{os.path.basename(path)}-{n}.zip")
        n += 1
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for rel in sorted(files):
                archive.write(os.path.join(path, rel), os.path.join(os.path.basename(path), rel))
    except (OSError, zipfile.BadZipFile) as e:
        return _result(False, f"I couldn't make the zip file: {e}", path)
    return _result(True, f"The whole project is in {target}.", target, opened=reveal(os.path.dirname(target)))


# ---------------------------------------------------------------- a Word document (.docx written here, no Word needed to make it)
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                  '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                  '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                  '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                  '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
         '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
_DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
_STYLES = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {_W}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:b/><w:sz w:val="48"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:color w:val="5A6472"/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:keepNext/><w:spacing w:before="360" w:after="100"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:keepNext/><w:spacing w:before="280" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/><w:b/><w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:pPr><w:shd w:val="clear" w:color="auto" w:fill="F3F5F8"/><w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="120" w:right="120"/></w:pPr>
<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Courier New" w:eastAsia="Consolas"/><w:noProof/><w:sz w:val="18"/></w:rPr></w:style>
</w:styles>'''


def _docx_text(text: str) -> str:
    return html.escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text), quote=False)


def _docx_paragraph(text: str, style: str = "") -> str:
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{props}<w:r><w:t xml:space="preserve">{_docx_text(text)}</w:t></w:r></w:p>'


def _docx_code(code: str) -> str:
    """One paragraph per line, in the Code style; a tab is kept as a real tab and every space is preserved."""
    out = []
    for line in code.rstrip("\n").split("\n"):
        runs = "".join("<w:r><w:tab/></w:r>" if piece == "\t" else f'<w:r><w:t xml:space="preserve">{_docx_text(piece)}</w:t></w:r>'
                       for piece in re.split(r"(\t)", line) if piece)
        out.append(f'<w:p><w:pPr><w:pStyle w:val="Code"/></w:pPr>{runs}</w:p>')
    return "".join(out)


def build_docx(target: str, project: dict, files: dict) -> None:
    """Write a .docx: a title, what it is and how to run it, then every file under its own path, in a monospaced face."""
    import coder
    body = [_docx_paragraph(project.get("title") or project["name"], "Title"),
            _docx_paragraph(" · ".join(p for p in (project.get("language", ""), f"{len(files)} file{'s' if len(files) != 1 else ''}",
                                                    datetime.now().strftime("%B %d, %Y").replace(" 0", " ")) if p), "Subtitle")]
    if project.get("summary"):
        body.append(_docx_paragraph(project["summary"]))
    for label, key in (("Run it with", "run"), ("Test it with", "test"), ("Needs", "needs")):
        if project.get(key):
            body.append(_docx_paragraph(f"{label}: {project[key]}"))
    body.append(_docx_paragraph("This document is for reading. The files themselves are in " + project["path"] + "."))
    body.append(_docx_paragraph("Files" if len(files) != 1 else "The code", "Heading1"))
    for rel in sorted(files, key=lambda p: (p.count("/"), p.lower())):
        language = coder.LANGUAGES.get(coder.language_of_file(rel) or "")
        body.append(_docx_paragraph(rel + (f"   ({language.name})" if language else ""), "Heading2"))
        body.append(_docx_code(files[rel]))
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W}><w:body>{"".join(body)}'
                '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1200" w:right="1200" w:bottom="1200" w:left="1200" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
                '</w:body></w:document>')
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_docx_text(project["name"])}</dc:title><dc:creator>Jarvis</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("docProps/core.xml", core)


def docx_lines(path: str) -> list:
    """The text of every paragraph of a .docx, tabs and spaces intact (used to prove indentation survived)."""
    import xml.etree.ElementTree as ET
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for paragraph in root.iter(f"{ns}p"):
        lines.append("".join("\t" if node.tag == f"{ns}tab" else (node.text or "") for node in paragraph.iter() if node.tag in (f"{ns}t", f"{ns}tab")))
    return lines


def _word(project: dict, files: dict) -> dict:
    target = os.path.join(project["path"], f"{project['name']}.docx")
    n = 2
    while os.path.exists(target):
        target = os.path.join(project["path"], f"{project['name']}-{n}.docx")
        n += 1
    try:
        build_docx(target, project, files)
    except (OSError, zipfile.BadZipFile) as e:
        return _result(False, f"I couldn't write the Word document: {e}", project["path"])
    opened = False
    if IS_MAC:
        app = _mac_app("Microsoft Word")
        opened = bool(app) and _open_with(app, target)
    elif osal.IS_WIN:
        try:
            os.startfile(target)   # noqa: S606 (a document Jarvis itself just wrote)
            opened = True
        except OSError:
            opened = False
    where = f"The Word document is {target}; the real files are in the same folder."
    if opened:
        return _result(True, "It's open in Word. " + where, target, opened=True)
    return _result(True, "Microsoft Word isn't installed here, so I didn't open it. " + where if IS_MAC and not _mac_app("Microsoft Word")
                   else "I couldn't open it in Word. " + where, target)


# ---------------------------------------------------------------- Apple Notes
_NOTES_NEW = '''on run argv
    tell application "Notes"
        set n to make new note with properties {name:(item 1 of argv), body:(item 2 of argv)}
        return id of n
    end tell
end run'''
_NOTES_READ = '''on run argv
    tell application "Notes" to return plaintext of (first note whose id is (item 1 of argv))
end run'''


def _notes_available():
    if not IS_MAC:
        return False, "Apple Notes only exists on a Mac."
    return (True, "") if _mac_app("Notes") else (False, "The Notes app isn't on this Mac.")


def notes_html(project: dict, files: dict) -> str:
    """The note's body. Notes keeps a monospaced face and line breaks but collapses ordinary spaces, so every leading
    space is a non-breaking one and a tab becomes four of them: the indentation you see is the indentation in the file."""
    def code(text: str) -> str:
        lines = []
        for line in text.rstrip("\n").split("\n"):
            line = line.replace("\t", "    ")
            indent = len(line) - len(line.lstrip(" "))
            lines.append("&nbsp;" * indent + html.escape(line[indent:]).replace("  ", " &nbsp;") or "<br>")
        return "".join(f'<div><font face="Menlo" size="2">{line or "<br>"}</font></div>' for line in lines)
    parts = [f"<h1>{html.escape(project.get('title') or project['name'])}</h1>"]
    if project.get("summary"):
        parts.append(f"<div>{html.escape(project['summary'])}</div>")
    for label, key in (("Run it with", "run"), ("Test it with", "test"), ("Needs", "needs")):
        if project.get(key):
            parts.append(f"<div>{label}: {html.escape(project[key])}</div>")
    parts.append(f"<div>The files themselves are in {html.escape(project['path'])}.</div><div><br></div>")
    for rel in sorted(files, key=lambda p: (p.count("/"), p.lower())):
        parts.append(f"<div><b>{html.escape(rel)}</b></div>{code(files[rel])}<div><br></div>")
    return "".join(parts)


def _notes(project: dict, files: dict) -> dict:
    ok, why = _notes_available()
    if not ok:
        return _result(False, f"{why} The project is saved in {project['path']}.", project["path"])
    body = notes_html(project, files)
    if len(body) > 900_000:
        return _result(False, f"That is too much code for one note. The project is saved in {project['path']}.", project["path"])
    code, note_id, err = _run(["osascript", "-e", _NOTES_NEW, project.get("title") or project["name"], body], seconds=40)
    if code != 0 or not note_id:
        denied = "-1743" in err or "not allowed" in err.lower() or "not authorized" in err.lower()
        return _result(False, ("Jarvis isn't allowed to use Notes yet: allow it in System Settings, Privacy & Security, Automation, then ask again. "
                               if denied else f"Notes didn't make the note ({err[:140] or 'no answer'}). ") + f"The project is saved in {project['path']}.", project["path"])
    _run(["osascript", "-e", 'tell application "Notes" to activate'])
    return _result(True, f"It's in a new note called {project.get('title') or project['name']}. Notes shows code in a plain monospaced face without colours; "
                         f"the real files are in {project['path']}.", "Notes", opened=True, note_id=note_id)


def notes_text(note_id: str) -> str:
    """A note's text as Notes holds it (to check that the code arrived with its indentation)."""
    return _run(["osascript", "-e", _NOTES_READ, note_id], seconds=30)[1]


# ---------------------------------------------------------------- Google Drive (only files Jarvis creates: the drive.file permission)
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_TOKEN = os.path.join(paths.DATA_DIR, ".drive_token.json")
DRIVE_SETUP = ("Google Drive isn't connected yet. It needs a Google sign-in set up for Jarvis: add GOOGLE_DRIVE_CLIENT_ID and "
               "GOOGLE_DRIVE_CLIENT_SECRET to the .env file (a free \"Desktop app\" OAuth client from Google Cloud Console, with the "
               "Google Drive API switched on; the Calendar ones are used if those are already there), then choose Connect Google Drive.")


class DriveUnavailable(Exception):
    """Drive isn't set up, sign-in failed, or Google refused; the message is fit to say."""


def _drive_client():
    for prefix in ("GOOGLE_DRIVE", "GOOGLE_CALENDAR"):
        client_id, secret = (os.getenv(f"{prefix}_CLIENT_ID") or "").strip(), (os.getenv(f"{prefix}_CLIENT_SECRET") or "").strip()
        if client_id and secret:
            return {"installed": {"client_id": client_id, "client_secret": secret, "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                  "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": ["http://localhost"]}}
    return None


def drive_status() -> str:
    """"connected" (a saved sign-in exists), "ready" (set up, never signed in) or "not_set_up"."""
    if not _drive_client():
        return "not_set_up"
    return "connected" if os.path.exists(DRIVE_TOKEN) else "ready"


def drive_credentials(interactive: bool = False):
    """A valid Google sign-in for Drive. interactive: may open the browser for the one-time consent; otherwise a
    missing or dead sign-in is an error (uploading must never pop a browser window on its own)."""
    config = _drive_client()
    if not config:
        raise DriveUnavailable(DRIVE_SETUP)
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = None
    if os.path.exists(DRIVE_TOKEN):
        try:
            creds = Credentials.from_authorized_user_file(DRIVE_TOKEN, DRIVE_SCOPES)
        except (ValueError, OSError):
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_drive_token(creds)
            return creds
        except Exception:
            creds = None   # revoked or expired for good: a fresh sign-in is needed
    if not interactive:
        raise DriveUnavailable("Google Drive needs you to sign in first: choose Connect Google Drive in Coding Mode.")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_config(config, DRIVE_SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=180,
                                       authorization_prompt_message="Sign in to Google Drive in the browser tab that just opened.",
                                       success_message="Google Drive is connected. You can close this tab and go back to Jarvis.")
    except Exception as e:
        raise DriveUnavailable(f"I couldn't sign in to Google Drive: {type(e).__name__}")
    _save_drive_token(creds)
    return creds


def _save_drive_token(creds) -> None:
    try:
        with open(DRIVE_TOKEN, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        os.chmod(DRIVE_TOKEN, 0o600)
    except OSError:
        pass


def _drive_call(session, method: str, url: str, **kwargs) -> dict:
    """One Drive request; the reply as a dict, or DriveUnavailable saying what Google answered (never the token)."""
    try:
        response = session.request(method, url, timeout=60, **kwargs)
    except Exception as e:
        raise DriveUnavailable(f"I couldn't reach Google Drive ({type(e).__name__}).")
    if response.status_code >= 300:
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        raise DriveUnavailable(f"Google Drive refused ({response.status_code}{': ' + detail[:160] if detail else ''}).")
    try:
        return response.json()
    except ValueError:
        raise DriveUnavailable("Google Drive answered with something I couldn't read.")


def drive_upload(project: dict, files: dict, session=None) -> dict:
    """Create the project in Drive: one file as itself, several inside a new folder with their sub-folders. Returns
    {"link", "count", "folder"} only from what Drive confirmed (each created id)."""
    if session is None:
        import requests
        creds = drive_credentials()
        session = requests.Session()
        session.headers["Authorization"] = f"Bearer {creds.token}"
    api, upload = "https://www.googleapis.com/drive/v3/files", "https://www.googleapis.com/upload/drive/v3/files"

    def folder(name: str, parent: str = "") -> dict:
        meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", **({"parents": [parent]} if parent else {})}
        made = _drive_call(session, "POST", api, params={"fields": "id,webViewLink"}, json=meta)
        if not made.get("id"):
            raise DriveUnavailable("Google Drive didn't confirm the new folder.")
        return made

    def put(name: str, text: str, parent: str = "") -> dict:
        meta = {"name": name, **({"parents": [parent]} if parent else {})}
        boundary = "jarvis-code-upload"
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
                f"--{boundary}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n").encode() + text.encode("utf-8") + f"\r\n--{boundary}--".encode()
        made = _drive_call(session, "POST", upload, params={"uploadType": "multipart", "fields": "id,webViewLink"}, data=body,
                           headers={"Content-Type": f"multipart/related; boundary={boundary}"})
        if not made.get("id"):
            raise DriveUnavailable(f"Google Drive didn't confirm {name}.")
        return made

    if len(files) == 1:
        (rel, text), = files.items()
        made = put(os.path.basename(rel), text)
        return {"link": made.get("webViewLink", ""), "count": 1, "folder": False}
    root = folder(project["name"])
    folders = {"": root["id"]}
    for rel in sorted(files):
        parent, built = "", ""
        for part in rel.split("/")[:-1]:
            built = f"{built}/{part}" if built else part
            if built not in folders:
                folders[built] = folder(part, folders[parent])["id"]
            parent = built
        put(os.path.basename(rel), files[rel], folders[parent])
    return {"link": root.get("webViewLink", ""), "count": len(files), "folder": True}


def _gdrive_available():
    status = drive_status()
    if status == "not_set_up":
        return False, DRIVE_SETUP
    return (True, "") if status == "connected" else (False, "Google Drive needs you to sign in first: choose Connect Google Drive in Coding Mode.")


def _gdrive(project: dict, files: dict) -> dict:
    try:
        made = drive_upload(project, files)
    except DriveUnavailable as e:
        return _result(False, f"{e} The project is saved on this computer, in {project['path']}.", project["path"])
    what = f"a folder called {project['name']} with {made['count']} files" if made["folder"] else "a file"
    return _result(True, f"It's in your Google Drive as {what}. A copy is on this computer too, in {project['path']}.", made["link"] or "Google Drive",
                   opened=False, link=made["link"])


# ---------------------------------------------------------------- the list
DESTINATIONS = {
    "vscode": {"name": "VS Code", "about": "A project folder, opened in Visual Studio Code", "available": _vscode_available, "deliver": _vscode},
    "local": {"name": "Local files", "about": "A project folder on this computer", "available": lambda: (True, ""), "deliver": _local},
    "word": {"name": "Word", "about": "A .docx to read or share, beside the real files", "available": lambda: (True, ""), "deliver": _word},
    "notes": {"name": "Notes", "about": "A new note in Apple Notes, beside the real files", "available": _notes_available, "deliver": _notes},
    "gdrive": {"name": "Google Drive", "about": "The files in your Drive, as a new folder", "available": _gdrive_available, "deliver": _gdrive},
    "zip": {"name": "Zip", "about": "The whole project as one .zip", "available": lambda: (True, ""), "deliver": _zip},
}
SPOKEN = {"vscode": "VS Code", "local": "a folder on this computer", "word": "a Word document", "notes": "Apple Notes", "gdrive": "Google Drive", "zip": "a zip file"}


def describe() -> list:
    """What the destination picker shows: every destination, and for one that can't be used now, why (in a few words
    for the list, and in full as "help")."""
    out = []
    for key, entry in DESTINATIONS.items():
        ok, why = entry["available"]()
        short = "Not set up yet: it needs a Google sign-in in the .env file." if why == DRIVE_SETUP else why
        out.append({"key": key, "name": entry["name"], "about": entry["about"], "available": ok, "why": short, "help": why})
    return out


def deliver(key: str, project: dict, files: dict) -> dict:
    entry = DESTINATIONS.get(key)
    if not entry:
        return _result(False, f"I don't know a place called {key}. The project is saved in {project['path']}.", project["path"])
    try:
        return entry["deliver"](project, files)
    except Exception as e:   # a destination's bug must not lose the report of what was written
        print(f"Delivering to {key} failed: {e!r}", flush=True)
        return _result(False, f"Something went wrong sending it to {entry['name']} ({type(e).__name__}). The project is saved in {project['path']}.", project["path"])
