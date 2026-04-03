# codebuddy-hud

A HUD-style status line for [CodeBuddy Code](https://cnb.cool/codebuddy/codebuddy-code), inspired by [claude-hud](https://github.com/jarrodwatts/claude-hud).

## What it shows

```
[Claude-Sonnet-4.6-1M] │ my-project  git:(main*)
Context ████░░░░░░ 41.8%
```

| Field | Source |
|-------|--------|
| Model name | `model.display_name` from stdin |
| Folder name | `workspace.current_dir` from stdin |
| Git branch + dirty (`*`) | `git branch --show-current` |
| Context bar + % | Latest `inputTokens` in transcript JSONL ÷ model context window |

Context bar color: green < 70%, yellow 70–85%, red ≥ 85%.

## Installation

**1. Clone or download this repo:**

```bash
git clone <repo-url> ~/codebuddy-hud
# or place hud.py anywhere you like
```

**2. Make the script accessible:**

```bash
# Option A: symlink to ~/.codebuddy/
ln -sf ~/codebuddy-hud/hud.py ~/.codebuddy/hud.py

# Option B: just note the full path to hud.py
```

**3. Add to `~/.codebuddy/settings.json`:**

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.codebuddy/hud.py",
    "padding": 0
  }
}
```

> Replace `python3` with `python3.11` (or whatever Python ≥ 3.6 is in your PATH).
> Replace `~/.codebuddy/hud.py` with the actual path to `hud.py` if you placed it elsewhere.

**4. Restart CodeBuddy Code.**

## Requirements

- Python 3.6+
- `git` in PATH
- `tail` in PATH

