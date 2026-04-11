# Security

## Reporting vulnerabilities

Report security issues **privately** (do not open a public GitHub issue for undisclosed exploits). Prefer the repository owner’s contact on the [GitHub profile](https://github.com/UnDadFeated) or, if published, a security advisory on the repository.

Include: affected version or commit, reproduction steps, and impact assessment.

## Privacy and data

- ChronoArchiver runs **locally**. The **HEALTH** summary stays on-screen; log files remain under the app log directory unless you copy them yourself; nothing is uploaded automatically.
- Optional **structured JSON logs** (`CHRONOARCHIVER_JSON_LOG=1`) are still **local files** under the app log directory.
- AI inference and media processing use **on-device** resources unless you explicitly use a feature that calls the network (e.g. model downloads, update checks).

## Supply chain

- Prefer **verified** release assets (SHA-256 checksums published with releases).
- **Windows / macOS**: use signed installers when available; verify publisher identity in the OS dialog.

## Dependencies

- Review **Dependabot** pull requests before merging; pinned stacks (e.g. PyTorch) may need manual testing.
