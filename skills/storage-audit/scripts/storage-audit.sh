#!/usr/bin/env bash
# shellcheck shell=bash
# Read-only workspace and repository storage auditor. It never deletes files.
set -euo pipefail
export LC_ALL=C
export TZ=UTC

ROOT=""
MODE=""
SCOPE="auto"
STRICT="true"
FORMAT="markdown"

ROOT_KIB_BEFORE=0
ROOT_KIB_AFTER=0
SNAPSHOT_STATUS="unknown"
declare -a ENTRY_IDS=()
declare -a ENTRY_CLASSES=()
declare -a ENTRY_PATHS=()
declare -a ENTRY_KIB=()
declare -a ENTRY_REASONS=()
declare -a ENTRY_REBUILDS=()
declare -a ENTRY_ELIGIBLE=()
declare -a REQUESTED_IDS=()
declare -a PROJECT_PATHS=()
declare -a PROJECT_KIB=()
declare -a PROJECT_GIT_STATUS=()
declare -a PROJECT_LAST_COMMIT=()
declare -a PROJECT_PROCESS_COUNT=()
declare -a PROJECT_WORKTREE_COUNT=()

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage:
  storage-audit.sh audit --root PATH [--scope auto|workspace|repo] [--strict|--fast] [--format markdown|json]
  storage-audit.sh plan --root PATH --candidate A-001 [--candidate A-002]

All modes are read-only. plan only prints commands; it never executes them.
EOF
}

canonical_dir() {
    [ -d "$1" ] || die "directory does not exist: $1"
    (
        cd -P -- "$1"
        pwd -P
    )
}

du_kib() {
    local kib
    kib=$(du -skx "$1" 2>/dev/null | awk 'NR == 1 { print $1 }') || die "cannot measure: $1"
    case "$kib" in
        ''|*[!0-9]*) die "invalid size result for: $1" ;;
    esac
    printf '%s\n' "$kib"
}

json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

shell_quote() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

has_unsupported_name() {
    local path
    while IFS= read -r -d '' path; do
        case "$path" in
            *$'\n'*|*$'\r'*|*$'\t'*|*$'\001'*|*$'\002'*|*$'\003'*|*$'\004'*|*$'\005'*|*$'\006'*|*$'\007'*|*$'\010'*|*$'\013'*|*$'\014'*|*$'\016'*|*$'\017'*)
                printf '%s\n' "$path"
                return 0
                ;;
        esac
    done < <(find -P "$ROOT" -print0 2>/dev/null)
    return 1
}

is_git_repo() {
    git -C "$1" rev-parse --is-inside-work-tree >/dev/null 2>&1
}

