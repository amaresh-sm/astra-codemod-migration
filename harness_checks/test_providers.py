import unittest

from astra_harness.providers import build_provider_command


class ProviderCommandTests(unittest.TestCase):
    """Keep each advertised generation provider constructible without Docker."""

    def test_claude_code_reads_the_prompt_from_standard_input(self) -> None:
        command = build_provider_command("claude-code", "claude-opus-4-8", "max")

        self.assertIn("claude -p", command.command)
        self.assertIn("--model claude-opus-4-8", command.command)
        self.assertIn("--effort max", command.command)
        self.assertIn("--output-format stream-json", command.command)
        self.assertNotIn("{prompt}", command.command)

    def test_all_advertised_providers_construct_a_command(self) -> None:
        for provider in ("codex", "openai-compatible", "claude-code"):
            with self.subTest(provider=provider):
                command = build_provider_command(provider, "example-model", "high")
                self.assertTrue(command.command)

    def test_codex_paths_request_structured_events(self) -> None:
        for provider in ("codex", "openai-compatible"):
            with self.subTest(provider=provider):
                command = build_provider_command(provider, "example-model", "high")
                self.assertIn("--json", command.command)


if __name__ == "__main__":
    unittest.main()
