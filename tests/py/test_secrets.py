import os
import unittest
from unittest import mock

from atomic_agent.secrets import SecretError, resolve_env
from helpers import stub, tmpdir


class SecretsTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.bin = self.root / "bin"
        self.log = self.root / "argv.log"
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "ARGV_LOG": str(self.log),
               "HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root / "cfg")}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_plain_env_passthrough(self):
        self.assertEqual(resolve_env({"A": "1", "B": ""}), {"A": "1", "B": ""})

    def test_keyring_lookup(self):
        stub(self.bin, "secret-tool", "printf tok")
        out = resolve_env({"TOKEN": {"keyring": {"service": "mikrotik", "account": "api"}}})
        self.assertEqual(out, {"TOKEN": "tok"})
        self.assertEqual(self.log.read_text().splitlines(), ["secret-tool lookup service mikrotik account api"])

    def test_credential_lookup(self):
        stub(self.bin, "systemd-creds", "printf cred")
        out = resolve_env({"K": {"credential": "nas"}})
        self.assertEqual(out, {"K": "cred"})
        expected = f"systemd-creds --user decrypt {self.root}/cfg/atomic-hyprland/credentials/nas.cred -"
        self.assertEqual(self.log.read_text().splitlines(), [expected])

    def test_missing_secret_raises(self):
        stub(self.bin, "secret-tool", "exit 1")
        with self.assertRaises(SecretError) as cm:
            resolve_env({"TOKEN": {"keyring": {"service": "s", "account": "a"}}})
        self.assertIn("TOKEN", str(cm.exception))

    def test_empty_secret_raises(self):
        stub(self.bin, "secret-tool", "true")
        with self.assertRaises(SecretError):
            resolve_env({"TOKEN": {"keyring": {"service": "s", "account": "a"}}})

    def test_unknown_reference_raises(self):
        with self.assertRaises(SecretError):
            resolve_env({"X": {"vault": "nope"}})


if __name__ == "__main__":
    unittest.main()
