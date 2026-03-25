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

Follow the official guide: [Submission](https://docs.flathub.org/docs/for-app-authors/submission). A **step-by-step table** (clone `new-pr`, copy files to the **fork’s root**, open PR against `new-pr`, `bot, build`, approval) is in the root **[README.md](../README.md#maintainer-guide-github-flathub-and-aur)** under **Maintainer guide**.

**Copy rule:** In the `flathub` fork, put `io.github.UnDadFeated.ChronoArchiver.yml` and the same-named `.desktop`, `.metainfo.xml`, `chronoarchiver.sh`, etc. **at the top level of the branch**—not inside a `flatpak/` folder—so paths in the manifest match.

**Important:** Flathub’s policy discourages fully AI-generated submission PRs. A human maintainer should review the manifest, metainfo, and screenshots before opening the PR.

## Screenshots

Replace the placeholder screenshot in `io.github.UnDadFeated.ChronoArchiver.metainfo.xml` with real PNGs of the main window (hosted on `raw.githubusercontent.com` or your site).
