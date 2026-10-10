#!/bin/sh
# Runs inside the build-runner container (ADR-0015). There is no network and no writable host
# mount: the verified project is mounted read-only at /src, work happens on a tmpfs, logs and
# step results go to stderr, and the built files leave as a tar stream on stdout.
set -u

now_ms() { date +%s%3N; }

step() {
  name="$1"
  shift
  start="$(now_ms)"
  "$@" 1>&2
  code=$?
  echo "@@step {\"name\":\"$name\",\"exit\":$code,\"ms\":$(( $(now_ms) - start ))}" 1>&2
  return $code
}

cp -R /src/. /work/ || exit 90
ln -s /toolchain/node_modules /work/node_modules || exit 91
cd /work || exit 92

step typecheck node node_modules/typescript/bin/tsc -p tsconfig.json || exit 1
step build node node_modules/vite/bin/vite.js build --logLevel warn || exit 1
[ -d dist ] || exit 93
tar -C dist -cf - .
