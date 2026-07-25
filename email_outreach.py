"""Cold-email draft generation from 00_saved/email-list.md.

The list is a markdown table (email / company / url / role / notes). Company
name resolution: the table column is authoritative; when empty, it is guessed
from the email's domain — corporate domains only, freemail providers cannot
name a company. Drafts are template fills (career/email/<role>.md,
mirroring career/cover-letter/'s per-role files — falls back to general.md),
no LLM: outreach mail must be short, factual, and entirely the sender's own
words.

Output: 10_output/30_emails/<Company>_email.md (skipped if it already exists,
so hand-edited drafts are never clobbered — delete a draft to regenerate it).
"""
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EMAIL_LIST = ROOT / "00_saved" / "email-list.md"
TEMPLATE_DIR = ROOT.parent / "email"
SIGNATURE_PATH = TEMPLATE_DIR / "_signature.md"
OUT_DIR = ROOT / "10_output" / "30_emails"
PROFILE_DIR = ROOT.parent / "cv" / "profile"


def _normalize_role(role: str) -> str:
    """email-list.md's ロール column is free text ("Product Designer"), but
    profile/email-template filenames are snake_case ("product_designer.md") —
    an exact-string lookup on the raw text never matches even when the right
    profile exists, and silently falls back to general.md with no warning.
    Slugify so casing/spacing differences stop mattering; a role with no
    matching file (e.g. "Web Designer", no web_designer.md) still falls back
    to general — that part is unavoidable without a role→profile alias
    table, but at least a real match is no longer missed by accident."""
    slug = re.sub(r"[^a-z0-9]+", "_", role.strip().lower()).strip("_")
    return slug or "general"


def resolved_profile(role: str) -> str:
    """Which profile role_type generate_outreach_cv/generate_draft will
    actually use for this role text — "general" whenever no matching
    profile file exists, so the UI can show the fallback instead of hiding
    it."""
    slug = _normalize_role(role)
    return slug if (PROFILE_DIR / f"{slug}.md").exists() else "general"

FREEMAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com",
    "yahoo.co.uk", "icloud.com", "me.com", "proton.me", "protonmail.com",
    "aol.com", "live.com", "msn.com", "mail.com", "gmx.com", "zoho.com",
}
# Registrable-suffix parts that are never the company name (papertiger.co.uk
# → "papertiger", not "co").
_SUFFIX_PARTS = {"co", "com", "org", "net", "ac", "gov", "ltd", "plc", "io", "uk", "scot"}


def guess_company(email: str) -> str | None:
    """Company name from a corporate email domain, None when impossible."""
    domain = email.rsplit("@", 1)[-1].lower().strip()
    if not domain or domain in FREEMAIL:
        return None
    parts = [p for p in domain.split(".") if p and p not in _SUFFIX_PARTS]
    if not parts:
        return None
    # widest label = most name-like ("mail.papertiger.co.uk" → "papertiger")
    label = max(parts, key=len)
    return re.sub(r"[-_]+", " ", label).title()


# Table header cells → row dict keys. Matched by substring so column order
# and exact Japanese wording in email-list.md can change freely.
_HEADER_MAP = [
    ("メール", "email"), ("email", "email"), ("mail", "email"),
    ("会社", "company"), ("company", "company"),
    ("url", "url"),
    ("ロール", "role"), ("role", "role"),
    ("下書き", "draft"), ("draft", "draft"),
    ("cv", "cv"),
    ("メモ", "notes"), ("notes", "notes"),
]


def _detect_columns(header_line: str) -> dict[int, str] | None:
    cells = [c.strip().lower() for c in header_line.strip().strip("|").split("|")]
    cols = {}
    for i, cell in enumerate(cells):
        for needle, key in _HEADER_MAP:
            if needle in cell:
                cols[i] = key
                break
    return cols if "email" in cols.values() else None


