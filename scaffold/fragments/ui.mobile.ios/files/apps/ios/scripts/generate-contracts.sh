#!/usr/bin/env bash
# Regenerate the Swift API client package from contracts/openapi.yaml.
#
#   apps/ios/scripts/generate-contracts.sh            write the package
#   apps/ios/scripts/generate-contracts.sh --check    compare the recorded contract hash
#   apps/ios/scripts/generate-contracts.sh --verify   regenerate in a temp dir and diff
#
# --verify and generation need Node (npx) and Java 17+. --check only reads the
# manifest written at generation time, so it is safe to run in any CI job.
set -euo pipefail

CLI_PACKAGE_VERSION="2.25.2"
GENERATOR_VERSION="7.27.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CONTRACT="$ROOT/contracts/openapi.yaml"
PACKAGE="$ROOT/apps/ios/Packages/Contracts"
MANIFEST="$PACKAGE/.contract-client.json"

usage() {
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
}

hash_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        echo "error: shasum or sha256sum is required" >&2
        exit 2
    fi
}

recorded_hash() {
    sed -n 's/.*"openapi_sha256"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$MANIFEST" | head -n 1
}

check_hash() {
    if [ ! -f "$CONTRACT" ]; then
        echo "error: $CONTRACT is missing; run make contracts first" >&2
        exit 1
    fi
    if [ ! -f "$MANIFEST" ]; then
        echo "error: $MANIFEST is missing; run apps/ios/scripts/generate-contracts.sh" >&2
        exit 1
    fi
    for required in \
        "$PACKAGE/Package.swift" \
        "$PACKAGE/Contracts/Classes/OpenAPIs/APIs/AuthAPI.swift" \
        "$PACKAGE/Contracts/Classes/OpenAPIs/Models/UserRead.swift"; do
        if [ ! -f "$required" ]; then
            echo "error: $required is missing; regenerate the Swift client" >&2
            exit 1
        fi
    done
    local expected actual
    expected="$(recorded_hash)"
    actual="$(hash_file "$CONTRACT")"
    if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
        echo "Swift client is stale; run apps/ios/scripts/generate-contracts.sh" >&2
        exit 1
    fi
}

write_manifest() {
    cat > "$MANIFEST" <<EOF
{
  "generator": "swift5",
  "options": {
    "projectName": "Contracts",
    "responseAs": "AsyncAwait"
  },
  "openapi_sha256": "$(hash_file "$CONTRACT")",
  "version": "$GENERATOR_VERSION"
}
EOF
}

generator_command() {
    local target="$1"
    local config="$target/.openapitools.json"
    cat > "$config" <<EOF
{
  "generator-cli": {
    "version": "$GENERATOR_VERSION"
  }
}
EOF
    local -a command
    if [ -n "${OPENAPI_GENERATOR_CLI:-}" ]; then
        read -r -a command <<< "$OPENAPI_GENERATOR_CLI"
    else
        command=(npx --yes "@openapitools/openapi-generator-cli@$CLI_PACKAGE_VERSION")
    fi
    "${command[@]}" --openapitools "$config" generate \
        --input-spec "$CONTRACT" \
        --generator-name swift5 \
        --output "$target" \
        --additional-properties "projectName=Contracts,responseAs=AsyncAwait"
}

generate_into() {
    local target="$1"
    local log
    log="$(mktemp)"
    if ! generator_command "$target" >"$log" 2>&1; then
        cat "$log" >&2
        rm -f "$log"
        echo "error: Swift client generation failed" >&2
        exit 1
    fi
    rm -f "$log"
}

install_output() {
    local source="$1"
    mkdir -p "$PACKAGE"
    rm -rf "$PACKAGE/Contracts"
    cp -R "$source/Contracts" "$PACKAGE/Contracts"
    cp "$source/Package.swift" "$PACKAGE/Package.swift"
}

verify() {
    check_hash
    local temporary
    temporary="$(mktemp -d)"
    trap 'rm -rf "${temporary:-}"' EXIT
    generate_into "$temporary"
    local failed=0
    diff -ru "$temporary/Contracts" "$PACKAGE/Contracts" || failed=1
    diff -u "$temporary/Package.swift" "$PACKAGE/Package.swift" || failed=1
    if [ "$failed" -ne 0 ]; then
        echo "Swift client is stale; run apps/ios/scripts/generate-contracts.sh" >&2
        exit 1
    fi
}

case "${1:-}" in
    "")
        if [ ! -f "$CONTRACT" ]; then
            echo "error: $CONTRACT is missing; run make contracts first" >&2
            exit 1
        fi
        temporary="$(mktemp -d)"
        trap 'rm -rf "${temporary:-}"' EXIT
        generate_into "$temporary"
        install_output "$temporary"
        write_manifest
        echo "apps/ios/Packages/Contracts generated"
        ;;
    --check)
        check_hash
        ;;
    --verify)
        verify
        ;;
    -h|--help)
        usage
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
