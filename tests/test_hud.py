"""
Tests for hud.py

Run with:
    python3.11 -m pytest tests/ -v
"""
import json
import os
import re
import subprocess
import sys
import tempfile

import pytest

# Make hud importable from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import hud

ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub('', s)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_transcript(entries: list) -> str:
    """Write a list of dicts as JSONL to a temp file; return the path."""
    f = tempfile.NamedTemporaryFile(
        mode='w', suffix='.jsonl', delete=False, encoding='utf-8'
    )
    for entry in entries:
        f.write(json.dumps(entry) + '\n')
    f.close()
    return f.name


# ── context_color ─────────────────────────────────────────────────────────────

class TestContextColor:
    def test_low_is_green(self):
        assert hud.context_color(0.0) == hud.GREEN
        assert hud.context_color(0.69) == hud.GREEN

    def test_mid_is_yellow(self):
        assert hud.context_color(0.70) == hud.YELLOW
        assert hud.context_color(0.84) == hud.YELLOW

    def test_high_is_red(self):
        assert hud.context_color(0.85) == hud.RED
        assert hud.context_color(1.0) == hud.RED


# ── make_bar ──────────────────────────────────────────────────────────────────

class TestMakeBar:
    def _visible(self, bar: str) -> str:
        return strip_ansi(bar)

    def test_empty_bar(self):
        bar = self._visible(hud.make_bar(0.0, width=10))
        assert '░' * 10 in bar

    def test_full_bar(self):
        bar = self._visible(hud.make_bar(1.0, width=10))
        assert '█' * 10 in bar

    def test_half_bar(self):
        bar = self._visible(hud.make_bar(0.5, width=10))
        assert '█' * 5 in bar
        assert '░' * 5 in bar

    def test_clamps_below_zero(self):
        bar = self._visible(hud.make_bar(-0.5, width=10))
        assert '░' * 10 in bar

    def test_clamps_above_one(self):
        bar = self._visible(hud.make_bar(2.0, width=10))
        assert '█' * 10 in bar

    def test_color_changes_at_threshold(self):
        low_bar  = hud.make_bar(0.5)
        high_bar = hud.make_bar(0.9)
        assert hud.GREEN in low_bar
        assert hud.RED   in high_bar


# ── get_tool_counts ───────────────────────────────────────────────────────────

class TestGetToolCounts:
    def test_missing_file(self):
        assert hud.get_tool_counts('/nonexistent.jsonl') == {}

    def test_empty_transcript(self):
        path = make_transcript([])
        try:
            assert hud.get_tool_counts(path) == {}
        finally:
            os.unlink(path)

    def test_completed_tool_counted(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Read', 'arguments': '{}'},
            {'type': 'function_call_result', 'callId': 'c1', 'status': 'completed'},
        ]
        path = make_transcript(entries)
        try:
            counts = hud.get_tool_counts(path)
            assert counts == {'Read': 1}
        finally:
            os.unlink(path)

    def test_incomplete_tool_not_counted(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Bash', 'arguments': '{}'},
        ]
        path = make_transcript(entries)
        try:
            counts = hud.get_tool_counts(path)
            assert counts == {}
        finally:
            os.unlink(path)

    def test_multiple_calls_same_tool(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Read', 'arguments': '{}'},
            {'type': 'function_call_result', 'callId': 'c1', 'status': 'completed'},
            {'type': 'function_call', 'callId': 'c2', 'name': 'Read', 'arguments': '{}'},
            {'type': 'function_call_result', 'callId': 'c2', 'status': 'completed'},
        ]
        path = make_transcript(entries)
        try:
            counts = hud.get_tool_counts(path)
            assert counts == {'Read': 2}
        finally:
            os.unlink(path)

    def test_mixed_tools(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Bash', 'arguments': '{}'},
            {'type': 'function_call_result', 'callId': 'c1', 'status': 'completed'},
            {'type': 'function_call', 'callId': 'c2', 'name': 'Read', 'arguments': '{}'},
            {'type': 'function_call_result', 'callId': 'c2', 'status': 'completed'},
            {'type': 'function_call', 'callId': 'c3', 'name': 'Read', 'arguments': '{}'},
            {'type': 'function_call_result', 'callId': 'c3', 'status': 'completed'},
        ]
        path = make_transcript(entries)
        try:
            counts = hud.get_tool_counts(path)
            assert counts == {'Bash': 1, 'Read': 2}
        finally:
            os.unlink(path)