def parse_email_list(path: Path = EMAIL_LIST) -> list[dict]:
    """Rows from the markdown table: [{email, company, url, role, notes,
    company_guessed}]. Columns are located by header text, not position, so
    reordering the table (e.g. company before email) does not break parsing.
    Rows without an @ in the email column are ignored; company falls back to
    a domain guess when left blank. role is slugified (_normalize_role) so
    it can be used directly as a profile/email-template lookup key — use
    resolved_profile(row["role"]) to see whether it actually matched a file
    or will fall back to general."""
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return rows
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    cols: dict[int, str] | None = None
    for line in text.splitlines():
        if "|" not in line:
            continue
        if re.fullmatch(r"[|\-:\s]+", line.strip()):
            continue  # markdown header separator row (---|---|---)
        if cols is None:
            cols = _detect_columns(line)
            continue  # this line IS the header — never a data row

        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        by_key = {key: (cells[i] if i < len(cells) else "") for i, key in cols.items()}
        # The email cell may be a markdown/mailto link, e.g.
        # "[a@b.com](mailto:a@b.com)" — Obsidian renders bare addresses that
        # way. Extract the bare address so downstream matching and domain
        # guessing see a clean email, not markup.
        m = re.search(r"[\w.+-]+@[\w.-]+", by_key.get("email", ""))
        if not m:
            continue
        email = m.group(0)
        company = by_key.get("company", "")
        guessed = False
        if not company:
            g = guess_company(email)
            if g:
                company, guessed = g, True
        rows.append({
            "email": email,
            "company": company,
            "url": by_key.get("url", ""),
            "role": _normalize_role(by_key.get("role", "") or "general"),
            "notes": by_key.get("notes", ""),
            "company_guessed": guessed,
        })
    return rows


def draft_path(row: dict) -> Path | None:
    """Where generate_draft(row) would write/find this row's file — usable
    before generation to check whether a draft already exists."""
    if not row["company"]:
        return None
    from matcher import make_safe_name
    return OUT_DIR / f"{make_safe_name(row['company'], 'email')}.md"


CV_OUT_DIR = ROOT / "10_output" / "31_outreach_cvs"


def outreach_cv_path(row: dict) -> Path | None:
    """Where generate_outreach_cv(row) would write/find this row's CV .md."""
    if not row["company"]:
        return None
    from matcher import make_safe_name
    return CV_OUT_DIR / f"{make_safe_name(row['company'], 'cv')}_CV.md"


def _stamp_fingerprint(text: str, stamp_line: str) -> str:
    """Insert/replace the gen_fingerprint line inside a doc's frontmatter —
    same stamping regen_top_docs applies to scrape-route CVs, so outreach CVs
    carry a comparable staleness marker."""
    if not text.startswith("---"):
        return text
    if re.search(r"^gen_fingerprint:.*$", text, re.MULTILINE):
        return re.sub(r"^gen_fingerprint:.*$", stamp_line, text, count=1, flags=re.MULTILINE)
    m = re.search(r"\n---\s*\n", text)
    if not m:
        return text
    return text[:m.start()] + f"\n{stamp_line}" + text[m.start():]


def generate_outreach_cv(row: dict, force: bool = False) -> tuple[Path | None, str]:
    """Generic (non-job-specific) CV for a speculative-application row.

    There is no job posting here — only a company and a role — so this
    skips everything that needs one: job-tailored experience ordering, match
    scoring, and review. generate_cv() already degrades to its static,
    role-appropriate project list when job_description is empty, which is
    exactly the generic CV this needs. Returns (path, status): 'created',
    'exists', or an error string; path is None on error.

    Staleness, not just existence, decides a skip: an existing CV is kept only
    when its stamped gen_fingerprint still matches the current generation spec
    (gen_version). Change the CV template/logic (bump GEN_SPEC_VERSION) or the
    source data (projects/*.md, profiles, skills, …) and the fingerprint moves,
    so the next run rebuilds these outreach CVs in lockstep with the
    scrape-route CVs instead of leaving them frozen at an old version.
    force=True rebuilds regardless.
    """
    if not row["company"]:
        return None, "会社名なし"

    out = outreach_cv_path(row)
    import gen_version
    # Use the RESOLVED profile (general when the row's role has no profile file)
    # for both generation and the fingerprint, so the two always agree.
    role = resolved_profile(row["role"])
    if out.exists() and not force:
        try:
            if gen_version.is_current(out.read_text(encoding="utf-8"), role):
                return out, "exists"
        except Exception:
            pass  # unreadable/unstamped → treat as stale, rebuild

    from cv_generator import generate_cv
    # job_title left blank (there is no posting); frontmatter's match_report/
    # cover_letter links stay empty by design — neither exists for this row.
    cv = generate_cv(role_type=role, job_title="Speculative Application",
                     company=row["company"], job_description="")
    cv = _stamp_fingerprint(cv, gen_version.stamp_line(role))

    CV_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(cv, encoding="utf-8")
    return out, "created"


