#!/bin/bash
# macOS launchd에 버거타임 측정기를 등록한다. 다시 실행하면 설정을 새로 반영한다.
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.burgertime.bench"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "macOS 전용 설치 스크립트입니다."
  exit 1
fi

# launchd로 실행되는 프로그램은 개인정보 보호(TCC) 때문에 데스크탑·문서·다운로드·iCloud 폴더에 접근이 막힐 수 있다.
case "$BENCH_DIR" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*|"$HOME/Library/Mobile Documents"*)
    echo "이 폴더($BENCH_DIR)는 macOS가 백그라운드 접근을 막는 위치입니다."
    echo "홈 바로 아래(예: ~/burgertime)로 옮긴 뒤 다시 실행하세요."
    exit 1
    ;;
esac

# SSH로 들어와 실행하면 PATH가 /usr/bin:/bin 정도라 launchd 작업이 CLI(와 codex가 쓰는 node)를 못 찾는다.
# 로그인 셸의 PATH를 받아 쓰고, Homebrew 경로가 빠져 있으면 덧붙인다.
LOGIN_PATH="$(/bin/zsh -l -c 'printf %s "$PATH"' 2>/dev/null || true)"
JOB_PATH="${LOGIN_PATH:-$PATH}"
for d in /opt/homebrew/bin /usr/local/bin; do
  case ":$JOB_PATH:" in
    *":$d:"*) ;;
    *) [[ -d "$d" ]] && JOB_PATH="$JOB_PATH:$d" ;;
  esac
done
export PATH="$JOB_PATH"

PY="$(command -v python3 || true)"
if [[ -z "$PY" ]]; then
  echo "python3를 찾을 수 없습니다. (xcode-select --install 또는 Homebrew python)"
  exit 1
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "Python 3.9 이상이 필요합니다: $("$PY" --version)"
  exit 1
}

if [[ -f "$HOME/.codex/AGENTS.md" ]]; then
  echo "참고: ~/.codex/AGENTS.md 가 있습니다. Codex 측정에도 반영될 수 있으니 측정 기간에는 내용을 바꾸지 마세요."
fi

echo
"$PY" "$BENCH_DIR/run_bench.py" selftest
echo

INTERVAL_SEC="$("$PY" -c 'import json,sys; print(int(json.load(open(sys.argv[1]))["ping_interval_min"]) * 60)' "$BENCH_DIR/config.json")"
mkdir -p "$HOME/Library/LaunchAgents" "$BENCH_DIR/results"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-i</string>
    <string>$PY</string>
    <string>$BENCH_DIR/run_bench.py</string>
    <string>tick</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$BENCH_DIR</string>
  <key>StartInterval</key>
  <integer>$INTERVAL_SEC</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>AbandonProcessGroup</key>
  <true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$PATH</string>
    <key>HOME</key>
    <string>$HOME</string>
    <key>LANG</key>
    <string>en_US.UTF-8</string>
  </dict>
  <key>StandardOutPath</key>
  <string>$BENCH_DIR/results/launchd.log</string>
  <key>StandardErrorPath</key>
  <string>$BENCH_DIR/results/launchd.log</string>
</dict>
</plist>
EOF

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
# bootout은 기존 작업이 완전히 내려가기 전에 돌아올 수 있다. 내려갈 때까지 최대 10초 기다린다.
for _ in $(seq 1 20); do
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
  sleep 0.5
done
if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
  echo "bootstrap 재시도 중..."
  sleep 2
  launchctl bootstrap "$DOMAIN" "$PLIST"
fi
launchctl enable "$DOMAIN/$LABEL"

echo "등록 완료: $PLIST"
echo "  ${INTERVAL_SEC}초마다 ping, config.json의 quality_every_hours 간격으로 코딩 과제를 돌립니다."
echo "  지금 바로 첫 ping이 실행됩니다. 1~2분 뒤 확인: python3 run_bench.py status"
echo "  로그: $BENCH_DIR/results/launchd.log, $BENCH_DIR/results/quality.log"
echo "  해제: ./uninstall.sh"
