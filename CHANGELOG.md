# CHANGELOG


## v0.1.1 (2026-03-29)

### Bug Fixes

- **ci**: Remove build_command from semantic-release config
  ([`a3dd857`](https://github.com/mrosata/codetex-mcp/commit/a3dd857ae2e6af13b9c5e45d1acec5726f80ecf9))

The PSR GitHub Action runs in a Docker container without uv, causing `uv build` to fail with exit
  code 127. The workflow already has a separate build step that runs on the runner.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.1.0 (2026-03-29)