def generate_draft(row: dict, force: bool = False) -> tuple[Path | None, str]:
    """Render one draft using the role's own template (career/email-template/
    <role>.md), falling back to general.md — same convention as cv/cover-letter
    per-role files. Returns (path, status): 'created', 'exists', or an error
    string; path is None on error.

    force=True overwrites an existing draft — use only for the explicit
    "作り直す" action, never the default "生成" button: a hand-edited draft
    (company-specific tweaks made directly in Obsidian) must survive a normal
    re-click, or every template iteration silently destroys that editing."""
    if not row["company"]:
        return None, "会社名なし (フリーメールで推定不可 — 表に記入してください)"

    role = row["role"] or "general"
    tpl_path = TEMPLATE_DIR / f"{role}.md"
    if not tpl_path.exists():
        tpl_path = TEMPLATE_DIR / "general.md"
    try:
        tpl = tpl_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, f"テンプレートなし: {tpl_path}"
    template = tpl_path.stem

    from cv_generator import get_header
    role_title, role_tagline = get_header(row["role"])

    body = re.sub(r"\A---\n.*?\n---\n", "", tpl, flags=re.DOTALL)
    m = re.search(r'^subject:\s*"(.*?)"', tpl, flags=re.MULTILINE)
    subject = (m.group(1) if m else "Speculative application — {company}")

    try:
        signature = SIGNATURE_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        signature = "Kazuki Yunomé"

    fills = {
        "company": row["company"],
        "role_title": role_title,
        "role_tagline": role_tagline,
        # HTML comments are invisible in Obsidian's markdown preview and in
        # any plain-text reading of the draft, but mark the signature's exact
        # extent so save_imap_draft can render it as a distinct styled block
        # (dark card) instead of just another paragraph of body text.
        "signature": f"<!--SIG-->{signature}<!--/SIG-->",
    }
    for k, v in fills.items():
        subject = subject.replace("{%s}" % k, v)
        body = body.replace("{%s}" % k, v)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = draft_path(row)
    if out.exists() and not force:
        return out, "exists"

    guessed_note = " (ドメインから推定 — 送信前に確認)" if row["company_guessed"] else ""
    front = f"""---
type: email_draft
to: "{row['email']}"
company: "{row['company']}{guessed_note}"
url: "{row['url']}"
role: "{row['role']}"
subject: "{subject}"
template: "{template}"
created: {date.today().isoformat()}
status: draft
---

# To: {row['email']}
# Subject: {subject}

"""
    out.write_text(front + body.strip() + "\n", encoding="utf-8")
    return out, "created"


def generate_all(force: bool = False) -> list[tuple[dict, Path | None, str]]:
    return [(r, *generate_draft(r, force=force)) for r in parse_email_list()]


_LINK_COLUMN_SPECS = [
    ("draft", "下書き", draft_path),
    ("cv", "CV", outreach_cv_path),
]


