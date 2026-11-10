# blyg

The generator for [blyg.shingai.xyz](https://blyg.shingai.xyz/), Shingai Thornton's [Blygger](https://blygger.org) blyg. Notes are written in Obsidian, stamped into protocol state, built into a static blyg, and published to GitHub Pages. It implements Blygger spec v0.4 (a pre-1.0 draft); section numbers below refer to it.

## Why another client

Blygger already has many clients (the [ecosystem page](https://blygger.org/ecosystem/) lists them). None fitted three needs at once: write in an existing Obsidian vault, host on GitHub Pages, and emit spec v0.4.

| Prior art | What it does | Why not here |
|---|---|---|
| [Blygger Studio](https://github.com/blygger/blygger-studio) | The reference client: a hosted studio on Cloudflare Workers | It already runs 12 of the 25 listed blygs. This blyg belongs to someone who audits the network's concentration (see [blyg-watch](https://halcyonic.systems/blyg-watch/)), so it adds a host and a client instead. |
| [blyg-publisher](https://github.com/brndnpink/blyg-publisher) | An Obsidian plugin: publishes to a Studio, or builds a static blyg and deploys it to Cloudflare Pages | Implements spec 0.2 at Level 1, and deploys only to Cloudflare. Its safety rules (one folder, opt-in per note, hidden comments stripped, private links refused) are adopted here. |
| [drafts-blyg](https://github.com/miguelito4/drafts-blyg) | Drafts actions that post from a phone, to a Studio or into a git repo whose build makes the blyg | It writes files and leaves the build to the site. This repo can be that build later; its "stamp at commit time" pattern is the model for the ledger. |
| [hugo-blyg](https://github.com/chrisbodhi/hugo-blyg) | A Hugo module that builds a blyg in GitHub Actions | Spec 0.3, and no licence. |

## How it works

| Step | What happens | Spec |
|---|---|---|
| Write | Notes live in the vault at `work/blyg/`. A note is an item only when its frontmatter says `blyg: fragment` or `blyg: thread`; every other note is a draft and never leaves the Mac. | §5.3 |
| Stamp | `press publish` gives each new item a permanent id (written into the note as `blyg_id`), and cuts a version when a note's text has changed and it has been untouched for 30 minutes (`--now` skips the wait). The ledger (`work/blyg/ledger.json`) holds versions, times and pinned content. | §5.1, §5.2, §8 |
| Build | From the ledger alone: manifest, feed, archive index, item documents, pinned versions, plain HTML pages. Nothing for unpinned older versions. | §4 to §9 |
| Publish | The build lands in `_site/`, a worktree on the `live` branch, which GitHub Pages serves. `--push` commits and pushes it when it changed. | |

The notes stay private because a public git history of them would publish every unpinned edit, which the spec withholds: "Older content is withheld — the publisher's history stays private by default — unless a version is pinned" (§5.2). Only the build is public.

**In a note's frontmatter**

| Key | Meaning |
|---|---|
| `blyg: fragment` or `blyg: thread` | Publish this note. A fragment is at most 2,000 characters (§5.3). |
| `note: …` | The changelog note for the next version (§5.2) |
| `pin: true` | Pin the latest published version, forever (§8). Removing it later unpins nothing. |
| `withdrawn: true` | Withdraw: an endcap with empty content; the page and any pins stay (§9). Remove it to bring the item back. |
| `blyg_id` | Written by the tool. Never edit or copy it. |

Deleting a note does nothing to the published blyg: the protocol has no delete (§9). Withdraw instead.

**Not yet:** `[[links]]` and `![[embeds]]` (refused at publish, since they could carry a private note's name and `[[id]]` is protocol grammar, §10.1), quoting other blygs (§10.2), stubs, forks, images, Webmention.

## Run

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest            # 11 tests, offline
.venv/bin/python -m press publish       # stamp and build into _site/
.venv/bin/python -m press publish --push
```

**Auto-publish, off.** `launchd/xyz.shingai.blyg.publish.plist` runs `press publish --push` every 10 minutes once copied to `~/Library/LaunchAgents/` and loaded. It is not loaded: publishing is by hand until there is a reason to change that.

The tests include one where [blyg-watch](https://github.com/halcyonic-systems/blyg-watch)'s watcher reads the built blyg, when that repo is checked out beside this one.
