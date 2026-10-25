#!/usr/bin/env bash
# NewsHub 引导式 UAT 一键启动：加载凭据 → 健康检查 → headed Playwright 走查
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

# 允许 NEWSHUB_REPO 覆盖；否则用脚本所在仓库根，再回退常见本机路径
if [[ -n "${NEWSHUB_REPO:-}" ]]; then
  REPO_ROOT="$(cd -- "$NEWSHUB_REPO" && pwd)"
elif [[ ! -f "$REPO_ROOT/ops/acceptance/guided_uat.py" ]]; then
  DEFAULT_REPO="${HOME}/githubRepos/lambert/news-aggregator"
  if [[ -f "$DEFAULT_REPO/ops/acceptance/guided_uat.py" ]]; then
    REPO_ROOT="$DEFAULT_REPO"
  fi
fi

cd -- "$REPO_ROOT"

GUIDED="$REPO_ROOT/ops/acceptance/guided_uat.py"
if [[ ! -f "$GUIDED" ]]; then
  echo "❌ 找不到 guided_uat.py：$GUIDED" >&2
  echo "   请在 news-aggregator 仓库内运行，或设置 NEWSHUB_REPO=/path/to/news-aggregator" >&2
  exit 1
fi

_python_has_playwright() {
  local bin="$1"
  [[ -x "$bin" ]] || return 1
  "$bin" -c 'from playwright.sync_api import sync_playwright' >/dev/null 2>&1
}

_resolve_python() {
  local candidates=()
  if [[ -n "${NEWSHUB_PYTHON:-}" ]]; then
    candidates+=("$NEWSHUB_PYTHON")
  fi
  candidates+=(
    "/usr/bin/python3"
    "$REPO_ROOT/backend/venv/bin/python"
    "$REPO_ROOT/backend/venv/bin/python3"
    "${XDG_DATA_HOME:-$HOME/.local/share}/newshub-tools/playwright-1.62.0-py3.12/bin/python"
    "$(command -v python3 2>/dev/null || true)"
  )
  local bin
  for bin in "${candidates[@]}"; do
    [[ -n "$bin" ]] || continue
    if _python_has_playwright "$bin"; then
      printf '%s\n' "$bin"
      return 0
    fi
  done
  return 1
}

if ! PYTHON_BIN="$(_resolve_python)"; then
  echo "❌ 未找到已安装 Playwright 的 Python。" >&2
  echo "   请任选其一：" >&2
  echo "     /usr/bin/python3 -m pip install --user 'playwright>=1.40'" >&2
  echo "     /usr/bin/python3 -m playwright install chromium" >&2
  echo "   或使用仓库 venv / 设置 NEWSHUB_PYTHON=/path/to/python" >&2
  echo "   或设置系统 Chromium：export NEWSHUB_ACCEPTANCE_CHROMIUM=/usr/bin/chromium" >&2
  exit 1
fi

echo "[启动] 仓库：$REPO_ROOT"
echo "[启动] Python：$PYTHON_BIN"