is_ignored() {
    local repo=$1
    local path=$2
    local relative
    relative=${path#"$repo"/}
    git -C "$repo" check-ignore -q -- "$relative"
}

add_entry() {
    ENTRY_IDS+=("$1")
    ENTRY_CLASSES+=("$2")
    ENTRY_PATHS+=("$3")
    ENTRY_KIB+=("$4")
    ENTRY_REASONS+=("$5")
    ENTRY_REBUILDS+=("$6")
    ENTRY_ELIGIBLE+=("$7")
}

add_project() {
    PROJECT_PATHS+=("$1")
    PROJECT_KIB+=("$2")
    PROJECT_GIT_STATUS+=("$3")
    PROJECT_LAST_COMMIT+=("$4")
    PROJECT_PROCESS_COUNT+=("$5")
    PROJECT_WORKTREE_COUNT+=("$6")
}

project_git_status() {
    local changed
    if ! is_git_repo "$1"; then
        printf 'not-a-repository\n'
        return
    fi
    changed=$(git -C "$1" status --porcelain=v1 --untracked-files=normal 2>/dev/null | awk 'END { print NR + 0 }')
    if [ "$changed" -eq 0 ]; then
        printf 'clean\n'
    else
        printf 'dirty\n'
    fi
}

project_last_commit() {
    git -C "$1" log -1 --format='%cs' 2>/dev/null || printf 'unknown\n'
}

project_process_count() {
    if ! command -v lsof >/dev/null 2>&1; then
        printf '%s\n' '-1'
        return
    fi
    (lsof -nP +D "$1" 2>/dev/null || true) | awk 'NR > 1 { seen[$2] = 1 } END { count = 0; for (pid in seen) { count++ }; print count }'
}
project_worktree_count() {
    if ! is_git_repo "$1"; then
        printf '0\n'
        return
    fi
    git -C "$1" worktree list --porcelain 2>/dev/null | awk '$1 == "worktree" { count++ } END { print count + 0 }'
}
discover_workspace_projects() {
    {
        find -P "$ROOT" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null
        find -P "$ROOT" -mindepth 2 -maxdepth 5 \
            \( -type d -name .git -print -prune \) -o \
            \( -type d \( -name target -o -name node_modules -o -name .venv \) -prune \) \
            2>/dev/null | sed 's#/.git$##'
    } | sort -u
}
collect_projects() {
    local project base kib git_status last_commit process_count worktree_count
    local -a projects=()

    case "$SCOPE" in
        repo)
            projects=("$ROOT")
            ;;
        auto)
            if is_git_repo "$ROOT" || [ -f "$ROOT/Cargo.toml" ] || [ -f "$ROOT/pyproject.toml" ] || [ -f "$ROOT/package.json" ]; then
                projects=("$ROOT")
            else
                while IFS= read -r project; do
                    projects+=("$project")
                done < <(discover_workspace_projects)
            fi
            ;;
        workspace)
            while IFS= read -r project; do
                projects+=("$project")
            done < <(discover_workspace_projects)
            ;;
        *) die "invalid scope: $SCOPE" ;;
    esac

    declare -a eligible_records=()
    declare -a protected_records=()

    for project in "${projects[@]}"; do
        [ -L "$project" ] && continue
        base=${project##*/}
        kib=$(du_kib "$project")
        git_status=$(project_git_status "$project")
        last_commit=$(project_last_commit "$project")
        process_count=$(project_process_count "$project")
        worktree_count=$(project_worktree_count "$project")
        add_project "$project" "$kib" "$git_status" "$last_commit" "$process_count" "$worktree_count"

        case "$base" in
            data|dataset|datasets|corpus|corpora|results|checkpoints|models|embeddings|graphs)
                protected_records+=("$kib"$'\t'"$project"$'\t'"local-data"$'\t'"local data or derived results"$'\t'"retain or archive review")
                continue
                ;;
        esac

        if [ -d "$project/target" ] && [ "$process_count" -eq 0 ] && [ -f "$project/Cargo.toml" ] && is_git_repo "$project" && is_ignored "$project" "$project/target"; then
            kib=$(du_kib "$project/target")
            eligible_records+=("$kib"$'\t'"$project/target"$'\t'"rebuildable"$'\t'"ignored Cargo build output"$'\t'"cargo build")
        fi

        if [ -d "$project/node_modules" ] && [ "$process_count" -eq 0 ] && [ -f "$project/package.json" ] && is_git_repo "$project" && is_ignored "$project" "$project/node_modules"; then
            if [ -f "$project/bun.lock" ] || [ -f "$project/bun.lockb" ] || [ -f "$project/pnpm-lock.yaml" ] || [ -f "$project/yarn.lock" ] || [ -f "$project/package-lock.json" ]; then
                kib=$(du_kib "$project/node_modules")
                eligible_records+=("$kib"$'\t'"$project/node_modules"$'\t'"rebuildable"$'\t'"ignored package dependencies with lockfile"$'\t'"install dependencies from the lockfile")
            fi
        fi

        if [ -d "$project/.venv" ] && [ "$process_count" -eq 0 ] && [ -f "$project/pyproject.toml" ] && is_git_repo "$project" && is_ignored "$project" "$project/.venv"; then
            if [ -f "$project/uv.lock" ] || [ -f "$project/requirements.txt" ]; then
                kib=$(du_kib "$project/.venv")
                eligible_records+=("$kib"$'\t'"$project/.venv"$'\t'"rebuildable"$'\t'"ignored Python environment with dependency manifest"$'\t'"uv sync or the project environment command")
            fi
        fi
        local cache
        for cache in .mypy_cache .pytest_cache .ruff_cache; do
            if [ -d "$project/$cache" ] && [ "$process_count" -eq 0 ] && is_git_repo "$project" && is_ignored "$project" "$project/$cache"; then
                kib=$(du_kib "$project/$cache")
                eligible_records+=("$kib"$'\t'"$project/$cache"$'\t'"rebuildable"$'\t'"ignored analysis or test cache"$'\t'"rerun the producing tool")
            fi
        done

        if [ -d "$project/.archex" ]; then
            kib=$(du_kib "$project/.archex")
            protected_records+=("$kib"$'\t'"$project/.archex"$'\t'"derived-review"$'\t'"retrieval index may require reindexing"$'\t'"review index provenance before removal")
        fi
        if [ -d "$project/.worktrees" ]; then
            kib=$(du_kib "$project/.worktrees")
            protected_records+=("$kib"$'\t'"$project/.worktrees"$'\t'"git-protected"$'\t'"worktree directory requires Git safety review"$'\t'"retain until a worktree-specific audit clears it")
        fi
    done

    local record size path class reason rebuild entry_id counter=1
    while IFS=$'\t' read -r size path class reason rebuild; do
        [ -n "$path" ] || continue
        printf -v entry_id 'A-%03d' "$counter"
        add_entry "$entry_id" "$class" "$path" "$size" "$reason" "$rebuild" "true"
        counter=$((counter + 1))
    done < <(printf '%s\n' "${eligible_records[@]:-}" | awk 'NF' | sort -t $'\t' -k1,1nr -k2,2)

    counter=1
    while IFS=$'\t' read -r size path class reason rebuild; do
        [ -n "$path" ] || continue
        printf -v entry_id 'P-%03d' "$counter"
        add_entry "$entry_id" "$class" "$path" "$size" "$reason" "$rebuild" "false"
        counter=$((counter + 1))
    done < <(printf '%s\n' "${protected_records[@]:-}" | awk 'NF' | sort -t $'\t' -k1,1nr -k2,2)
}

