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


# ── Fixtures ─────────────────────────────────────────────────────────────────

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


# ── make_bar ─────────────────────────────────────────────────────────────────

class TestMakeBar:
    def _visible(self, bar: str) -> str:
        """Strip ANSI, return only block characters."""
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


# ── fmt_tokens ───────────────────────────────────────────────────────────────

class TestFmtTokens:
    def test_small_values(self):
        assert hud.fmt_tokens(500, 200_000) == '500/200k'

    def test_large_values(self):
        assert hud.fmt_tokens(45_000, 200_000) == '45k/200k'

    def test_1m_context(self):
        assert hud.fmt_tokens(300_000, 1_000_000) == '300k/1000k'


# ── fmt_duration ─────────────────────────────────────────────────────────────

class TestFmtDuration:
    def test_zero(self):
        assert hud.fmt_duration(0) == ''

    def test_seconds_only(self):
        assert hud.fmt_duration(45_000) == '45s'

    def test_minutes_and_seconds(self):
        assert hud.fmt_duration(65_000) == '1m05s'

    def test_hours_and_minutes(self):
        assert hud.fmt_duration(3_720_000) == '1h02m'


# ── context_window ────────────────────────────────────────────────────────────

class TestContextWindow:
    def test_1m_model(self):
        assert hud.context_window('claude-sonnet-4-6-1m') == 1_000_000

    def test_200k_model(self):
        assert hud.context_window('claude-opus-200k') == 200_000

    def test_default(self):
        assert hud.context_window('unknown-model') == 200_000


# ── _tool_target ──────────────────────────────────────────────────────────────

class TestToolTarget:
    def test_file_path(self):
        target = hud._tool_target('Read', {'file_path': '/a/b/c/src/index.ts'})
        assert target == 'src/index.ts'

    def test_single_segment_path(self):
        target = hud._tool_target('Read', {'file_path': 'README.md'})
        assert target == 'README.md'

    def test_bash_short_command(self):
        target = hud._tool_target('Bash', {'command': 'npm test'})
        assert target == 'npm test'

    def test_bash_long_command_truncated(self):
        cmd = 'x' * 40
        target = hud._tool_target('Bash', {'command': cmd})
        assert target.endswith('…')
        assert len(strip_ansi(target)) <= 36  # 35 chars + ellipsis

    def test_bash_multiline_shows_first_line(self):
        target = hud._tool_target('Bash', {'command': 'echo hello\necho world'})
        assert target == 'echo hello'

    def test_pattern_key(self):
        target = hud._tool_target('Glob', {'pattern': '**/*.ts'})
        assert target == '**/*.ts'

    def test_description_fallback(self):
        target = hud._tool_target('Agent', {'description': 'explore codebase'})
        assert target == 'explore codebase'

    def test_empty_input(self):
        target = hud._tool_target('Unknown', {})
        assert target == ''


# ── get_input_tokens ──────────────────────────────────────────────────────────

class TestGetInputTokens:
    def test_returns_zero_for_missing_file(self):
        assert hud.get_input_tokens('/nonexistent/path.jsonl') == 0

    def test_returns_zero_for_empty_path(self):
        assert hud.get_input_tokens('') == 0

    def test_reads_latest_token_count(self):
        entries = [
            {'providerData': {'usage': {'inputTokens': 1000}}},
            {'providerData': {'usage': {'inputTokens': 2500}}},
        ]
        path = make_transcript(entries)
        try:
            assert hud.get_input_tokens(path) == 2500
        finally:
            os.unlink(path)

    def test_ignores_malformed_lines(self):
        path = tempfile.mktemp(suffix='.jsonl')
        with open(path, 'w') as f:
            f.write('not json\n')
            f.write(json.dumps({'providerData': {'usage': {'inputTokens': 999}}}) + '\n')
        try:
            assert hud.get_input_tokens(path) == 999
        finally:
            os.unlink(path)


# ── get_running_tools ─────────────────────────────────────────────────────────

