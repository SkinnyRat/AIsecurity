"""Tests for flag detection patterns.

Unit tests for the flag detection regex patterns used in PentestAgent.
"""

import re

import pytest

# Flag patterns retained for compatibility with historical CTF scoring behavior.
FLAG_PATTERNS = [
    r"flag\{[^\}]+\}",  # flag{...}
    r"FLAG\{[^\}]+\}",  # FLAG{...}
    r"HTB\{[^\}]+\}",  # HTB{...}
    r"CTF\{[^\}]+\}",  # CTF{...}
    r"[A-Za-z0-9_]+\{[^\}]+\}",  # Generic CTF format
    r"\b[a-f0-9]{32}\b",  # 32-char hex (HTB user/root flags)
]


def detect_flags(text: str) -> list[str]:
    """Detect potential flags in text using regex patterns."""
    flags = []
    for pattern in FLAG_PATTERNS:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            flag = match.group(0)
            if flag not in flags:
                flags.append(flag)
    return flags


@pytest.mark.unit
class TestFlagDetection:
    """Tests for flag detection patterns."""

    def test_detect_flag_lowercase(self):
        """Test detecting lowercase flag{...} pattern."""
        text = "The flag is flag{s3cr3t_p4ssw0rd}"
        flags = detect_flags(text)
        assert "flag{s3cr3t_p4ssw0rd}" in flags

    def test_detect_flag_uppercase(self):
        """Test detecting uppercase FLAG{...} pattern."""
        text = "Found: FLAG{ADMIN_ACCESS}"
        flags = detect_flags(text)
        assert "FLAG{ADMIN_ACCESS}" in flags

    def test_detect_htb_flag(self):
        """Test detecting HTB{...} pattern."""
        text = "HackTheBox flag: HTB{h4ck_th3_pl4n3t}"
        flags = detect_flags(text)
        assert "HTB{h4ck_th3_pl4n3t}" in flags

    def test_detect_ctf_flag(self):
        """Test detecting CTF{...} pattern."""
        text = "Capture the flag: CTF{y0u_w1n}"
        flags = detect_flags(text)
        assert "CTF{y0u_w1n}" in flags

    def test_detect_custom_ctf_format(self):
        """Test detecting custom CTF format like picoCTF{...}."""
        text = "Here is the flag: picoCTF{custom_flag_here}"
        flags = detect_flags(text)
        assert "picoCTF{custom_flag_here}" in flags

    def test_detect_32_char_hex(self):
        """Test detecting 32-character hex flags (HTB user/root)."""
        text = "User flag: 0123456789abcdef0123456789abcdef"
        flags = detect_flags(text)
        assert "0123456789abcdef0123456789abcdef" in flags

    def test_detect_32_char_hex_mixed_case(self):
        """Test detecting 32-char hex with mixed case."""
        text = "Root flag: aBcDeF0123456789aBcDeF0123456789"
        flags = detect_flags(text)
        # The pattern should match (case insensitive)
        assert any("abcdef0123456789abcdef0123456789" in f.lower() for f in flags)

    def test_detect_multiple_flags(self):
        """Test detecting multiple flags in one text."""
        text = """
        Found these flags:
        - flag{first_flag}
        - HTB{second_flag}
        - 0123456789abcdef0123456789abcdef
        """
        flags = detect_flags(text)
        assert len(flags) >= 3
        assert "flag{first_flag}" in flags
        assert "HTB{second_flag}" in flags
        assert "0123456789abcdef0123456789abcdef" in flags

    def test_no_false_positives_short_hex(self):
        """Test that short hex strings are not detected as flags."""
        text = "Hash: abc123 and ID: 12345678"
        flags = detect_flags(text)
        # Should not detect short hex strings
        assert "abc123" not in flags
        assert "12345678" not in flags

    def test_no_false_positives_31_char_hex(self):
        """Test that 31-char hex strings are not detected as flags."""
        text = "Almost: 0123456789abcdef0123456789abcde"  # 31 chars
        flags = detect_flags(text)
        # Should not include 31-char strings
        assert not any(len(f) == 31 and f.isalnum() for f in flags)

    def test_no_false_positives_33_char_hex(self):
        """Test that 33-char hex strings are not detected as flags."""
        text = "Too long: 0123456789abcdef0123456789abcdefa"  # 33 chars
        flags = detect_flags(text)
        # The pattern should not match the full 33-char string
        # (may match first 32 chars depending on pattern)
        assert "0123456789abcdef0123456789abcdefa" not in flags

    def test_flag_with_special_content(self):
        """Test detecting flags with special characters in content."""
        text = "flag{c0mp13x_fl4g_w1th_und3rsc0r3s}"
        flags = detect_flags(text)
        assert "flag{c0mp13x_fl4g_w1th_und3rsc0r3s}" in flags

    def test_flag_in_json_context(self):
        """Test detecting flags in JSON-like output."""
        text = '{"result": "success", "flag": "flag{json_flag_123}"}'
        flags = detect_flags(text)
        assert "flag{json_flag_123}" in flags

    def test_flag_in_command_output(self):
        """Test detecting flags in command output context."""
        text = """
        cat /root/root.txt
        HTB{r00t_4cc3ss_gr4nt3d}
        """
        flags = detect_flags(text)
        assert "HTB{r00t_4cc3ss_gr4nt3d}" in flags

    def test_empty_string(self):
        """Test that empty string returns no flags."""
        flags = detect_flags("")
        assert flags == []

    def test_no_flags(self):
        """Test text with no flags returns empty list."""
        text = "This is just regular text without any flags."
        flags = detect_flags(text)
        # May detect some false positives with generic pattern, but
        # main flag formats should not match
        assert not any(f.startswith(("flag{", "FLAG{", "HTB{", "CTF{")) for f in flags)

    def test_flag_case_insensitive(self):
        """Test that flag detection is case insensitive."""
        text = "FlaG{MiXeD_CaSe}"
        flags = detect_flags(text)
        # Should detect the flag
        assert len(flags) >= 1

    def test_duplicate_flags_not_repeated(self):
        """Test that duplicate flags are not returned multiple times."""
        text = "flag{duplicate} and again flag{duplicate}"
        flags = detect_flags(text)
        # Count occurrences of the duplicate flag
        count = flags.count("flag{duplicate}")
        assert count == 1
