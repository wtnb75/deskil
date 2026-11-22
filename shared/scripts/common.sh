#!/usr/bin/env bash
# Shared script. Plugins reference this file through relative symlinks.
set -euo pipefail

echo "common.sh: hello from $(basename "$(dirname "$(dirname "$0")")") (args: $*)"