# ── fmt_tools_line ────────────────────────────────────────────────────────────

class TestFmtToolsLine:
    def test_empty_counts(self):
        assert hud.fmt_tools_line({}) == ''

    def test_hidden_tools_filtered(self):
        counts = {'Bash': 5, 'TaskCreate': 10, 'EnterPlanMode': 3}
        line = strip_ansi(hud.fmt_tools_line(counts))
        assert 'Bash' in line
        assert 'TaskCreate' not in line
        assert 'EnterPlanMode' not in line

    def test_shows_checkmark(self):
        line = strip_ansi(hud.fmt_tools_line({'Read': 3}))
        assert '✓' in line
        assert 'Read' in line

    def test_count_shown_when_gt_1(self):
        line = strip_ansi(hud.fmt_tools_line({'Bash': 5}))
        assert '×5' in line

    def test_no_count_when_eq_1(self):
        line = strip_ansi(hud.fmt_tools_line({'Read': 1}))
        assert '×' not in line

    def test_sorted_by_count_descending(self):
        counts = {'Read': 2, 'Bash': 10, 'Edit': 5}
        line = strip_ansi(hud.fmt_tools_line(counts))
        bash_pos = line.index('Bash')
        edit_pos = line.index('Edit')
        read_pos = line.index('Read')
        assert bash_pos < edit_pos < read_pos

    def test_max_five_tools(self):
        counts = {f'Tool{i}': i for i in range(1, 10)}
        line = strip_ansi(hud.fmt_tools_line(counts))
        shown = [t for t in counts if t in line]
        assert len(shown) <= 5

    def test_all_hidden_returns_empty(self):
        counts = {'TaskCreate': 5, 'EnterPlanMode': 3, 'Skill': 2}
        assert hud.fmt_tools_line(counts) == ''


# ── end-to-end: main() via subprocess ────────────────────────────────────────

HUD_PY = os.path.join(os.path.dirname(__file__), '..', 'hud.py')


def run_hud(stdin_data: dict, transcript_entries: list = None) -> str:
    """Run hud.py with given stdin JSON and optional transcript; return stdout."""
    transcript_path = ''
    tmp = None
    if transcript_entries is not None:
        tmp = make_transcript(transcript_entries)
        transcript_path = tmp

    stdin_data['transcript_path'] = transcript_path
    payload = json.dumps(stdin_data)

    try:
        result = subprocess.run(
            [sys.executable, HUD_PY],
            input=payload.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
        return result.stdout.decode('utf-8', errors='replace')
    finally:
        if tmp:
            os.unlink(tmp)


BASE_STDIN = {
    'model': {'id': 'claude-sonnet-4-6-1m', 'display_name': 'Claude-Sonnet-4.6-1M'},
    'workspace': {'current_dir': '/tmp'},
}


class TestEndToEnd:
    def test_two_lines_when_no_tools(self):
        out = strip_ansi(run_hud(BASE_STDIN, transcript_entries=[]))
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 2

    def test_line1_contains_model_name(self):
        out = strip_ansi(run_hud(BASE_STDIN))
        assert 'Claude-Sonnet-4.6-1M' in out

    def test_line2_contains_context(self):
        out = strip_ansi(run_hud(BASE_STDIN))
        assert 'Context' in out
        assert '%' in out

    def test_line3_appears_with_completed_tool(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Bash',
             'arguments': '{"command": "npm test"}'},
            {'type': 'function_call_result', 'callId': 'c1', 'status': 'completed'},
        ]
        out = strip_ansi(run_hud(BASE_STDIN, transcript_entries=entries))
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 3
        assert '✓' in lines[2]
        assert 'Bash' in lines[2]

    def test_line3_absent_when_all_hidden(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'TaskCreate',
             'arguments': '{}'},
            {'type': 'function_call_result', 'callId': 'c1', 'status': 'completed'},
        ]
        out = strip_ansi(run_hud(BASE_STDIN, transcript_entries=entries))
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 2

    def test_context_pct_from_stdin(self):
        stdin = dict(BASE_STDIN)
        stdin['context_window'] = {'used_percentage': 42.5, 'context_window_size': 1_000_000}
        out = strip_ansi(run_hud(stdin))
        assert '42.5%' in out

    def test_invalid_stdin_outputs_blank(self):
        result = subprocess.run(
            [sys.executable, HUD_PY],
            input=b'not json',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
        assert result.returncode == 0
        assert result.stdout.decode().strip() == ''
