#!/usr/bin/env python3
"""
codebuddy-hud: A HUD-style status line for CodeBuddy Code.
Visual style aligned with claude-hud (github.com/jarrodwatts/claude-hud).

Line 1: [model]  │  folder  git:(branch*)
Line 2: Context [████░░░░░░] pct%
Line 3: ✓ Bash ×32  ✓ Read ×5  ✓ Edit ×3   (top-5 tool usage stats, by count)

Install:
  ln -sf /data/workspace/codebuddy-hud/hud.py ~/.codebuddy/hud.py

Add to ~/.codebuddy/settings.json:
  "statusLine": {
    "type": "command",
    "command": "python3.12 ~/.codebuddy/hud.py",
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

HIDDEN_TOOLS  = {'AskUserQuestion', 'EnterPlanMode', 'ExitPlanMode', 'TaskCreate', 'TaskUpdate', 'TaskGet', 'TaskList',
                 'TaskStop', 'TaskOutput', 'ToolSearch', 'DeferExecuteTool', 'Skill'}


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
# Read transcript tail — shared helper.
# ---------------------------------------------------------------------------
def _read_transcript_tail(transcript_path: str, n: int = 800) -> list:
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
# Get completed tool usage counts from transcript.
# Returns {tool_name: count}
# ---------------------------------------------------------------------------
def get_tool_counts(transcript_path: str) -> dict:
    lines = _read_transcript_tail(transcript_path, 800)

    tool_calls = {}  # callId -> name
    result_ids = set()
    counts     = {}  # name -> completed count

    for raw in lines:
        raw = raw.strip()
        if not raw or 'function_call' not in raw:
            continue
        try:
            entry = json.loads(raw)
        except Exception:
            continue

        etype = entry.get('type', '')
        if etype == 'function_call':
            cid  = entry.get('callId', '')
            name = entry.get('name', '')
            if cid and name:
                tool_calls[cid] = name
        elif etype == 'function_call_result':
            cid = entry.get('callId', '')
            if cid:
                result_ids.add(cid)

    for cid, name in tool_calls.items():
        if cid in result_ids:
            counts[name] = counts.get(name, 0) + 1

    return counts


# ---------------------------------------------------------------------------
# Render the tool stats line (Line 3): top-5 by count
# ---------------------------------------------------------------------------
MAX_TOOLS = 5


def fmt_tools_line(counts: dict) -> str:
    visible = {n: c for n, c in counts.items() if n not in HIDDEN_TOOLS}
    if not visible:
        return ''

    top = sorted(visible, key=lambda n: -visible[n])[:MAX_TOOLS]
    parts = []
    for name in top:
        n = visible[name]
        count_str = f" {DIM}×{n}{RESET}" if n > 1 else ''
        parts.append(f"{GREEN}✓{RESET} {CYAN}{name}{RESET}{count_str}")

    return '  '.join(parts)


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
        return f"{CYAN}git:({RESET}{YELLOW}{branch}{dirty}{RESET}{CYAN}){RESET}"
    except Exception:
        return ''


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

    # Context usage — prefer stdin's context_window data (accurate, no parsing needed)
    ctx_window  = data.get('context_window', {})
    ctx_pct_raw = ctx_window.get('used_percentage', 0)
    if ctx_pct_raw:
        ctx_pct = ctx_pct_raw / 100.0
    else:
        ctx_pct = 0.0

    bar     = make_bar(ctx_pct)
    pct_str = f"{ctx_pct * 100:.1f}%"

    # Git
    git_str = get_git_info(cwd) if cwd else ''

    # Tool usage counts
    tool_counts = get_tool_counts(transcript) if transcript else {}

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
    line2     = f"{ctx_label} {bar} {pct_color}{pct_str}{RESET}"

    # ── Line 3: tool usage stats ─────────────────────────────────────────────
    tools_line = fmt_tools_line(tool_counts)

    output = f"{line1}\n{line2}"
    if tools_line:
        output += f"\n{tools_line}"
    print(output)


if __name__ == '__main__':
    main()
