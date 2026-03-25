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

Follow **official steps**: [Submission](https://docs.flathub.org/docs/for-app-authors/submission).

Summary:

1. Fork [flathub/flathub](https://github.com/flathub/flathub) (uncheck “copy master only”).
2. Clone `git clone --branch=new-pr git@github.com:YOUR_USER/flathub.git && cd flathub`.
3. Branch: `git checkout -b add-chronoarchiver new-pr`.
4. Copy **this `flatpak/` directory’s contents** into the fork (paths Flathub expects are usually the manifest + appstream at repo root for the submission PR; follow the current Flathub PR template).
5. Open a PR **against the `new-pr` branch** (not `master`), title e.g. `Add io.github.UnDadFeated.ChronoArchiver`.
6. Comment `bot, build` when ready for a test build.
7. Address review feedback; after merge, the app repo will appear under [github.com/flathub](https://github.com/flathub) and you will get an invite.

**Important:** Flathub’s policy discourages fully AI-generated submission PRs. A human maintainer should review the manifest, metainfo, and screenshots before opening the PR.

## Screenshots

Replace the placeholder screenshot in `io.github.UnDadFeated.ChronoArchiver.metainfo.xml` with real PNGs of the main window (hosted on `raw.githubusercontent.com` or your site).