class TestGetRunningTools:
    def test_empty_transcript(self):
        path = make_transcript([])
        try:
            assert hud.get_running_tools(path) == []
        finally:
            os.unlink(path)

    def test_missing_file(self):
        assert hud.get_running_tools('/nonexistent.jsonl') == []

    def test_completed_tool_not_shown(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Read',
             'arguments': '{"file_path": "/a/b.py"}'},
            {'type': 'function_call_result', 'callId': 'c1', 'status': 'completed'},
        ]
        path = make_transcript(entries)
        try:
            assert hud.get_running_tools(path) == []
        finally:
            os.unlink(path)

    def test_running_tool_shown(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Read',
             'arguments': '{"file_path": "/a/b/c.py"}'},
        ]
        path = make_transcript(entries)
        try:
            result = hud.get_running_tools(path)
            assert len(result) == 1
            name, target = result[0]
            assert name == 'Read'
            assert target == 'b/c.py'
        finally:
            os.unlink(path)

    def test_two_running_tools(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Read',
             'arguments': '{"file_path": "/a/index.ts"}'},
            {'type': 'function_call', 'callId': 'c2', 'name': 'Bash',
             'arguments': '{"command": "npm test"}'},
        ]
        path = make_transcript(entries)
        try:
            result = hud.get_running_tools(path)
            assert len(result) == 2
            names = [r[0] for r in result]
            assert 'Read' in names
            assert 'Bash' in names
        finally:
            os.unlink(path)

    def test_max_two_running_tools(self):
        entries = [
            {'type': 'function_call', 'callId': f'c{i}', 'name': 'Read',
             'arguments': f'{{"file_path": "/a/file{i}.py"}}'}
            for i in range(5)
        ]
        path = make_transcript(entries)
        try:
            result = hud.get_running_tools(path)
            assert len(result) == 2
        finally:
            os.unlink(path)

    def test_mixed_completed_and_running(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Read',
             'arguments': '{"file_path": "/done.py"}'},
            {'type': 'function_call_result', 'callId': 'c1', 'status': 'completed'},
            {'type': 'function_call', 'callId': 'c2', 'name': 'Bash',
             'arguments': '{"command": "npm run build"}'},
        ]
        path = make_transcript(entries)
        try:
            result = hud.get_running_tools(path)
            assert len(result) == 1
            assert result[0][0] == 'Bash'
        finally:
            os.unlink(path)

    def test_bash_target_extracted(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Bash',
             'arguments': '{"command": "git status"}'},
        ]
        path = make_transcript(entries)
        try:
            result = hud.get_running_tools(path)
            assert result[0][1] == 'git status'
        finally:
            os.unlink(path)


# ── fmt_tools_line ────────────────────────────────────────────────────────────

class TestFmtToolsLine:
    def test_empty_list(self):
        assert hud.fmt_tools_line([]) == ''

    def test_single_tool_with_target(self):
        line = strip_ansi(hud.fmt_tools_line([('Read', 'src/index.ts')]))
        assert '◐' in line
        assert 'Read' in line
        assert 'src/index.ts' in line

    def test_single_tool_no_target(self):
        line = strip_ansi(hud.fmt_tools_line([('Bash', '')]))
        assert 'Bash' in line

    def test_two_tools_separated(self):
        line = strip_ansi(hud.fmt_tools_line([
            ('Read', 'a/b.ts'),
            ('Bash', 'npm test'),
        ]))
        assert 'Read' in line
        assert 'Bash' in line


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

    def test_line3_appears_with_running_tool(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Bash',
             'arguments': '{"command": "npm test"}'},
        ]
        out = strip_ansi(run_hud(BASE_STDIN, transcript_entries=entries))
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 3
        assert '◐' in lines[2]
        assert 'Bash' in lines[2]

    def test_line3_absent_when_all_complete(self):
        entries = [
            {'type': 'function_call', 'callId': 'c1', 'name': 'Read',
             'arguments': '{"file_path": "/a/b.py"}'},
            {'type': 'function_call_result', 'callId': 'c1', 'status': 'completed'},
        ]
        out = strip_ansi(run_hud(BASE_STDIN, transcript_entries=entries))
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 2

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

    def test_context_pct_shown(self):
        # Use a 200k model so 100k tokens = 50%
        stdin = {
            'model': {'id': 'claude-opus-200k', 'display_name': 'Claude-Opus-200k'},
            'workspace': {'current_dir': '/tmp'},
        }
        entries = [
            {'providerData': {'usage': {'inputTokens': 100_000}}},
        ]
        out = strip_ansi(run_hud(stdin, transcript_entries=entries))
        assert '50.0%' in out  # 100k / 200k = 50%