scan() {
    ROOT=$(canonical_dir "$ROOT")
    [ "$ROOT" != "/" ] || die "filesystem root is not an audit target"
    [ ! -L "$ROOT" ] || die "symlink roots are not supported"

    local unsupported
    if unsupported=$(has_unsupported_name); then
        die "unsupported control character in path: $unsupported"
    fi

    ENTRY_IDS=()
    ENTRY_CLASSES=()
    ENTRY_PATHS=()
    ENTRY_KIB=()
    ENTRY_REASONS=()
    ENTRY_REBUILDS=()
    PROJECT_WORKTREE_COUNT=()
    ENTRY_ELIGIBLE=()
    PROJECT_PATHS=()
    PROJECT_KIB=()
    PROJECT_GIT_STATUS=()
    PROJECT_LAST_COMMIT=()
    PROJECT_PROCESS_COUNT=()

    ROOT_KIB_BEFORE=$(du_kib "$ROOT")
    collect_projects
    ROOT_KIB_AFTER=$(du_kib "$ROOT")
    if [ "$STRICT" = "true" ] && [ "$ROOT_KIB_BEFORE" = "$ROOT_KIB_AFTER" ]; then
        SNAPSHOT_STATUS="stable"
    elif [ "$STRICT" = "true" ]; then
        SNAPSHOT_STATUS="unstable"
    else
        SNAPSHOT_STATUS="fast"
    fi
}

