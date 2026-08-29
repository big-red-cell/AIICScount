import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from prompt import system_prompt_step2


def test_system_prompt_step2_emphasizes_blind_sender_needing_help_first():
    assert "opening paragraph must clearly and explicitly emphasize" in system_prompt_step2
    assert "blind person who needs help" in system_prompt_step2
    assert "opening paragraph emphasizing that the sender is blind and needs help" in system_prompt_step2
