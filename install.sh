#!/usr/bin/env bash
# 安装信息监理 skill 套件到各类 Agent。
# 用法：
#   ./install.sh claude          # ~/.claude/skills
#   ./install.sh workbuddy       # ~/.workbuddy/skills
#   ./install.sh codebuddy       # ~/.codebuddy/skills
#   ./install.sh copilot         # ~/.copilot/skills
#   ./install.sh codex           # ~/.codex/skills
#   ./install.sh project <dir>   # <dir>/.claude/skills 与 <dir>/.codebuddy/skills（项目级）
#   ./install.sh path <dir>      # 安装到任意目录
#   ./install.sh zip             # 打包到 dist/，供 GUI 方式导入
# 可加 --link 使用软链接（便于 git pull 后自动更新）。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$REPO_DIR/skills"
MODE="copy"
ARGS=()
for a in "$@"; do
  if [[ "$a" == "--link" ]]; then MODE="link"; else ARGS+=("$a"); fi
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

install_to() {
  local dest="$1"
  mkdir -p "$dest"
  for skill in "$SKILLS_DIR"/*/; do
    local name; name="$(basename "$skill")"
    rm -rf "${dest:?}/$name"
    if [[ "$MODE" == "link" ]]; then
      ln -s "${skill%/}" "$dest/$name"
    else
      cp -R "${skill%/}" "$dest/$name"
      find "$dest/$name" -name '__pycache__' -type d -prune -exec rm -rf {} +
    fi
    echo "  ✓ $name"
  done
  echo "已安装到：${dest}"
}

make_zip() {
  local dist="$REPO_DIR/dist"
  rm -rf "$dist" && mkdir -p "$dist"
  # 用 Python zipfile 打包，中文文件名带 UTF-8 标记，Windows / WorkBuddy 导入不乱码
  python3 - "$SKILLS_DIR" "$dist" <<'PY'
import sys, zipfile
from pathlib import Path
src, dist = Path(sys.argv[1]), Path(sys.argv[2])
def pack(target, roots):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for root in roots:
            for f in sorted(root.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts and f.name != ".DS_Store":
                    z.write(f, f.relative_to(src).as_posix())
skills = sorted(p for p in src.iterdir() if p.is_dir())
pack(dist / "it-supervision-skills.zip", skills)
for s in skills:
    pack(dist / f"{s.name}.zip", [s])
PY
  echo "已打包到：${dist}（子 skill 依赖 it-supervision-core，请一并导入）"
}

[[ $# -ge 1 ]] || usage
case "$1" in
  claude)    install_to "$HOME/.claude/skills" ;;
  workbuddy) install_to "$HOME/.workbuddy/skills" ;;
  codebuddy) install_to "$HOME/.codebuddy/skills" ;;
  copilot)   install_to "$HOME/.copilot/skills" ;;
  codex)     install_to "$HOME/.codex/skills" ;;
  project)   [[ $# -ge 2 ]] || usage; install_to "$2/.claude/skills"; install_to "$2/.codebuddy/skills" ;;
  path)      [[ $# -ge 2 ]] || usage; install_to "$2" ;;
  zip)       make_zip ;;
  *)         usage ;;
esac

if ! python3 -c "import docx" 2>/dev/null; then
  echo "提示：渲染 DOCX 需要 python-docx，请执行：python3 -m pip install python-docx"
fi
