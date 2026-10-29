"""From the ledger to the publication surface (spec v0.4 §4): the manifest,
feed, archive index, item documents, pinned versions, and plain HTML pages.

The build reads only the ledger, never the notes, so what goes out is
exactly what has been stamped. It writes nothing for unpinned older
versions: their content is withheld (§5.2).
"""
import html
import json
import re
import shutil
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import markdown

from .ledger import content_hash

SPEC = "0.4"
LEVEL = 2  # §3: a publisher that emits no cross-origin construct is L2 "by doing nothing new"
FEED_WINDOW = 50  # §7: RECOMMENDED
STYLE = Path(__file__).with_name("style.css")


def build(ledger, config, out):
    out = Path(out)
    if out.exists():
        for child in out.iterdir():
            if child.name != ".git":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    origin = config["site"]
    docs = {i: _item_doc(i, item, config) for i, item in ledger["items"].items() if item["changelog"]}
    by_updated = sorted(docs.values(), key=lambda d: d["updated"], reverse=True)
    updated = by_updated[0]["updated"] if by_updated else None

    for item_id, doc in docs.items():
        _write_json(out / "items" / f"{item_id}.json", doc)
        for n, pin in ledger["items"][item_id]["pins"].items():
            _write_json(out / "items" / item_id / f"v{n}.json", _pin_doc(doc, int(n), pin, config))
        _write(out / doc["page"] / "index.html", _page(doc, config))
    _write_json(out / "items" / "index.json", {
        "updated": updated,
        "items": [{k: d[k] for k in ("id", "kind", "created", "updated", "version")} for d in by_updated]})
    _write_json(out / "blyg.json", _manifest(config, updated))
    _write(out / "feed.xml", _feed(docs, config, updated))
    _write(out / "index.html", _home(by_updated, config))
    shutil.copy(STYLE, out / "style.css")
    _write(out / "CNAME", urlsplit(origin).netloc + "\n")  # GitHub Pages custom domain
    _write(out / ".nojekyll", "")
    return out


def _item_doc(item_id, item, config):
    log = item["changelog"]
    last = log[-1]
    kind = last["kind"]
    page = f"{'t' if item['kind'] == 'thread' else 'f'}/{item_id}/"
    md = item["current_md"] if kind != "withdrawn" else ""
    doc = {
        "blyg": SPEC, "id": item_id, "kind": kind, "origin": config["site"], "page": page,
        "created": item["created"], "updated": last["at"], "version": last["version"],
        "content_md": md, "content_html": render(md, config["site"]), "content_hash": content_hash(md),
        "media": [],
        "changelog": [_entry(e, item["pins"]) for e in log],
    }
    if config.get("author"):
        doc["author"] = config["author"]
    if item["kind"] == "thread":
        doc["transclusions"] = []  # §10.3: threads always carry the key
    return doc


def _entry(e, pins):
    entry = {"version": e["version"], "at": e["at"], "note": e["note"]}
    if str(e["version"]) in pins:
        entry["pinned"] = True
    return entry


def _pin_doc(doc, n, pin, config):
    # §8: the pinned version's own content, with "pinned": true.
    e = next(c for c in doc["changelog"] if c["version"] == n)
    kind = "thread" if doc["page"].startswith("t/") else "fragment"
    pdoc = {"blyg": SPEC, "id": doc["id"], "kind": kind, "version": n, "at": e["at"], "note": e["note"],
            "pinned": True, "origin": config["site"], "content_md": pin["content_md"],
            "content_html": render(pin["content_md"], config["site"]), "content_hash": content_hash(pin["content_md"])}
    if kind == "thread":
        pdoc["transclusions"] = []
    return pdoc


def _manifest(config, updated):
    m = {"blyg": SPEC, "level": LEVEL, "generator": config["generator"], "generator_url": config["generator_url"],
         "site": config["site"], "title": config["title"], "feed": "feed.xml", "items": "items/index.json",
         "updated": updated}
    if config.get("author"):
        m["author"] = config["author"]
    return m