# —— 安全加载本地 env（不 echo 密钥值；已存在的环境变量优先）——
_load_env_file() {
  local file="$1"
  [[ -f "$file" ]] || return 1
  local line key val
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ "$line" == export\ * ]]; then
      line="${line#export }"
      line="${line#"${line%%[![:space:]]*}"}"
    fi
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    val="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    key="${key#"${key%%[![:space:]]*}"}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ "$val" =~ ^\".*\"$ ]]; then
      val="${val:1:${#val}-2}"
    elif [[ "$val" =~ ^\'.*\'$ ]]; then
      val="${val:1:${#val}-2}"
    fi
    if [[ -z "${!key+x}" ]]; then
      export "$key=$val"
    fi
  done < "$file"
  return 0
}

CRED_SOURCE="env"
_had_creds=0
if [[ -n "${NEWSHUB_ACCEPTANCE_USER:-}" && -n "${NEWSHUB_ACCEPTANCE_PASSWORD:-}" ]]; then
  _had_creds=1
fi
LOADED=""
for candidate in \
  "$REPO_ROOT/ops/acceptance/.env.local" \
  "$REPO_ROOT/.env.local" \
  "${XDG_CONFIG_HOME:-$HOME/.config}/newshub/acceptance.env" \
  "$HOME/.config/newshub/acceptance.env"
do
  if _load_env_file "$candidate"; then
    LOADED="$candidate"
    break
  fi
done
if [[ -n "$LOADED" ]]; then
  echo "[启动] 已从本地文件加载未设置的变量（不打印内容）：$LOADED"
  if [[ "$_had_creds" -eq 0 ]]; then
    CRED_SOURCE="file:$LOADED"
  fi
fi

_prompt_secret() {
  local var_name="$1" prompt="$2" required="${3:-1}" value=""
  if [[ -n "${!var_name:-}" ]]; then
    return 0
  fi
  if [[ ! -t 0 ]]; then
    if [[ "$required" == "1" ]]; then
      echo "❌ 非交互环境且未设置 $var_name；请 export 或写入 ops/acceptance/.env.local" >&2
      exit 1
    fi
    return 0
  fi
  read -r -s -p "$prompt" value
  echo >&2
  if [[ -z "$value" ]]; then
    if [[ "$required" == "1" ]]; then
      echo "❌ $var_name 不能为空" >&2
      exit 1
    fi
    return 0
  fi
  export "$var_name=$value"
}

if [[ -z "${NEWSHUB_ACCEPTANCE_USER:-}" || -z "${NEWSHUB_ACCEPTANCE_PASSWORD:-}" ]]; then
  CRED_SOURCE="prompt"
  echo "[启动] 未在环境/本地文件中找到完整登录凭据，将交互询问（输入不回显）"
  if [[ -z "${NEWSHUB_ACCEPTANCE_USER:-}" ]]; then
    if [[ -t 0 ]]; then
      read -r -p "登录用户名 [admin]: " _u
      export NEWSHUB_ACCEPTANCE_USER="${_u:-admin}"
    else
      echo "❌ 非交互环境且未设置 NEWSHUB_ACCEPTANCE_USER" >&2
      exit 1
    fi
  fi
  _prompt_secret NEWSHUB_ACCEPTANCE_PASSWORD "登录密码: " 1
fi

if [[ -z "${NEWSHUB_ACCEPTANCE_DEEPSEEK_KEY:-}" && -t 0 && "${NEWSHUB_ACCEPTANCE_PROMPT_DEEPSEEK:-0}" == "1" ]]; then
  _prompt_secret NEWSHUB_ACCEPTANCE_DEEPSEEK_KEY "可选 DeepSeek Key（直接回车跳过）: " 0
fi

_ds_status="未设置"
[[ -n "${NEWSHUB_ACCEPTANCE_DEEPSEEK_KEY:-}" ]] && _ds_status="已设置"
echo "[启动] 凭据来源：$CRED_SOURCE（用户=${NEWSHUB_ACCEPTANCE_USER:-?}；密码=已设置；DeepSeek Key=${_ds_status}）"

# —— 运行时健康检查（不自动 destroy / recreate）——
BASE_URL="${NEWSHUB_BASE_URL:-http://127.0.0.1:9527}"
BASE_URL="${BASE_URL%/}"
HEALTH_OK=0
if command -v curl >/dev/null 2>&1; then
  if curl -fsS --connect-timeout 3 --max-time 8 "$BASE_URL/" >/dev/null 2>&1 \
    || curl -fsS --connect-timeout 3 --max-time 8 "$BASE_URL/api/news/" >/dev/null 2>&1; then
    HEALTH_OK=1
  fi
elif "$PYTHON_BIN" - "$BASE_URL" <<'PY'
import sys, urllib.request
base = sys.argv[1].rstrip("/")
for path in ("/", "/api/news/"):
    try:
        urllib.request.urlopen(base + path, timeout=5)
        raise SystemExit(0)
    except Exception:
        pass
raise SystemExit(1)
PY
then
  HEALTH_OK=1
fi

if [[ "$HEALTH_OK" -ne 1 ]]; then
  echo "❌ 本地 NewsHub 未响应：$BASE_URL" >&2
  echo "   请先启动本机验收运行时（不要用会删卷的 down -v）：" >&2
  echo "     # 推荐：完整本地运行时（项目名默认 newshub-local-main）" >&2
  echo "     ./scripts/deploy/local-full-runtime.sh --help" >&2
  echo "     # 查看已有 Compose 项目：" >&2
  echo "     docker compose -p newshub-local-main ps" >&2
  echo "     # 开发脚本：" >&2
  echo "     ./scripts/news start" >&2
  echo "   启动后再运行本脚本。当前不会自动 recreate，以免误伤数据卷。" >&2
  if [[ "${NEWSHUB_ACCEPTANCE_ALLOW_DOWN:-0}" != "1" ]]; then
    exit 1
  fi
  echo "⚠️  NEWSHUB_ACCEPTANCE_ALLOW_DOWN=1，继续尝试打开浏览器…" >&2
else
  echo "[启动] 运行时可达：$BASE_URL"
fi

# 默认 headed + 中文分段暂停（与 guided_uat.py 一致）；可被已有环境变量覆盖
export NEWSHUB_BASE_URL="${NEWSHUB_BASE_URL:-$BASE_URL}"
export NEWSHUB_ACCEPTANCE_PAUSE="${NEWSHUB_ACCEPTANCE_PAUSE:-1}"
export NEWSHUB_ACCEPTANCE_SLOW_MO="${NEWSHUB_ACCEPTANCE_SLOW_MO:-400}"

echo "[启动] 执行：guided_uat.py $*（headed，PAUSE=$NEWSHUB_ACCEPTANCE_PAUSE）"
exec "$PYTHON_BIN" "$GUIDED" "$@"
