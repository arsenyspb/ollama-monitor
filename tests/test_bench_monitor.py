import subprocess
import pytest

def test_eval_rate_grep_anchoring():
    """Verify that grep '^eval rate:' isolates generation speed from prompt eval rate."""
    ollama_verbose_output = """
total duration:       2.512345s
load duration:        1.234ms
prompt eval count:    25 token(s)
prompt eval duration: 100.5ms
prompt eval rate:     248.76 tokens/s
eval count:           100 token(s)
eval duration:        2.0s
eval rate:            50.00 tokens/s
"""
    # The buggy grep 'eval rate:' matches both lines:
    cmd_buggy = f"echo '{ollama_verbose_output}' | grep 'eval rate:' | awk '{{print $3}}'"
    buggy_res = subprocess.check_output(cmd_buggy, shell=True, text=True).strip()
    # It produces two lines ('rate:' from prompt eval rate and '50.00' from eval rate)
    assert "\n" in buggy_res

    # The anchored grep '^eval rate:' matches only generation eval rate:
    cmd_fixed = f"echo '{ollama_verbose_output}' | grep '^eval rate:' | awk '{{print $3}}'"
    fixed_res = subprocess.check_output(cmd_fixed, shell=True, text=True).strip()
    assert fixed_res == "50.00"

    cmd_prompt = f"echo '{ollama_verbose_output}' | grep '^prompt eval rate:' | awk '{{print $4}}'"
    prompt_res = subprocess.check_output(cmd_prompt, shell=True, text=True).strip()
    assert prompt_res == "248.76"
