#!/usr/bin/env python3
"""
codebuddy-hud: A HUD-style status line for CodeBuddy Code.
Visual style aligned with claude-hud (github.com/jarrodwatts/claude-hud).

Line 1: [model]  │  folder  git:(branch*)
Line 2: Context [████░░░░░░] pct%
Line 3: ◐ Read: src/index.ts   ◐ Bash: npm test   (running tools, if any)

Install:
  ln -sf /data/workspace/codebuddy-hud/hud.py ~/.codebuddy/hud.py

Add to ~/.codebuddy/settings.json:
  "statusLine": {
    "type": "command",
    "command": "python3.11 ~/.codebuddy/hud.py",
    "padding": 0
  }
"""
import json
import os
import subprocess
import sys

# ---------------------------------------------------------------------------
# ANSI codes (same as claude-hud)
# ---------------------------------------------------------------------------
RESET   = '\x1b[0m'
DIM     = '\x1b[2m'
BOLD    = '\x1b[1m'
RED     = '\x1b[31m'
YELLOW  = '\x1b[33m'
GREEN   = '\x1b[32m'
BLUE    = '\x1b[34m'
MAGENTA = '\x1b[35m'
CYAN    = '\x1b[36m'
WHITE   = '\x1b[37m'

SEP = f" \u2502 "  # │

# ---------------------------------------------------------------------------
# Context window sizes
# ---------------------------------------------------------------------------
def context_window(model_id: str) -> int:
    mid = model_id.lower()
    if '1m' in mid:
        return 1_000_000
    if '200k' in mid:
        return 200_000
    return 200_000


# ---------------------------------------------------------------------------
# Context color (matches claude-hud getContextColor):
#   <70%  → green
#   70-85% → yellow
#   ≥85%  → red
# ---------------------------------------------------------------------------
def context_color(pct: float) -> str:
    if pct >= 0.85:
        return RED
    if pct >= 0.70:
        return YELLOW
    return GREEN


def make_bar(pct: float, width: int = 10) -> str:
    """Colored filled blocks + DIM empty blocks, matching claude-hud."""
    pct = max(0.0, min(1.0, pct))
    filled = round(pct * width)
    empty  = width - filled
    color  = context_color(pct)
    return f"{color}{'█' * filled}{DIM}{'░' * empty}{RESET}"


