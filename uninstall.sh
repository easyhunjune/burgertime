#!/bin/bash
# launchd 등록을 해제한다. results/ 의 기록은 지우지 않는다.
set -euo pipefail

LABEL="com.burgertime.bench"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "해제 완료. 측정 기록(results/)은 그대로 남아 있습니다."