def _feed(docs, config, updated):
    events = []
    for doc in docs.values():
        log = doc["changelog"]
        # §7: a withdrawn item contributes exactly one entry, its withdrawal.
        for e in (log[-1:] if doc["kind"] == "withdrawn" else log):
            events.append((e["at"], doc, e))
    events.sort(key=lambda t: t[0], reverse=True)
    items = []
    for at, doc, e in events[:FEED_WINDOW]:
        withdrawn = doc["kind"] == "withdrawn"
        link = urljoin(config["site"], doc["page"])
        items.append(
            "    <item>\n"
            f'      <guid isPermaLink="false">blyg:{doc["id"]}:v{e["version"]}</guid>\n'
            f"      <link>{_x(link)}</link>\n"
            f"      <title>{_x('withdrawn' if withdrawn else _title(e['note'], doc['content_html']))}</title>\n"
            f"      <description><![CDATA[{'' if withdrawn else doc['content_html']}]]></description>\n"
            f"      <pubDate>{_rfc822(at)}</pubDate>\n"
            + (f"      <dc:creator>{_x(config['author']['name'])}</dc:creator>\n" if config.get("author") else "")
            + f"      <blyg:id>{doc['id']}</blyg:id>\n"
            f"      <blyg:kind>{doc['kind']}</blyg:kind>\n"
            f"      <blyg:version>{e['version']}</blyg:version>\n"
            f"      <blyg:created>{doc['created']}</blyg:created>\n"
            f"      <blyg:item>{_x(urljoin(config['site'], 'items/' + doc['id'] + '.json'))}</blyg:item>\n"
            "    </item>\n")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:blyg="https://blygger.org/ns/0.1" xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "  <channel>\n"
        f"    <title>{_x(config['title'])}</title>\n"
        f"    <link>{_x(config['site'])}</link>\n"
        f"    <description>{_x(config.get('description', ''))}</description>\n"
        + (f"    <lastBuildDate>{_rfc822(updated)}</lastBuildDate>\n" if updated else "")
        + f"    <blyg:level>{LEVEL}</blyg:level>\n"
        f"    <blyg:manifest>{_x(urljoin(config['site'], 'blyg.json'))}</blyg:manifest>\n"
        + "".join(items) + "  </channel>\n</rss>\n")


def _title(note, content_html):
    # §7: derived, never read back. The spec's recommended form joins the
    # note and an excerpt with a dash; this client uses a colon.
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</(p|h\d|li|blockquote)>|<br ?/?>", " ", content_html)))).strip()
    excerpt = text[:80] + ("…" if len(text) > 80 else "")
    return f"{note}: {excerpt}" if note else excerpt


def render(md, origin):
    if not md:
        return ""
    out = markdown.markdown(md, extensions=["fenced_code", "tables"])
    # §5.2: every URL in content_html MUST be absolute.
    return re.sub(r'(href|src)="(?![a-z][a-z0-9+.-]*:|#)([^"]*)"',
                  lambda m: f'{m.group(1)}="{urljoin(origin, m.group(2))}"', out)


def _page(doc, config):
    body = '<p class="gone">withdrawn</p>' if doc["kind"] == "withdrawn" else doc["content_html"]
    log = "".join(f"<li>v{e['version']} {e['at'][:10]}{' pinned' if e.get('pinned') else ''}"
                  f"{': ' + html.escape(e['note']) if e['note'] else ''}</li>" for e in doc["changelog"])
    alt = f'<link rel="alternate" type="application/json" href="{urljoin(config["site"], "items/" + doc["id"] + ".json")}">'
    return _shell(config, f"<article>{body}</article><ol class=\"log\">{log}</ol>", alt, depth=2)


def _home(docs, config):
    rows = "".join(
        f'<li><a href="{d["page"]}">{html.escape(_title(None, d["content_html"]) or "withdrawn")}</a>'
        f' <span>{d["updated"][:10]}</span></li>' for d in docs)
    head = f'<link rel="alternate" type="application/rss+xml" href="feed.xml"><link rel="blyg" href="./">'
    return _shell(config, f"<h1>{html.escape(config['title'])}</h1><ul class=\"items\">{rows}</ul>", head, depth=0)


def _shell(config, main, head, depth):
    up = "../" * depth
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(config['title'])}</title>{head}"
            f'<link rel="stylesheet" href="{up}style.css"></head>'
            f'<body><main>{main}</main><footer><a href="{up}">{html.escape(config["title"])}</a>'
            f' · <a href="{up}feed.xml">feed</a> · a <a href="https://blygger.org">Blygger</a> blyg</footer></body></html>\n')


def _rfc822(at):
    return format_datetime(datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc), usegmt=True)


def _x(s):
    return html.escape(s or "", quote=False)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_json(path, obj):
    _write(path, json.dumps(obj, indent=1, ensure_ascii=False) + "\n")
