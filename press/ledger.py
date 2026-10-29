"""The blyg's protocol state: ids, versions, changelogs and pins.

The ledger lives beside the notes (private) because it holds what the
protocol withholds: every version's hash and time, and the content of each
pinned version, which must stay fetchable forever (§8). It never holds the
content of an unpinned older version.

A version is cut when a note's text differs from its last published
version and the note has been quiet for `quiet` seconds, or at once with
`now=True`. Every publish event bumps the counter by exactly 1 (§5.2).
"""
import hashlib
import json
import secrets
from datetime import datetime, timezone

from .notes import set_meta

CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"


def new_id():
    # §5.1: 128 random bits as 26 characters of lowercase Crockford base32.
    n = secrets.randbits(128)
    return "".join(CROCKFORD[(n >> (5 * i)) & 31] for i in reversed(range(26)))


def content_hash(md):
    return "sha256:" + hashlib.sha256(md.encode()).hexdigest()  # §5.1


def stamp_time(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path):
    return json.loads(path.read_text()) if path.exists() else {"items": {}}


def save(ledger, path):
    path.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n")


def stamp(ledger, notes, now_ts, quiet=1800, now=False):
    """Apply every note's state to the ledger. Returns the ids that changed."""
    changed = []
    at = stamp_time(now_ts)
    for note in notes:
        item_id = note.meta.get("blyg_id")
        if not item_id:
            item_id = new_id()
            set_meta(note.path, "blyg_id", item_id)
        item = ledger["items"].setdefault(item_id, {"kind": note.kind, "created": None, "changelog": [], "pins": {}})
        last = item["changelog"][-1] if item["changelog"] else None
        withdrawn = note.meta.get("withdrawn") == "true"
        settled = now or now_ts - note.mtime >= quiet

        if withdrawn:
            if last and last["kind"] != "withdrawn" and settled:
                _event(item, at, "withdrawn", "", note.meta.get("note"))
                changed.append(item_id)
            continue
        if note.kind != item["kind"]:
            raise ValueError(f"{note.path.name}: a published item's kind cannot change")
        if (last is None or last["kind"] == "withdrawn" or last["hash"] != content_hash(note.body)) and settled:
            item["created"] = item["created"] or at
            _event(item, at, note.kind, note.body, note.meta.get("note"))
            changed.append(item_id)
            last = item["changelog"][-1]
        if note.meta.get("pin") == "true" and last and last["kind"] != "withdrawn":
            # §8: a pin is irrevocable, so removing `pin` later unpins nothing.
            # It pins the last published version, never unpublished edits.
            if str(last["version"]) not in item["pins"]:
                item["pins"][str(last["version"])] = {"content_md": item["current_md"]}
                changed.append(item_id)
    return sorted(set(changed))


def _event(item, at, kind, md, note):
    # A note in frontmatter describes the next version only: one already
    # used is not repeated on every later edit.
    used = {e["note"] for e in item["changelog"]}
    item["changelog"].append({"version": len(item["changelog"]) + 1, "at": at, "kind": kind,
                              "hash": content_hash(md), "note": note if note and note not in used else None})
    item["current_md"] = md  # the latest published content; older content is not kept
