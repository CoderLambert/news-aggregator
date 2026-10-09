#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"

EXECUTE=0
IMAGE=""
SHA=""
ROOT=""
CONTAINER_ID=""
WORK_DIR=""
STAGE_DIR=""
CURRENT_LINK_TMP=""
PREVIOUS_LINK_TMP=""
TEMP_ASSET=""

usage() {
    cat <<'EOF'
Usage: export-static.sh [--execute] [--image IMAGE] [--sha 40-HEX-SHA] [--root ABSOLUTE-ROOT]

Without --execute, this script only validates arguments and prints a dry-run plan.
EOF
}

fail() {
    printf 'export-static: %s\n' "$1" >&2
    exit 2
}

cleanup() {
    local status=$?
    trap - EXIT
    if [[ -n "$CONTAINER_ID" ]]; then
        docker rm "$CONTAINER_ID" >/dev/null 2>&1 || true
    fi
    if [[ -n "$STAGE_DIR" && -d "$STAGE_DIR" ]]; then
        rm -rf -- "$STAGE_DIR"
    fi
    if [[ -n "$CURRENT_LINK_TMP" && -L "$CURRENT_LINK_TMP" ]]; then
        rm -f -- "$CURRENT_LINK_TMP"
    fi
    if [[ -n "$PREVIOUS_LINK_TMP" && -L "$PREVIOUS_LINK_TMP" ]]; then
        rm -f -- "$PREVIOUS_LINK_TMP"
    fi
    if [[ -n "$TEMP_ASSET" && -f "$TEMP_ASSET" ]]; then
        rm -f -- "$TEMP_ASSET"
    fi
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        rm -rf -- "$WORK_DIR"
    fi
    exit "$status"
}
trap cleanup EXIT

