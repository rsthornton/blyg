"""The generator against the rules of Blygger spec v0.4 it implements."""
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from press import build, ledger, notes

CONFIG = {"site": "https://blyg.example/", "title": "Test blyg", "generator": "shingai-press/0.1",
          "generator_url": "https://github.com/rsthornton/blyg",
          "author": {"name": "Tester", "url": "https://example.com/"}}
QUIET = 1800
T0 = 1_800_000_000  # a fixed clock
WATCH = Path(__file__).resolve().parents[2] / "blyg-watch" / "crawl"


class Blyg:
    """A source folder, its ledger, and a clock, for one test."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name) / "src"
        self.out = Path(self.tmp.name) / "out"
        self.src.mkdir()
        self.state = {"items": {}}

    def write(self, name, text, at):
        path = self.src / name
        path.write_text(text)
        import os
        os.utime(path, (at, at))
        return path

    def publish(self, at, now=False):
        changed = ledger.stamp(self.state, notes.read_notes(self.src), at, quiet=QUIET, now=now)
        build.build(self.state, CONFIG, self.out)
        return changed

    def json(self, rel):
        return json.loads((self.out / rel).read_text())

    def item(self, path):
        return self.json(f"items/{notes.split(path.read_text())[0]['blyg_id']}.json")


class TestVersions(unittest.TestCase):
    def setUp(self):
        self.b = Blyg()

    def tearDown(self):
        self.b.tmp.cleanup()

    def test_quiet_period_then_version_one(self):
        p = self.b.write("a.md", "---\nblyg: fragment\n---\nFirst words.\n", T0)
        self.assertEqual(self.b.publish(T0 + 60), [])
        self.assertEqual(len(self.b.publish(T0 + QUIET)), 1)
        doc = self.b.item(p)
        self.assertEqual((doc["version"], doc["content_md"]), (1, "First words.\n"))
        self.assertRegex(doc["id"], r"^[0-9a-hjkmnp-tv-z]{26}$")  # §5.1

    def test_now_skips_the_wait(self):
        self.b.write("a.md", "---\nblyg: fragment\n---\nNow.\n", T0)
        self.assertEqual(len(self.b.publish(T0, now=True)), 1)

    def test_edit_cuts_one_version_and_withholds_the_old_one(self):
        p = self.b.write("a.md", "---\nblyg: fragment\n---\nOne.\n", T0)
        self.b.publish(T0, now=True)
        self.b.write("a.md", p.read_text().replace("One.", "Two."), T0 + 10)
        self.b.publish(T0 + 20)  # still settling: nothing new
        self.assertEqual(self.b.item(p)["version"], 1)
        self.b.publish(T0 + 10 + QUIET)
        doc = self.b.item(p)
        self.assertEqual((doc["version"], doc["content_md"]), (2, "Two.\n"))
        self.assertFalse((self.b.out / "items" / doc["id"] / "v1.json").exists())  # §8: unpinned is 404
        self.assertNotIn("One.", "".join(f.read_text() for f in self.b.out.rglob("*") if f.is_file()))

    def test_pin_is_forever(self):
        p = self.b.write("a.md", "---\nblyg: fragment\npin: true\n---\nKeep this.\n", T0)
        self.b.publish(T0, now=True)
        self.b.write("a.md", p.read_text().replace("pin: true\n", "").replace("Keep this.", "Later."), T0 + 5)
        self.b.publish(T0 + 5, now=True)
        doc = self.b.item(p)
        pin = self.b.json(f"items/{doc['id']}/v1.json")
        self.assertEqual((pin["content_md"], pin["pinned"]), ("Keep this.\n", True))
        self.assertTrue(doc["changelog"][0]["pinned"])

    def test_withdrawal_is_an_endcap_and_keeps_pins(self):
        p = self.b.write("t.md", "---\nblyg: thread\npin: true\n---\n# A thread\n\nBody.\n", T0)
        self.b.publish(T0, now=True)
        self.b.write("t.md", p.read_text().replace("pin: true", "withdrawn: true"), T0 + 5)
        self.b.publish(T0 + 5, now=True)
        doc = self.b.item(p)
        self.assertEqual((doc["kind"], doc["content_md"], doc["media"], doc["transclusions"]),
                         ("withdrawn", "", [], []))  # §9
        self.assertTrue((self.b.out / doc["page"] / "index.html").exists())  # §9: page kept
        self.assertTrue((self.b.out / "items" / doc["id"] / "v1.json").exists())  # §8 rule 1
        feed = ET.parse(self.b.out / "feed.xml").getroot()
        titles = [i.findtext("title") for i in feed.iter("item")]
        self.assertEqual(titles, ["withdrawn"])  # §7: exactly one entry


class TestPrivacy(unittest.TestCase):
    def setUp(self):
        self.b = Blyg()

    def tearDown(self):
        self.b.tmp.cleanup()

    def test_drafts_and_hidden_comments_never_leave(self):
        self.b.write("draft.md", "A private draft with SECRET-DRAFT.\n", T0)
        self.b.write("a.md", "---\nblyg: fragment\n---\nPublic %%SECRET-COMMENT%% text.\n", T0)
        self.b.publish(T0, now=True)
        everything = "".join(f.read_text() for f in self.b.out.rglob("*") if f.is_file())
        self.assertNotIn("SECRET-DRAFT", everything)
        self.assertNotIn("SECRET-COMMENT", everything)

    def test_obsidian_links_are_refused(self):
        self.b.write("a.md", "---\nblyg: fragment\n---\nSee [[My private note]].\n", T0)
        with self.assertRaises(notes.Refused):
            self.b.publish(T0, now=True)


class TestSurface(unittest.TestCase):
    def setUp(self):
        self.b = Blyg()
        self.b.write("a.md", "---\nblyg: fragment\nnote: first\n---\nA [link](/elsewhere/).\n", T0)
        self.b.write("t.md", "---\nblyg: thread\n---\n# Thread\n\nLonger.\n", T0 + 100)
        self.b.publish(T0 + 100, now=True)

    def tearDown(self):
        self.b.tmp.cleanup()

    def test_manifest_and_index(self):
        m = self.b.json("blyg.json")
        for key in ("blyg", "title", "updated", "level", "generator", "site"):
            self.assertIn(key, m)  # §6.1
        index = self.b.json("items/index.json")["items"]
        self.assertEqual([i["updated"] for i in index], sorted((i["updated"] for i in index), reverse=True))  # §6.2

    def test_item_documents_carry_the_required_members(self):
        for entry in self.b.json("items/index.json")["items"]:
            doc = self.b.json(f"items/{entry['id']}.json")
            for key in ("blyg", "id", "kind", "origin", "version", "created", "updated", "content_md",
                        "content_html", "content_hash", "changelog", "media"):
                self.assertIn(key, doc)  # §5 members table
            self.assertEqual(doc["content_hash"], ledger.content_hash(doc["content_md"]))
            self.assertEqual(doc["updated"], doc["changelog"][-1]["at"])  # §5.2
            self.assertNotIn('href="/', doc["content_html"])  # §5.2: absolute URLs only

    def test_feed(self):
        root = ET.parse(self.b.out / "feed.xml").getroot()
        ns = "{https://blygger.org/ns/0.1}"
        self.assertEqual(root.find(f"channel/{ns}manifest").text, "https://blyg.example/blyg.json")
        guids = [i.findtext("guid") for i in root.iter("item")]
        self.assertTrue(all(g.startswith("blyg:") and ":v" in g for g in guids))  # §7
        self.assertEqual(sorted(["first: A link.", "Thread Longer."]), sorted([i.findtext("title") for i in root.iter("item")]))

    @unittest.skipUnless(WATCH.exists(), "blyg-watch is not checked out beside this repo")
    def test_the_watcher_reads_it(self):
        sys.path.insert(0, str(WATCH))
        from blygwatch.net import Response
        from blygwatch.watch import run

        out, site = self.b.out, CONFIG["site"]

        class Files:
            requests = 0

            def get(self, url):
                self.requests += 1
                if url == "https://dir.example/blygs.opml":
                    return Response(url, 200, f'<opml><body><outline xmlUrl="{site}feed.xml" htmlUrl="{site}"/></body></opml>'.encode())
                path = out / url[len(site):]
                return Response(url, 200, path.read_bytes()) if url.startswith(site) and path.is_file() else Response(url, 404, b"")

        with tempfile.TemporaryDirectory() as data:
            snap = json.loads(run(Files(), data, day="2026-11-01", seeds="https://dir.example/blygs.opml").read_text())
        blyg = snap["blygs"][0]
        self.assertNotIn("error", blyg)
        self.assertEqual((blyg["origin"], blyg["generator"], len(blyg["items"])), (site, "shingai-press/0.1", 2))


if __name__ == "__main__":
    unittest.main()
