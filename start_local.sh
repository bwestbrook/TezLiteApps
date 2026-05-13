#!/usr/bin/env bash
# Local dev: install deps, build, and start the dev server.
set -euo pipefail

npm install
npm run build
npm run serve