# ---------------------------------------------------------------------------
# Read transcript tail — shared helper used by multiple parsers.
# Uses explicit stdout/stderr pipes for Python 3.6 compatibility.
# ---------------------------------------------------------------------------
def _read_transcript_tail(transcript_path: str, n: int = 500) -> list:
    if not transcript_path or not os.path.exists(transcript_path):
        return []
    try:
        result = subprocess.run(
            ['tail', '-n', str(n), transcript_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=1
        )
        return result.stdout.decode('utf-8', errors='replace').splitlines()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Read latest inputTokens from transcript JSONL
# ---------------------------------------------------------------------------
def get_input_tokens(transcript_path: str) -> int:
    lines = _read_transcript_tail(transcript_path, 300)
    last_tokens = 0
    for line in reversed(lines):
        line = line.strip()
        if not line or 'inputTokens' not in line:
            continue
        try:
            entry  = json.loads(line)
            tokens = entry.get('providerData', {}).get('usage', {}).get('inputTokens', 0)
            if tokens:
                last_tokens = tokens
                break
        except Exception:
            continue
    return last_tokens


# ---------------------------------------------------------------------------
# Extract a short human-readable target from a tool call's arguments dict
# ---------------------------------------------------------------------------
def _tool_target(name: str, inp: dict) -> str:
    """Return a short target string for a tool call, e.g. filename or command."""
    # File-oriented tools
    for key in ('file_path', 'path', 'pattern', 'glob'):
        val = inp.get(key, '')
        if val:
            # Show only last two path segments to keep it short
            parts = val.replace('\\', '/').rstrip('/').split('/')
            return '/'.join(parts[-2:]) if len(parts) > 1 else parts[0]
    # Bash: first 35 chars of command
    cmd = inp.get('command', '')
    if cmd:
        cmd = cmd.strip().split('\n')[0]
        return cmd[:35] + ('…' if len(cmd) > 35 else '')
    # description / query fallback
    for key in ('description', 'query', 'prompt'):
        val = inp.get(key, '')
        if val:
            return str(val)[:35] + ('…' if len(str(val)) > 35 else '')
    return ''


# ---------------------------------------------------------------------------
# Get running tools: function_call entries with no matching function_call_result
# CodeBuddy transcript format uses flat JSONL entries:
#   {"type":"function_call",  "callId":"...", "name":"Read", "arguments":"{...}"}
#   {"type":"function_call_result", "callId":"...", "status":"completed", ...}
# ---------------------------------------------------------------------------
def get_running_tools(transcript_path: str) -> list:
    """
    Returns list of (tool_name, target_str) for tools currently in flight.
    Looks at the last 500 lines of the transcript for speed.
    """
    lines = _read_transcript_tail(transcript_path, 500)

    tool_calls  = {}   # callId -> (name, target)
    result_ids  = set()

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        # Fast pre-filter to skip irrelevant lines
        if 'function_call' not in raw:
            continue
        try:
            entry = json.loads(raw)
        except Exception:
            continue

        etype = entry.get('type', '')
        if etype == 'function_call':
            cid  = entry.get('callId', '')
            name = entry.get('name', '')
            # arguments is a JSON string in the real format
            args_raw = entry.get('arguments', '{}') or '{}'
            try:
                inp = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except Exception:
                inp = {}
            if cid and name:
                tool_calls[cid] = (name, _tool_target(name, inp))
        elif etype == 'function_call_result':
            cid = entry.get('callId', '')
            if cid:
                result_ids.add(cid)

    running = [
        (name, target)
        for cid, (name, target) in tool_calls.items()
        if cid not in result_ids
    ]
    # Return at most 2, most-recent first (dict preserves insertion order in Py3.7+)
    return running[-2:][::-1]


# ---------------------------------------------------------------------------
# Render the running-tools line (Line 3)
# ---------------------------------------------------------------------------
def fmt_tools_line(running: list) -> str:
    if not running:
        return ''
    parts = []
    for name, target in running:
        label = f"{YELLOW}◐{RESET} {CYAN}{name}{RESET}"
        if target:
            label += f"{DIM}:{RESET} {target}"
        parts.append(label)
    return '   '.join(parts)


# ---------------------------------------------------------------------------
# Git info in claude-hud style: git:(branch*)
# ---------------------------------------------------------------------------
def get_git_info(cwd: str) -> str:
    try:
        branch = subprocess.check_output(
            ['git', '-C', cwd, 'branch', '--show-current'],
            stderr=subprocess.DEVNULL, timeout=1
        ).decode().strip()
        if not branch:
            return ''
        dirty = ''
        try:
            subprocess.check_output(
                ['git', '-C', cwd, 'diff-index', '--quiet', 'HEAD', '--'],
                stderr=subprocess.DEVNULL, timeout=1
            )
        except subprocess.CalledProcessError:
            dirty = '*'
        # Format: git:(branch*)  — cyan parens, yellow branch
        return f"{CYAN}git:({RESET}{YELLOW}{branch}{dirty}{RESET}{CYAN}){RESET}"
    except Exception:
        return ''


# ---------------------------------------------------------------------------
# Duration  e.g. 65000ms → "1m05s", 3720000ms → "1h02m"
# ---------------------------------------------------------------------------
def fmt_duration(ms: float) -> str:
    if not ms:
        return ''
    s = int(ms / 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


# ---------------------------------------------------------------------------
# Format token count for display
# ---------------------------------------------------------------------------
def fmt_tokens(n: int, total: int) -> str:
    if n >= 1000:
        return f"{n/1000:.0f}k/{total//1000}k"
    return f"{n}/{total//1000}k"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        print('')
        return

    workspace   = data.get('workspace', {})
    cwd         = workspace.get('current_dir') or data.get('cwd', '')
    folder      = os.path.basename(cwd) if cwd else ''
    model_id    = data.get('model', {}).get('id', '')
    model_name  = data.get('model', {}).get('display_name', model_id)
    transcript  = data.get('transcript_path', '')

    # Context usage
    input_tokens = get_input_tokens(transcript)
    ctx_size     = context_window(model_id)
    ctx_pct      = input_tokens / ctx_size if ctx_size else 0
    bar          = make_bar(ctx_pct)
    pct_str      = f"{ctx_pct * 100:.1f}%"
    tok_str      = fmt_tokens(input_tokens, ctx_size)

    # Git
    git_str = get_git_info(cwd) if cwd else ''

    # Running tools
    running_tools = get_running_tools(transcript) if transcript else []

    # ── Line 1: [model]  │  folder  git:(branch*) ──────────────────────────
    model_part  = f"{WHITE}[{model_name}]{RESET}"
    folder_part = f"{CYAN}{folder}{RESET}" if folder else ''

    parts1 = [model_part]
    if folder_part:
        folder_section = folder_part
        if git_str:
            folder_section += f"  {git_str}"
        parts1.append(folder_section)

    line1 = SEP.join(parts1)

    # ── Line 2: Context [bar] pct% ──────────────────────────────────────────
    ctx_label = f"{DIM}Context{RESET}"
    pct_color = context_color(ctx_pct)
    ctx_part  = f"{ctx_label} {bar} {pct_color}{pct_str}{RESET}"

    line2 = ctx_part

    # ── Line 3: running tools (only when tools are in flight) ───────────────
    tools_line = fmt_tools_line(running_tools)

    output = f"{line1}\n{line2}"
    if tools_line:
        output += f"\n{tools_line}"
    print(output)


if __name__ == '__main__':
    main()