while (($#)); do
    case "$1" in
        --execute)
            EXECUTE=1
            shift
            ;;
        --image)
            (($# >= 2)) || fail '--image requires a value.'
            IMAGE=$2
            shift 2
            ;;
        --sha)
            (($# >= 2)) || fail '--sha requires a value.'
            SHA=$2
            shift 2
            ;;
        --root)
            (($# >= 2)) || fail '--root requires a value.'
            ROOT=$2
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            fail "unknown argument: $1"
            ;;
    esac
done

validate_sha() {
    [[ "$SHA" =~ ^[[:xdigit:]]{40}$ ]] || fail '--sha must be exactly 40 hexadecimal characters.'
    SHA="$(printf '%s' "$SHA" | tr 'A-F' 'a-f')"
}

validate_root() {
    [[ "$ROOT" == /* ]] || fail '--root must be an absolute path.'
    [[ "$ROOT" != / ]] || fail '--root must not be /.'
    ROOT="$(realpath -m -- "$ROOT")"
    [[ "$ROOT" != / ]] || fail '--root must not resolve to /.'
    if [[ "$ROOT" == "$PROJECT_ROOT" || "$ROOT" == "$PROJECT_ROOT/"* ]]; then
        fail '--root must be outside the source tree.'
    fi
}

if ((!EXECUTE)); then
    if [[ -z "$IMAGE" && -z "$SHA" && -z "$ROOT" ]]; then
        printf 'Dry run only: no Docker or filesystem changes. Pass --execute --image IMAGE --sha SHA --root ABSOLUTE-ROOT to export.\n'
        exit 0
    fi
    [[ -n "$IMAGE" && -n "$SHA" && -n "$ROOT" ]] || fail 'dry-run arguments must include --image, --sha, and --root together.'
    validate_sha
    validate_root
    printf 'Dry run only: would export image %s revision %s to %s; no Docker or filesystem changes.\n' "$IMAGE" "$SHA" "$ROOT"
    exit 0
fi

[[ -n "$IMAGE" ]] || fail '--execute requires --image.'
[[ -n "$SHA" ]] || fail '--execute requires --sha.'
[[ -n "$ROOT" ]] || fail '--execute requires --root.'
validate_sha
validate_root

IMAGE_REVISION="$(docker image inspect --format='{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE" 2>/dev/null)" \
    || fail 'could not inspect the requested image revision label.'
[[ "$IMAGE_REVISION" =~ ^[[:xdigit:]]{40}$ ]] || fail 'image revision label is missing or invalid.'
IMAGE_REVISION="$(printf '%s' "$IMAGE_REVISION" | tr 'A-F' 'a-f')"
[[ "$IMAGE_REVISION" == "$SHA" ]] || fail 'image revision label does not match --sha.'

mkdir -p -- "$ROOT"
[[ -d "$ROOT" && ! -L "$ROOT" ]] || fail 'export root must be a real directory, not a symlink.'
for directory in "$ROOT/releases" "$ROOT/assets"; do
    if [[ -L "$directory" ]]; then
        fail 'releases and assets directories must not be symlinks.'
    fi
    if [[ -e "$directory" && ! -d "$directory" ]]; then
        fail 'releases and assets paths must be directories.'
    fi
    mkdir -p -- "$directory"
done

RELEASE_REL="releases/$SHA"
RELEASE_PATH="$ROOT/$RELEASE_REL"
[[ ! -e "$RELEASE_PATH" && ! -L "$RELEASE_PATH" ]] || fail 'release path already exists; existing releases are never overwritten.'

old_current_sha=""
old_current_rel=""
if [[ -L "$ROOT/current" ]]; then
    old_current_path="$(realpath -e -- "$ROOT/current")" || fail 'current points to a missing release.'
    [[ "$old_current_path" == "$ROOT/releases/"* ]] || fail 'current must point inside releases/.'
    old_current_sha="${old_current_path##*/}"
    [[ "$old_current_sha" =~ ^[[:xdigit:]]{40}$ && -d "$old_current_path" && ! -L "$old_current_path" ]] \
        || fail 'current must point to an existing 40-hex release directory.'
    old_current_rel="${old_current_path#"$ROOT/"}"
elif [[ -e "$ROOT/current" ]]; then
    fail 'current exists but is not a symlink.'
fi
if [[ -e "$ROOT/previous" && ! -L "$ROOT/previous" ]]; then
    fail 'previous exists but is not a symlink.'
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/newshub-static-export.XXXXXX")"
mkdir -p -- "$WORK_DIR/dist"
CONTAINER_ID="$(docker create --network none "$IMAGE")" || fail 'docker create failed.'
[[ -n "$CONTAINER_ID" ]] || fail 'docker create returned an empty container ID.'
docker cp "$CONTAINER_ID:/app/frontend/dist/." "$WORK_DIR/dist/" || fail 'docker cp failed.'
docker rm "$CONTAINER_ID" >/dev/null || fail 'could not remove the stopped export container.'
CONTAINER_ID=""

DIST="$WORK_DIR/dist"
[[ -f "$DIST/index.html" && ! -L "$DIST/index.html" ]] || fail 'image dist is missing a regular index.html.'
[[ -d "$DIST/assets" && ! -L "$DIST/assets" ]] || fail 'image dist is missing an assets directory.'
if find "$DIST" -type l -print -quit | grep -q .; then
    fail 'image dist must not contain symlinks.'
fi
if find "$DIST" ! -type f ! -type d -print -quit | grep -q .; then
    fail 'image dist may contain only regular files and directories.'
fi
asset_count="$(find "$DIST/assets" -type f -printf '.' | wc -c)"
((asset_count > 0)) || fail 'image dist assets directory is empty.'

STAGE_DIR="$(mktemp -d "$ROOT/releases/.${SHA}.tmp.XXXXXX")"
find "$DIST" -mindepth 1 -maxdepth 1 ! -name assets -exec cp -a -- {} "$STAGE_DIR/" \;

ensure_asset_parent() {
    local relative_directory=$1
    local cursor="$ROOT/assets"
    local component
    local -a components
    [[ "$relative_directory" == . ]] && return 0
    IFS='/' read -r -a components <<< "$relative_directory"
    for component in "${components[@]}"; do
        [[ -n "$component" && "$component" != . && "$component" != .. ]] || fail 'invalid asset path.'
        cursor="$cursor/$component"
        [[ ! -L "$cursor" ]] || fail 'shared asset path contains a symlink.'
        if [[ -e "$cursor" ]]; then
            [[ -d "$cursor" ]] || fail 'shared asset parent is not a directory.'
        else
            mkdir -- "$cursor"
        fi
    done
}

while IFS= read -r -d '' source_asset; do
    relative_asset="${source_asset#"$DIST/assets/"}"
    [[ "$relative_asset" != "$source_asset" ]] || fail 'invalid asset path.'
    [[ "$relative_asset" != /* ]] || fail 'invalid absolute asset path.'
    asset_directory="$(dirname -- "$relative_asset")"
    ensure_asset_parent "$asset_directory"
    destination_asset="$ROOT/assets/$relative_asset"
    if [[ -e "$destination_asset" || -L "$destination_asset" ]]; then
        [[ -f "$destination_asset" && ! -L "$destination_asset" ]] || fail 'shared asset destination is not a regular file.'
        cmp -s -- "$source_asset" "$destination_asset" || fail 'same-name shared asset has different content; refusing to overwrite.'
        continue
    fi
    TEMP_ASSET="$(mktemp "$(dirname -- "$destination_asset")/.asset.XXXXXX")"
    cp -- "$source_asset" "$TEMP_ASSET"
    if ! ln -- "$TEMP_ASSET" "$destination_asset" 2>/dev/null; then
        if [[ -f "$destination_asset" && ! -L "$destination_asset" ]] && cmp -s -- "$source_asset" "$destination_asset"; then
            rm -f -- "$TEMP_ASSET"
            TEMP_ASSET=""
            continue
        fi
        rm -f -- "$TEMP_ASSET"
        TEMP_ASSET=""
        fail 'could not atomically add a shared asset.'
    fi
    rm -f -- "$TEMP_ASSET"
    TEMP_ASSET=""
done < <(find "$DIST/assets" -type f -print0)

ln -s ../../assets "$STAGE_DIR/assets"
mv -- "$STAGE_DIR" "$RELEASE_PATH"
STAGE_DIR=""

if [[ -n "$old_current_sha" ]]; then
    PREVIOUS_LINK_TMP="$ROOT/.previous.new.$$"
    [[ ! -e "$PREVIOUS_LINK_TMP" && ! -L "$PREVIOUS_LINK_TMP" ]] || fail 'temporary previous symlink already exists.'
    ln -s "$old_current_rel" "$PREVIOUS_LINK_TMP"
    mv -Tf -- "$PREVIOUS_LINK_TMP" "$ROOT/previous"
    PREVIOUS_LINK_TMP=""
fi

CURRENT_LINK_TMP="$ROOT/.current.new.$$"
[[ ! -e "$CURRENT_LINK_TMP" && ! -L "$CURRENT_LINK_TMP" ]] || fail 'temporary current symlink already exists.'
ln -s "$RELEASE_REL" "$CURRENT_LINK_TMP"
mv -Tf -- "$CURRENT_LINK_TMP" "$ROOT/current"
CURRENT_LINK_TMP=""

printf 'Exported revision %s to %s; current now points to %s.\n' "$SHA" "$ROOT" "$RELEASE_REL"
