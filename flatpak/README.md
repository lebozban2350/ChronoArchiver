# Flathub packaging for ChronoArchiver

Flatpak **app ID**: `io.github.UnDadFeated.ChronoArchiver` (matches GitHub: `UnDadFeated/ChronoArchiver`).

## Prerequisites

- `flatpak` and `flatpak-builder`
- Flathub remotes: `org.kde.Platform`, `org.kde.Sdk` **6.8**, `io.qt.PySide.BaseApp` **6.8**, `org.freedesktop.Sdk.Extension` (if needed)

Install the builder tool Flathub recommends:

```bash
flatpak install -y flathub org.flatpak.Builder
```

## Local test build

From the **repository root** (so the `flatpak/` paths resolve):

```bash
flatpak run org.flatpak.Builder --install --user --force-clean build-dir flatpak/io.github.UnDadFeated.ChronoArchiver.yml
flatpak run io.github.UnDadFeated.ChronoArchiver
```

## Regenerate Python wheel modules (optional)

PySide6 is taken from **`io.qt.PySide.BaseApp`**. Other dependencies are listed in `requirements-flatpak.txt`. To refresh `python3-*` modules after dependency changes:

```bash
python3 /path/to/flatpak-builder-tools/pip/flatpak-pip-generator.py \
  --requirements-file=flatpak/requirements-flatpak.txt \
  --output=flatpak/python3-modules --yaml --ignore-errors
```

Then merge the generated modules into `io.github.UnDadFeated.ChronoArchiver.yml` (and fix **opencv** wheels with `only-arches` for `x86_64` and `aarch64` as in the current manifest).

## Submit to Flathub

Read [Submission](https://docs.flathub.org/docs/for-app-authors/submission), [Requirements](https://docs.flathub.org/docs/for-app-authors/requirements), and the [Generative AI policy](https://docs.flathub.org/docs/for-app-authors/requirements#generative-ai-policy). PRs must target the **`new-pr`** branch ([CONTRIBUTING](https://github.com/flathub/flathub/blob/master/CONTRIBUTING.md)).

**Copy rule:** In your `flathub` fork, put `io.github.UnDadFeated.ChronoArchiver.yml` and the same-named `.desktop`, `.metainfo.xml`, `chronoarchiver.sh`, etc. **at the top level of the branch**—not inside a `flatpak/` folder—so paths in the manifest match.

| Step | Action |
|------|--------|
| 1 | Fork [flathub/flathub](https://github.com/flathub/flathub) with **“Copy the master branch only”** unchecked. |
| 2 | `git clone --branch=new-pr git@github.com:YOUR_USER/flathub.git && cd flathub` |
| 3 | `git checkout -b add-chronoarchiver new-pr` |
| 4 | Copy the files from this repo’s **`flatpak/`** into the fork **root** (see copy rule). Ensure the manifest **`tag:`** matches a commit you intend to ship (e.g. **v3.8.2** on `main`). |
| 5 | Build and test locally; run the [linter](https://docs.flathub.org/docs/for-app-authors/submission#run-the-linter). |
| 6 | `git add`, `commit`, `push` to your fork. |
| 7 | Open a PR with **base = `new-pr`**, title e.g. `Add io.github.UnDadFeated.ChronoArchiver`. |
| 8 | Review: comment **`bot, build`** when ready; fix feedback. |
| 9 | After merge, accept the org invite; maintain updates in **`flathub/io.github.UnDadFeated.ChronoArchiver`** ([maintenance](https://docs.flathub.org/docs/for-app-authors/maintenance)). |

**Important:** Flathub discourages fully AI-generated submission PRs; a human should review manifests and metainfo before opening the PR.

## Screenshots

Replace the placeholder screenshot in `io.github.UnDadFeated.ChronoArchiver.metainfo.xml` with real PNGs of the main window (hosted on `raw.githubusercontent.com` or your site).