def link_outputs_into_list(path: Path = EMAIL_LIST) -> bool:
    """Add/update 下書き and CV columns in email-list.md with Obsidian
    wikilinks to each row's generated draft / outreach CV, matched by email
    address. Only touches the header row (inserts either column if missing)
    and existing data rows' draft/CV cells — every other cell, and any
    non-table content (prose, comments, blank lines), is copied through
    byte-for-byte. Returns False (no write) when the table can't be safely
    located, so a hand-edited file is never risked.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False

    lines = text.splitlines(keepends=True)
    header_idx = sep_idx = None
    cols: dict[int, str] | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "|" not in stripped:
            continue
        if re.fullmatch(r"[|\-:\s]+", stripped):
            if header_idx is not None and sep_idx is None:
                sep_idx = i
            continue
        if header_idx is None:
            detected = _detect_columns(stripped)
            if detected is not None:
                header_idx, cols = i, detected
    if header_idx is None or sep_idx is None or cols is None:
        return False  # no recognizable table — do nothing rather than guess

    def split_row(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header_cells = split_row(lines[header_idx])
    ncols = len(header_cells)
    positions: dict[str, int] = {}
    header_added = False
    for key, label, _fn in _LINK_COLUMN_SPECS:
        pos = next((i for i, k in cols.items() if k == key), None)
        if pos is None:
            header_cells.append(label)
            pos = ncols
            ncols += 1
            header_added = True
            sep_cells = split_row(lines[sep_idx])
            sep_cells.append("---")
            lines[sep_idx] = "| " + " | ".join(sep_cells) + " |\n"
        positions[key] = pos
    changed = header_added
    if header_added:
        lines[header_idx] = "| " + " | ".join(header_cells) + " |\n"

    email_col = next(i for i, k in cols.items() if k == "email")
    rows_by_email = {r["email"]: r for r in parse_email_list(path)}
    for i in range(sep_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if "|" not in stripped:
            break  # table ended
        cells = split_row(lines[i])
        while len(cells) < ncols:
            cells.append("")
        email = cells[email_col] if email_col < len(cells) else ""
        m = re.search(r"[\w.+-]+@[\w.-]+", email)
        if not m:
            continue
        row = rows_by_email.get(m.group(0))
        if row is None:
            continue
        for key, _label, path_fn in _LINK_COLUMN_SPECS:
            p = path_fn(row)
            if p and p.exists():
                link = f"[[{p.stem}]]"
                pos = positions[key]
                if cells[pos] != link:
                    cells[pos] = link
                    changed = True
        lines[i] = "| " + " | ".join(cells) + " |\n"

    if changed:
        path.write_text("".join(lines), encoding="utf-8")
    return True


SENDER_ACCOUNT = "CANDIDATE_EMAIL"


def gmail_compose_url(draft: Path, sender: str = SENDER_ACCOUNT) -> str | None:
    """Gmail web-compose URL pre-filled with this draft's to/subject/body,
    opened under `sender`'s account (authuser). Stops short of sending —
    lands the user in the compose window to review, attach the CV, and hit
    Send themselves. Attachments cannot be pre-filled via URL (no browser or
    Gmail API allows attaching a local file through a link — this is a
    universal, non-bypassable restriction, not a gap in this tool), so the
    CV must be attached by hand each time.
    Returns None if the draft file is missing or has no parseable subject."""
    from urllib.parse import quote

    try:
        text = draft.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

    fm_m = re.match(r"\A---\n(.*?)\n---\n(.*)", text, flags=re.DOTALL)
    if not fm_m:
        return None
    fm, body = fm_m.group(1), fm_m.group(2)

    to_m = re.search(r'^to:\s*"?(.*?)"?\s*$', fm, flags=re.MULTILINE)
    subj_m = re.search(r'^subject:\s*"(.*?)"\s*$', fm, flags=re.MULTILINE)
    if not to_m or not subj_m:
        return None
    to_email_m = re.search(r"[\w.+-]+@[\w.-]+", to_m.group(1))
    if not to_email_m:
        return None
    to_addr, subject = to_email_m.group(0), subj_m.group(1)

    # Body: drop the "# To: / # Subject:" header lines duplicated from
    # frontmatter — Gmail's own To/Subject fields already carry that.
    body = re.sub(r"\A(?:# To:.*\n# Subject:.*\n)+\n?", "", body.strip())

    params = "&".join(
        f"{k}={quote(v, safe='')}" for k, v in [
            ("view", "cm"), ("fs", "1"), ("tf", "1"),
            ("to", to_addr), ("su", subject), ("body", body),
            ("authuser", sender),
        ]
    )
    return f"https://mail.google.com/mail/?{params}"


def save_imap_draft(row: dict, cv_pdf: Path | None = None) -> tuple[bool, str]:
    """Upload an email draft (+ optional PDF attachment) to Gmail's Drafts
    folder via IMAP, using an app password from .env.

    Returns (success, message). The IMAP approach bypasses the browser
    attachment restriction that `gmail_compose_url` hits — local files can
    be attached programmatically, so the user gets a fully-formed draft
    ready to review and send.

    Requires in .env:
      GMAIL_ADDRESS       the Gmail account (e.g. CANDIDATE_EMAIL)
      GMAIL_APP_PASSWORD  16-char app password from myaccount.google.com/apppasswords
    """
    import imaplib
    import email as email_lib
    import os
    import html as html_lib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders as email_encoders

    from dotenv import dotenv_values
    env = {**dotenv_values(ROOT / ".env"), **os.environ}

    gmail_addr = env.get("GMAIL_ADDRESS", "")
    app_pass = env.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not gmail_addr or not app_pass:
        return False, "GMAIL_ADDRESS か GMAIL_APP_PASSWORD が .env に未設定"

    dp = draft_path(row)
    if not dp or not dp.exists():
        return False, "メール下書きファイルが見つかりません — 先に「メール下書きを生成」してください"

    # Parse draft: extract to/subject/body from frontmatter + body
    text = dp.read_text(encoding="utf-8")
    fm_m = re.match(r"\A---\n(.*?)\n---\n(.*)", text, flags=re.DOTALL)
    if not fm_m:
        return False, f"下書きファイルのフォーマットが読めません: {dp.name}"
    fm, body_md = fm_m.group(1), fm_m.group(2)

    to_m = re.search(r'^to:\s*"?(.*?)"?\s*$', fm, flags=re.MULTILINE)
    subj_m = re.search(r'^subject:\s*"(.*?)"\s*$', fm, flags=re.MULTILINE)
    if not to_m or not subj_m:
        return False, "下書きの to: / subject: が読めません"
    to_email_m = re.search(r"[\w.+-]+@[\w.-]+", to_m.group(1))
    if not to_email_m:
        return False, "宛先メールアドレスが読めません"

    to_addr = to_email_m.group(0)
    subject = subj_m.group(1)
    body_text = re.sub(r"\A(?:# To:.*\n# Subject:.*\n)+\n?", "", body_md.strip())
    # RFC 5322 requires CRLF line endings in message bodies. Python's email
    # package does not normalize bare \n → \r\n on its own, and some mail
    # clients render a lone \n as no break at all (text reads as one crammed
    # paragraph) even though Gmail's own web compose is lenient about it.
    body_text = body_text.replace("\r\n", "\n").replace("\n", "\r\n")

    attach_name = f"CV_kazukiyunome_{re.sub(r'[^A-Za-z0-9]+', '_', row['company']).strip('_')}.pdf"

    # Gmail's OWN draft editor (opened from an IMAP-APPENDed draft, not from
    # its own Compose flow) is a rich-text editor: it renders whichever part
    # of a multipart/alternative it prefers, and for text/plain-only drafts it
    # has been observed to collapse paragraph breaks entirely — even with
    # correct \r\n line endings — showing everything run together. Attaching
    # a matching text/html alternative (paragraphs as separate <p> tags) gives
    # Gmail's editor an unambiguous rendering to load, independent of how it
    # would have reflowed the plain-text part.
    #
    # The signature block (career/email/_signature.md) uses Markdown link
    # and image syntax ([text](url), ![alt](url), including the linked-icon
    # form [![alt](img)](link)) so the text/plain part reads sensibly as
    # plain text. The HTML part must render those as real <a>/<img> tags —
    # html.escape() alone leaves "[text](url)" as inert literal text, which
    # is exactly the bug reported ("Markdown syntax shows up as-is"). Escape
    # first (safe: html.escape doesn't touch [ ] ( ) !, so it can't corrupt
    # the patterns matched below), then convert Markdown → HTML on the
    # escaped text; matched URLs go straight into href/src unescaped by a
    # second pass since they were already escaped in the first.
    # ATX heading level → font size for signature-line emphasis. Fewer #'s =
    # bigger, matching normal heading convention; floor is still comfortably
    # above the 14px body text so even h6 stands out. Levels are otherwise
    # arbitrary (this isn't a document, just "make these particular lines
    # prominent") — pick whichever # count reads right in the .md source.
    _HEADING_PX = {1: 24, 2: 21, 3: 19, 4: 17, 5: 16, 6: 15}

    def _heading_sub(m: re.Match) -> str:
        size = _HEADING_PX.get(len(m.group(1)), 15)
        return f'<span style="font-size:{size}px;font-weight:bold;">{m.group(2)}</span>'

    def _md_to_html(escaped: str) -> str:
        # #...###### Line — heading-style emphasis for specific signature
        # lines (name, portfolio link) so they stand out from the rest of the
        # block. Matched before the link/image patterns below so a markdown
        # link inside a heading line (e.g. "###### Portfolio Site: [x](url)")
        # still gets converted afterward — the <span> wrapper doesn't
        # interfere with the regexes that run next.
        escaped = re.sub(r"^(#{1,6}) (.+)$", _heading_sub, escaped, flags=re.MULTILINE)
        # [![alt](img_url)](link_url) — icon that links somewhere
        escaped = re.sub(
            r"\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)",
            r'<a href="\3"><img src="\2" alt="\1" style="vertical-align:middle;border:0;"></a>',
            escaped,
        )
        # ![alt](img_url) — bare image
        escaped = re.sub(
            r"!\[([^\]]*)\]\(([^)]+)\)",
            r'<img src="\2" alt="\1" style="vertical-align:middle;border:0;">',
            escaped,
        )
        # [text](url) — bare link
        escaped = re.sub(
            r"\[([^\]]*)\]\(([^)]+)\)",
            r'<a href="\2">\1</a>',
            escaped,
        )
        return escaped

    # Join with an explicit double <br> rather than wrapping each paragraph in
    # <p>...</p>: Gmail's compose editor resets <p> margins to 0 internally,
    # so paragraph gaps silently collapsed to a single line break even though
    # each paragraph was correctly in its own tag — <br><br> has no margin to
    # reset and renders identically everywhere.
    # Pull the <!--SIG-->...<!--/SIG--> block (see generate_draft) out of the
    # message before the generic paragraph split, build it into its own
    # dark-card HTML fragment (still using the same escape + _md_to_html +
    # <br> logic internally, so its own name/contact vs. icons spacing is
    # unchanged), and splice a placeholder back in — forcing blank-line
    # isolation on both sides so it always lands as its own paragraph,
    # regardless of exactly how much whitespace surrounded the sentinel.
    plain_body = body_text.replace("\r\n", "\n")
    sig_placeholder = "\x00SIGNATURE_CARD\x00"
    sig_html = ""
    sig_m = re.search(r"<!--SIG-->(.*?)<!--/SIG-->", plain_body, flags=re.DOTALL)
    if sig_m:
        # Unlike the rest of the message, the signature's styling (dark card,
        # sizing, etc.) is authored directly as raw HTML in
        # career/email/_signature.md — NOT html.escape()'d here, so a literal
        # <div style="..."> in that file passes straight through instead of
        # showing up as visible "<div>" text. This is deliberately scoped to
        # just the signature (a fixed, self-authored file) rather than the
        # message body (freeform per-role prose), where escaping stays the
        # safe default. _md_to_html still runs, so the signature's Markdown
        # links/images/headings get converted exactly as before.
        sig_text = sig_m.group(1).strip("\n")
        sig_inner = _md_to_html(sig_text).replace("\n", "<br>")
        # Mail clients' user-agent stylesheets default <a> to blue regardless
        # of a dark parent background — illegible against a dark card unless
        # overridden per-tag (a <style> block isn't reliable in Gmail, which
        # strips <head>). _md_to_html doesn't know the signature is dark, so
        # patch every anchor it produced here instead.
        sig_html = sig_inner.replace('<a href=', '<a style="color:#7ec8ff;" href=')
        plain_body = (
            plain_body[:sig_m.start()].rstrip("\n") + "\n\n"
            + sig_placeholder + "\n\n"
            + plain_body[sig_m.end():].lstrip("\n")
        )

    paragraphs = re.split(r"\r?\n\r?\n", plain_body.strip())
    html_body = "<br><br>".join(
        (sig_html if p.strip() == sig_placeholder
         else _md_to_html(html_lib.escape(p)).replace(chr(10), "<br>"))
        for p in paragraphs if p.strip()
    )

    # HTML-ONLY body (no text/plain alternative). With a multipart/alternative
    # Gmail's draft editor was picking the text/plain part — showing raw
    # Markdown syntax ([text](url)) and collapsing paragraph breaks to a single
    # line — so all the HTML rendering below was simply never displayed. An
    # HTML-only body leaves Gmail nothing else to render, so the <a>/<img> tags
    # and <br><br> gaps actually take effect in the compose window. Wrap in a
    # minimal document so line spacing is predictable across clients.
    html_doc = (
        '<html><body style="font-family:Arial,Helvetica,sans-serif;'
        f'font-size:14px;line-height:1.5;">{html_body}</body></html>'
    )
    html_part = MIMEText(html_doc, "html", "utf-8")

    # Build MIME message. If there's an attachment we need multipart/mixed;
    # otherwise the HTML part can be the whole message on its own.
    if cv_pdf and cv_pdf.exists():
        msg = MIMEMultipart("mixed")
        msg.attach(html_part)
        with cv_pdf.open("rb") as f:
            part = MIMEBase("application", "pdf")
            part.set_payload(f.read())
        email_encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment",
                        filename=attach_name)
        msg.attach(part)
    else:
        msg = html_part

    msg["From"] = gmail_addr
    msg["To"] = to_addr
    msg["Subject"] = subject

    replaced = 0
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        imap.login(gmail_addr, app_pass)
        # Gmail's Drafts label — works for any language setting
        imap.select('"[Gmail]/Drafts"')

        # Replace, don't accumulate: append() has no concept of "this row
        # already has a draft" — clicking the save button again (after a
        # template edit, or just retrying) previously appended a second,
        # third, ... copy of the same draft instead of updating it. Delete
        # any existing draft(s) already addressed to this recipient first, so
        # the result is always exactly one current draft per row.
        status, data = imap.search(None, "TO", f'"{to_addr}"')
        if status == "OK" and data and data[0]:
            nums = data[0].split()
            for num in nums:
                imap.store(num, "+FLAGS", r"\Deleted")
            imap.expunge()
            replaced = len(nums)

        imap.append(
            '"[Gmail]/Drafts"',
            r"\Draft",
            imaplib.Time2Internaldate(__import__("time").time()),
            msg.as_bytes(),
        )
        imap.logout()
    except imaplib.IMAP4.error as e:
        return False, f"IMAP エラー: {e}"
    except Exception as e:
        return False, f"接続エラー: {e}"

    attach_note = f" (添付: {cv_pdf.name})" if cv_pdf and cv_pdf.exists() else ""
    replace_note = f" (既存の下書き{replaced}件を置き換え)" if replaced else ""
    return True, f"Gmail の下書きに保存しました → {to_addr}{attach_note}{replace_note}"


if __name__ == "__main__":
    results = generate_all()
    if not results:
        print("email-list.md に有効な行がありません (メール列に @ を含む表の行が必要)")
    for row, path, status in results:
        print(f"  {row['email']:35s} {row['company']:20s} → {status}"
              + (f"  {path.name}" if path else ""))
