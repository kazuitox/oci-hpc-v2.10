import json
import os
import unittest

import jinja2
import yaml


REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "openondemand",
    "templates",
    "opencomposer_dashboard_manifest.yml.j2",
)


class OpenComposerDashboardLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(TEMPLATE_PATH, encoding="utf-8") as template_file:
            cls.template = template_file.read()

        environment = jinja2.Environment()
        environment.filters["basename"] = os.path.basename
        environment.filters["to_json"] = json.dumps
        cls.manifest_template = environment.from_string(cls.template)

    def render_manifest(self, install_dir):
        rendered = self.manifest_template.render(
            ood_opencomposer_install_dir=install_dir
        )
        return yaml.safe_load(rendered)

    def test_dashboard_link_opens_the_slurm_job_form_directly(self):
        manifest = self.render_manifest(
            "/var/www/ood/apps/sys/OpenComposer"
        )
        self.assertEqual(manifest["url"], "/pun/sys/OpenComposer/slurm")

    def test_dashboard_link_follows_the_configured_install_directory_name(self):
        manifest = self.render_manifest(
            "/var/www/ood/apps/sys/CustomComposer"
        )
        self.assertEqual(manifest["url"], "/pun/sys/CustomComposer/slurm")


if __name__ == "__main__":
    unittest.main()