render_json() {
    local i comma=""
    printf '{"root":"%s","scope":"%s","strict":%s,"status":"%s","allocated_kib":%s,"projects":[' \
        "$(json_escape "$ROOT")" "$SCOPE" "$STRICT" "$SNAPSHOT_STATUS" "$ROOT_KIB_AFTER"
    for ((i = 0; i < ${#PROJECT_PATHS[@]}; i++)); do
        printf '%s{"path":"%s","allocated_kib":%s,"git_status":"%s","last_commit":"%s","process_count":%s,"worktree_count":%s}' \
            "$comma" \
            "$(json_escape "${PROJECT_PATHS[$i]}")" \
            "${PROJECT_KIB[$i]}" \
            "${PROJECT_GIT_STATUS[$i]}" \
            "${PROJECT_LAST_COMMIT[$i]}" \
            "${PROJECT_PROCESS_COUNT[$i]}" \
            "${PROJECT_WORKTREE_COUNT[$i]}"
        comma=","
    done
    printf '],"entries":['
    comma=""
    for ((i = 0; i < ${#ENTRY_IDS[@]}; i++)); do
        printf '%s{"id":"%s","class":"%s","path":"%s","allocated_kib":%s,"reason":"%s","rebuild":"%s","cleanup_eligible":%s}' \
            "$comma" \
            "${ENTRY_IDS[$i]}" \
            "${ENTRY_CLASSES[$i]}" \
            "$(json_escape "${ENTRY_PATHS[$i]}")" \
            "${ENTRY_KIB[$i]}" \
            "$(json_escape "${ENTRY_REASONS[$i]}")" \
            "$(json_escape "${ENTRY_REBUILDS[$i]}")" \
            "${ENTRY_ELIGIBLE[$i]}"
        comma=","
    done
    printf ']}\n'
}

render_markdown() {
    local i
    printf '# Storage audit — READ-ONLY\n\n'
    printf 'Root: `%s`\n\n' "$ROOT"
    printf 'Snapshot: **%s** · Allocated size: **%s KiB**\n\n' "$SNAPSHOT_STATUS" "$ROOT_KIB_AFTER"
    printf '| ID | Class | KiB | Path | Action |\n|---|---|---:|---|---|\n'
    for ((i = 0; i < ${#ENTRY_IDS[@]}; i++)); do
        printf '| %s | %s | %s | `%s` | %s |\n' \
            "${ENTRY_IDS[$i]}" \
            "${ENTRY_CLASSES[$i]}" \
            "${ENTRY_KIB[$i]}" \
            "${ENTRY_PATHS[$i]}" \
            "${ENTRY_REBUILDS[$i]}"
    done
    if [ "$SNAPSHOT_STATUS" != "stable" ]; then
        printf '\nCleanup script suppressed: rerun a strict audit on a quiescent filesystem.\n'
    fi
}

render_plan() {
    [ "$SNAPSHOT_STATUS" = "stable" ] || die "cleanup plan requires a stable strict audit"
    local requested found i
    local -a selected_paths=()

    for requested in "${REQUESTED_IDS[@]}"; do
        found="false"
        for ((i = 0; i < ${#ENTRY_IDS[@]}; i++)); do
            [ "${ENTRY_IDS[$i]}" = "$requested" ] || continue
            found="true"
            [ "${ENTRY_ELIGIBLE[$i]}" = "true" ] || die "candidate '$requested' is not cleanup-eligible"
            selected_paths+=("${ENTRY_PATHS[$i]}")
        done
        [ "$found" = "true" ] || die "candidate '$requested' is not cleanup-eligible"
    done

    printf '#!/usr/bin/env bash\n'
    printf '# Generated by storage-audit.sh plan. Review before running.\n'
    printf 'set -euo pipefail\n\n'
    printf 'readonly AUDIT_ROOT=%s\n' "$(shell_quote "$ROOT")"
    printf 'TARGETS=(\n'
    for target in "${selected_paths[@]}"; do
        printf '    %s\n' "$(shell_quote "$target")"
    done
    cat <<'EOF'
)

case "$#" in
    0)
        printf 'Preview only. Review targets, then run: %s --execute\n' "$0"
        printf '%s\n' "${TARGETS[@]}"
        exit 0
        ;;
    1) [ "$1" = '--execute' ] || { printf 'Unknown argument: %s\n' "$1" >&2; exit 64; } ;;
    *) printf 'Usage: %s [--execute]\n' "$0" >&2; exit 64 ;;
esac

for target in "${TARGETS[@]}"; do
    [ -d "$target" ] || { printf 'Missing directory: %s\n' "$target" >&2; exit 1; }
    case "$target" in
        "$AUDIT_ROOT"/*) ;;
        *) printf 'Refusing path outside audit root: %s\n' "$target" >&2; exit 1 ;;
    esac
done

printf 'Selected targets:\n'
du -sh -- "${TARGETS[@]}"
for target in "${TARGETS[@]}"; do
    printf 'Removing %s\n' "$target"
    rm -rf -- "$target"
done
EOF
}

parse_args() {
    MODE=${1:-}
    shift || true
    case "$MODE" in
        audit|plan) ;;
        -h|--help|help|'') usage; exit 0 ;;
        *) die "unknown mode: $MODE" ;;
    esac

    while [ "$#" -gt 0 ]; do
        case "$1" in
            --root)
                [ "$#" -ge 2 ] || die "--root requires a path"
                ROOT=$2
                shift 2
                ;;
            --scope)
                [ "$#" -ge 2 ] || die "--scope requires a value"
                SCOPE=$2
                shift 2
                ;;
            --strict) STRICT="true"; shift ;;
            --fast) STRICT="false"; shift ;;
            --format)
                [ "$#" -ge 2 ] || die "--format requires a value"
                FORMAT=$2
                shift 2
                ;;
            --candidate)
                [ "$#" -ge 2 ] || die "--candidate requires an ID"
                REQUESTED_IDS+=("$2")
                shift 2
                ;;
            -h|--help) usage; exit 0 ;;
            *) die "unknown option: $1" ;;
        esac
    done

    [ -n "$ROOT" ] || die "--root is required"
    if [ "$MODE" = "plan" ]; then
        [ "${#REQUESTED_IDS[@]}" -gt 0 ] || die "plan requires at least one --candidate"
        STRICT="true"
    fi
}

main() {
    parse_args "$@"
    scan
    case "$MODE" in
        audit)
            case "$FORMAT" in
                json) render_json ;;
                markdown) render_markdown ;;
                *) die "invalid format: $FORMAT" ;;
            esac
            ;;
        plan) render_plan ;;
    esac
}

main "$@"
