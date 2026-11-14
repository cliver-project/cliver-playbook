#!/usr/bin/env bash
# Regenerate the Kotlin API client module from contracts/openapi.yaml.
#
#   apps/android/scripts/generate-contracts.sh            write the module sources
#   apps/android/scripts/generate-contracts.sh --check    compare the recorded contract hash
#   apps/android/scripts/generate-contracts.sh --verify   regenerate in a temp dir and diff
#
# --verify and generation need Node (npx) and Java 17+. --check only reads the
# manifest written at generation time, so it is safe to run in any CI job.
set -euo pipefail

CLI_PACKAGE_VERSION="2.25.2"
GENERATOR_VERSION="7.27.0"
PACKAGE_NAME="com.example.android.contracts"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CONTRACT="$ROOT/contracts/openapi.yaml"
MODULE="$ROOT/apps/android/contracts"
SOURCES="$MODULE/src/main/kotlin/com/example/android/contracts"
MANIFEST="$MODULE/.contract-client.json"

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
        echo "error: $MANIFEST is missing; run apps/android/scripts/generate-contracts.sh" >&2
        exit 1
    fi
    for required in \
        "$SOURCES/apis/AuthApi.kt" \
        "$SOURCES/models/UserRead.kt"; do
        if [ ! -f "$required" ]; then
            echo "error: $required is missing; regenerate the Kotlin client" >&2
            exit 1
        fi
    done
    local expected actual
    expected="$(recorded_hash)"
    actual="$(hash_file "$CONTRACT")"
    if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
        echo "Kotlin client is stale; run apps/android/scripts/generate-contracts.sh" >&2
        exit 1
    fi
}

write_manifest() {
    cat > "$MANIFEST" <<EOF
{
  "generator": "kotlin",
  "options": {
    "apiPackage": "$PACKAGE_NAME.apis",
    "dateLibrary": "java8",
    "invokerPackage": "$PACKAGE_NAME.infrastructure",
    "library": "jvm-okhttp4",
    "modelPackage": "$PACKAGE_NAME.models",
    "packageName": "$PACKAGE_NAME",
    "serializationLibrary": "gson",
    "sourceFolder": "src/main/kotlin",
    "useCoroutines": "true"
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
        --generator-name kotlin \
        --library jvm-okhttp4 \
        --output "$target" \
        --additional-properties "serializationLibrary=gson,useCoroutines=true,dateLibrary=java8,packageName=$PACKAGE_NAME,modelPackage=$PACKAGE_NAME.models,apiPackage=$PACKAGE_NAME.apis,invokerPackage=$PACKAGE_NAME.infrastructure,sourceFolder=src/main/kotlin"
}

generate_into() {
    local target="$1"
    local log
    log="$(mktemp)"
    if ! generator_command "$target" >"$log" 2>&1; then
        cat "$log" >&2
        rm -f "$log"
        echo "error: Kotlin client generation failed" >&2
        exit 1
    fi
    rm -f "$log"
}

install_output() {
    local source="$1"
    mkdir -p "$(dirname "$SOURCES")"
    rm -rf "$SOURCES"
    cp -R "$source/src/main/kotlin/com/example/android/contracts" "$SOURCES"
}

verify() {
    check_hash
    local temporary
    temporary="$(mktemp -d)"
    trap 'rm -rf "${temporary:-}"' EXIT
    generate_into "$temporary"
    if ! diff -ru "$temporary/src/main/kotlin/com/example/android/contracts" "$SOURCES"; then
        echo "Kotlin client is stale; run apps/android/scripts/generate-contracts.sh" >&2
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
        echo "apps/android/contracts generated"
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
