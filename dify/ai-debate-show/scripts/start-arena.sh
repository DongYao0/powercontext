#!/usr/bin/env sh
# ==========================================================================
#  《再说一遍？AI 记仇辩论夜》Arena 服务启动脚本（Unix）
#
#  行为约定：
#    * 只做检查与启动，不安装任何依赖；
#    * 端口被占用时只提示 PID 并安全退出，不结束任何进程；
#    * 服务在前台运行，日志写入项目内 logs/ 目录；
#    * 不读取、不输出、不记录任何令牌的具体值。
#
#  首次使用请先执行：chmod +x scripts/start-arena.sh
# ==========================================================================
set -eu

# --- 1. 定位项目目录（由脚本自身位置推导，不依赖当前工作目录） ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# --- 2. 端口 ---
ARENA_PORT="${ARENA_PORT:-8088}"

# --- 3. 检查 python3 ---
if ! command -v python3 >/dev/null 2>&1; then
  echo "[错误] 找不到可执行的 python3。" >&2
  echo "       请先安装 Python 3.11 或更高版本，并确保 python3 已经在 PATH 中。" >&2
  exit 1
fi

# --- 4. 检查端口占用（只提示，不结束进程） ---
detect_port_pid() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${ARENA_PORT}" -sTCP:LISTEN -t 2>/dev/null | head -n 1
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null \
      | grep -E "[:.]${ARENA_PORT}[[:space:]]" \
      | grep -oE 'pid=[0-9]+' \
      | head -n 1 \
      | cut -d= -f2
  fi
}

PORT_PID="$(detect_port_pid || true)"
if [ -n "${PORT_PID}" ]; then
  echo "[警告] 端口 ${ARENA_PORT} 已经被占用，PID 为 ${PORT_PID}。" >&2
  echo "       本脚本不会自动结束任何进程。请先自行处理该进程，" >&2
  echo "       或用 ARENA_PORT 环境变量换一个端口后重试。" >&2
  exit 2
fi

# --- 5. 日志目录与带时间戳的日志文件 ---
LOG_DIR="${PROJECT_DIR}/logs"
mkdir -p "${LOG_DIR}"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="${LOG_DIR}/arena-${STAMP}.log"

# --- 6. 提示信息 ---
echo "[信息] 项目目录：${PROJECT_DIR}"
echo "[信息] 监听端口：${ARENA_PORT}"
if [ -n "${POWERCONTEXT_BASE_URL:-}" ]; then
  echo "[信息] 记忆能力：已配置，将召回历史并写入结算记忆。"
else
  echo "[信息] 记忆能力：未配置，本场没有跨会话翻旧账，对局照常可玩。"
fi
echo "[信息] 日志文件：${LOG_FILE}"
echo "[信息] 按 Ctrl+C 停止服务。"
echo "[信息] 实时查看日志：tail -f ${LOG_FILE}"
echo

# --- 7. 前台启动 ---
export PYTHONPATH="${PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONUNBUFFERED=1
# 让日志文件固定写成 UTF-8，不受终端区域设置影响
export PYTHONIOENCODING=utf-8
cd "${PROJECT_DIR}"
python3 -m arena_service.server >>"${LOG_FILE}" 2>&1
