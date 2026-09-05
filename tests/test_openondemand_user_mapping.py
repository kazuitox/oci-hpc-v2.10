import os
import re
import stat
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "openondemand",
    "defaults",
    "main.yml",
)
PORTAL_TEMPLATE_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "openondemand",
    "templates",
    "ood_portal.yml.j2",
)
MAPPER_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "openondemand",
    "files",
    "ood-user-map",
)


class OpenOnDemandUserMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DEFAULTS_PATH, encoding="utf-8") as defaults_file:
            cls.defaults = defaults_file.read()
        with open(PORTAL_TEMPLATE_PATH, encoding="utf-8") as template_file:
            cls.portal_template = template_file.read()

    def test_remote_user_keeps_email_claim_for_static_login(self):
        self.assertRegex(
            self.defaults,
            re.compile(r"^ood_oidc_remote_user_claim: email$", re.MULTILINE),
        )

    def test_portal_uses_custom_user_mapper(self):
        self.assertRegex(
            self.defaults,
            re.compile(r"^ood_user_map_cmd: /usr/local/sbin/ood-user-map$", re.MULTILINE),
        )
        self.assertIn("user_map_cmd: '{{ ood_user_map_cmd }}'", self.portal_template)

    def run_mapper(self, remote_user):
        with tempfile.TemporaryDirectory() as temp_dir:
            getent_path = os.path.join(temp_dir, "getent")
            with open(getent_path, "w", encoding="utf-8") as getent_file:
                getent_file.write(
                    "#!/bin/sh\n"
                    "[ \"$1\" = passwd ] && [ \"$2\" = kazuito ]\n"
                )
            os.chmod(getent_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            env = os.environ.copy()
            env["PATH"] = temp_dir + os.pathsep + env["PATH"]
            return subprocess.run(
                [MAPPER_PATH, remote_user],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

    def test_mapper_accepts_bare_ldap_username(self):
        result = self.run_mapper("kazuito")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "kazuito\n")

    def test_mapper_maps_static_login_email_to_system_user(self):
        result = self.run_mapper("kazuito%40example.local")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "kazuito\n")

    def test_mapper_rejects_unknown_or_unsafe_users(self):
        for remote_user in ("unknown", "%2Doption%40example.local"):
            with self.subTest(remote_user=remote_user):
                self.assertNotEqual(self.run_mapper(remote_user).returncode, 0)


if __name__ == "__main__":
    unittest.main()
