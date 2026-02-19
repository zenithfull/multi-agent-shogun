#!/bin/bash
# test_grep.sh - Debug script for grep fallback logic

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# settings.yaml のパス（必要に応じて修正してください）
CLI_ADAPTER_SETTINGS="$SCRIPT_DIR/config/settings.yaml"

echo "Checking settings file at: $CLI_ADAPTER_SETTINGS"

if [ ! -f "$CLI_ADAPTER_SETTINGS" ]; then
    echo "Error: settings.yaml not found at $CLI_ADAPTER_SETTINGS"
    echo "Current directory: $(pwd)"
    ls -l "$SCRIPT_DIR/config"
    exit 1
fi

echo "--- File Content Start ---"
cat "$CLI_ADAPTER_SETTINGS"
echo "--- File Content End ---"

# テスト対象のキー: cli.default -> "default"
key_path="cli.default"
key_name="${key_path##*.}"

echo "Searching for key: $key_name"

# lib/cli_adapter.sh と同じ grep コマンド
match=$(grep -E "^[[:space:]]*${key_name}:" "$CLI_ADAPTER_SETTINGS" 2>/dev/null | head -n 1)

echo "Grep match result: '$match'"
echo "Exit code: $?"

if [[ -n "$match" ]]; then
    # 抽出ロジック
    value=$(echo "$match" | sed -E "s/^[[:space:]]*${key_name}:[[:space:]]*//; s/[[:space:]]*#.*//")
    value=$(echo "$value" | sed -E 's/^"//; s/"$//; s/^'"'"'//; s/'"'"'$//')
    echo "Extracted value: '$value'"
else
    echo "No match found."
    # 念のため単純なgrepでも試す
    echo "Trying simple grep..."
    grep "default:" "$CLI_ADAPTER_SETTINGS"
fi