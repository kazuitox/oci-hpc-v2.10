import os
import re
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


class OpenOnDemandUserMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DEFAULTS_PATH, encoding="utf-8") as defaults_file:
            cls.defaults = defaults_file.read()
        with open(PORTAL_TEMPLATE_PATH, encoding="utf-8") as template_file:
            cls.portal_template = template_file.read()

    def test_remote_user_uses_dex_preferred_username(self):
        self.assertRegex(
            self.defaults,
            re.compile(r"^ood_oidc_remote_user_claim: preferred_username$", re.MULTILINE),
        )
        self.assertIn(
            "preferredUsernameAttr: '{{ ood_ldap_preferred_username_attr }}'",
            self.portal_template,
        )

    def test_user_mapping_accepts_bare_ldap_username(self):
        self.assertRegex(
            self.defaults,
            re.compile(r'^ood_user_map_match: "\.\*"$', re.MULTILINE),
        )


if __name__ == "__main__":
    unittest.main()
