"""LLM バックエンド抽象化レイヤー.

LLM の呼び先を切替できるようにする。通常はリポジトリを開いているAIエージェント自身が
手順書を読み、Pythonから別のAIを子プロセス起動しない:

- ``none``（既定）: 外部LLMを呼ばない。機械診断のみ。
- ``claude_cli``: 明示指定時だけ `claude -p` を subprocess で呼ぶ。
- ``anthropic_api``: Anthropic SDK を使う（``ANTHROPIC_API_KEY`` 必須）。
- ``api``: ``anthropic_api`` の後方互換エイリアス。

選択の優先順位: 引数 ``backend`` > 環境変数 ``LLM_BACKEND`` > 既定 ``none``。

各モジュール（decomposer / standardizer / diagnoser / generator）はこの
``complete_json`` / ``complete_text`` だけを呼ぶ。SDK を直叩きしない。
"""

from __future__ import annotations

import json
import os
import re
import subprocess

DEFAULT_BACKEND = "none"

# claude -p を「クリーンなテキスト生成」として振る舞わせるためのシステムプロンプト。
# 既定の Claude Code エージェント用プロンプトを置換し、前置き・ツール使用・ファイル操作を止める。
_COMPLETION_SYSTEM_PROMPT = (
    "あなたはテキスト生成エンジンです。指示された成果物の本文（JSON または Markdown）のみを出力します。"
    "前置き・後書き・説明文・相づち・ツール使用・ファイル操作は一切しません。"
    "要求された本文そのものだけを返してください。"
)

# SDK のフルモデルID → claude CLI のエイリアス
_CLI_MODEL_ALIAS = {
    "claude-sonnet-4-6": "sonnet",
    "claude-haiku-4-5-20251001": "haiku",
}


def resolve_backend(backend: str | None = None) -> str:
    return backend or os.environ.get("LLM_BACKEND") or DEFAULT_BACKEND


def llm_available(api_key: str | None = None, backend: str | None = None) -> bool:
    """明示された外部LLMバックエンドを実行できるか。"""
    b = resolve_backend(backend)
    if b == "none":
        return False
    if b == "claude_cli":
        return True
    return bool(api_key or os.environ.get("ANTHROPIC_API_KEY"))


def complete_text(
    prompt: str,
    *,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
    api_key: str | None = None,
    backend: str | None = None,
) -> str:
    """prompt を渡して生テキストを返す（Markdown 章生成など、整形なし）."""
    b = resolve_backend(backend)
    if b in {"api", "anthropic_api"}:
        return _via_api(prompt, model, max_tokens, api_key)
    if b == "claude_cli":
        return _via_claude_cli(prompt, model)
    if b == "none":
        raise RuntimeError("LLM_BACKEND=none では外部LLM補完を実行しません")
    raise ValueError(f"未知の LLM_BACKEND: {b}（none | claude_cli | anthropic_api）")


def complete_json(
    prompt: str,
    *,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
    api_key: str | None = None,
    backend: str | None = None,
) -> str:
    """prompt を渡して JSON 文字列を返す（```フェンス除去済み。呼び出し側で json.loads する）."""
    raw = complete_text(
        prompt, model=model, max_tokens=max_tokens, api_key=api_key, backend=backend
    )
    return _strip_code_fence(raw)


def _via_api(prompt: str, model: str, max_tokens: int, api_key: str | None) -> str:
    import anthropic

    # api_key=None / ダミー値の場合は env ANTHROPIC_API_KEY を使う
    key = api_key if (api_key and api_key.startswith("sk-")) else None
    client = anthropic.Anthropic(api_key=key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _via_claude_cli(prompt: str, model: str) -> str:
    cli_model = _CLI_MODEL_ALIAS.get(model, model)
    cmd = [
        "claude",
        "-p",
        # prompt はコマンドライン引数ではなく標準入力で渡す（`claude -p` はstdin入力に対応）。
        # 引数渡しだとWindowsのコマンドライン長上限（約32,767文字）を超えると
        # `[WinError 206] ファイル名または拡張子が長すぎます。` で失敗するため（GTMデータ追加で顕在化）。
        # stdin渡しはOSを問わず動くのでOS分岐は不要。
        "--model",
        cli_model,
        "--output-format",
        "json",
        # エージェント用システムプロンプトを置換し、前置き・ツール使用を止める
        "--system-prompt",
        _COMPLETION_SYSTEM_PROMPT,
        # ツールを無効化（ファイル操作などのエージェント挙動を防ぐ）
        "--tools",
        "",
        # MCP/ツールを排除してクリーンな補完にする（context削減）
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers": {}}',
    ]
    # encoding を明示しないと Windows では locale（cp932）で復号され、
    # 日本語を含む出力が UnicodeDecodeError になる（stdout が None になり後段で落ちる）。
    # errors="replace" で、万一デコードできないバイト列があっても例外にせず続行する。
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude -p 失敗 (code {proc.returncode}): {proc.stderr.strip()[:500]}"
        )
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"claude -p の出力を JSON として解釈できません: {proc.stdout[:300]}"
        ) from e
    if env.get("is_error"):
        raise RuntimeError(f"claude -p エラー: {str(env.get('result', ''))[:300]}")
    return env.get("result", "")


def _strip_code_fence(text: str) -> str:
    """```json ... ``` / ``` ... ``` で囲まれていれば中身だけ取り出す."""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", t, re.S)
    return m.group(1).strip() if m else t
