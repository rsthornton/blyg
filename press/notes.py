"""Reading the source folder: which notes are items, and what they say.

A note is an item when its frontmatter says `blyg: fragment` or
`blyg: thread`. Every other note is a draft and is never read past its
frontmatter. Section numbers refer to Blygger spec v0.4.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("fragment", "thread")
FRAGMENT_CAP = 2000  # §5.3: publishers SHOULD cap fragments at 2,000 characters
_FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
_COMMENT = re.compile(r"%%.*?%%|<!--.*?-->", re.S)
_WIKI = re.compile(r"!?\[\[[^\]]*\]\]")


@dataclass
class Note:
    path: Path
    kind: str
    body: str  # content_md: the note's text, frontmatter and hidden comments removed
    meta: dict = field(default_factory=dict)
    mtime: float = 0.0


class Refused(Exception):
    """A note marked for publishing that cannot go out as written."""


def read_notes(folder):
    notes = []
    for path in sorted(Path(folder).glob("*.md")):
        text = path.read_text()
        meta, body = split(text)
        kind = meta.get("blyg")
        if kind not in KINDS:
            continue
        body = _COMMENT.sub("", body).strip() + "\n"
        if _WIKI.search(body):
            # Obsidian links and embeds would publish a private note's name,
            # and `[[` + id is protocol grammar (§10.1). Not supported yet.
            raise Refused(f"{path.name}: remove [[links]] and ![[embeds]] before publishing")
        if kind == "fragment" and len(body) > FRAGMENT_CAP:
            raise Refused(f"{path.name}: a fragment is at most {FRAGMENT_CAP} characters (§5.3)")
        notes.append(Note(path, kind, body, meta, path.stat().st_mtime))
    return notes


def split(text):
    """Frontmatter as a flat dict of strings (the subset this tool writes), and the body."""
    m = _FRONT.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not line.startswith((" ", "\t", "-")):
            meta[key.strip()] = value.strip().strip("\"'")
    return meta, text[m.end():]


def set_meta(path, key, value):
    """Write one frontmatter key into a note, leaving the rest as it was."""
    text = path.read_text()
    m = _FRONT.match(text)
    line = f"{key}: {value}"
    if not m:
        path.write_text(f"---\n{line}\n---\n{text}")
        return
    lines = [l for l in m.group(1).splitlines() if not l.startswith(f"{key}:")]
    path.write_text("---\n" + "\n".join(lines + [line]) + "\n---\n" + text[m.end():])
