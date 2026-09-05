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
HISTORY_TEMPLATE_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "openondemand",
    "templates",
    "opencomposer_history_manifest.yml.j2",
)
ONDEMAND_TEMPLATE_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "openondemand",
    "templates",
    "ondemand.yml.j2",
)
WIDGET_TEMPLATE_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "openondemand",
    "templates",
    "opencomposer_dashboard_widget.html.erb.j2",
)
FRAME_WIDGET_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "openondemand",
    "files",
    "etc",
    "ood",
    "config",
    "apps",
    "dashboard",
    "views",
    "widgets",
    "_opencomposer_frame.html.erb",
)


class OpenComposerDashboardLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(TEMPLATE_PATH, encoding="utf-8") as template_file:
            cls.template = template_file.read()
        with open(HISTORY_TEMPLATE_PATH, encoding="utf-8") as template_file:
            cls.history_template = template_file.read()
        with open(ONDEMAND_TEMPLATE_PATH, encoding="utf-8") as template_file:
            cls.ondemand_template = template_file.read()
        with open(WIDGET_TEMPLATE_PATH, encoding="utf-8") as template_file:
            cls.widget_template = template_file.read()
        with open(FRAME_WIDGET_PATH, encoding="utf-8") as frame_widget_file:
            cls.frame_widget = frame_widget_file.read()

        environment = jinja2.Environment()
        environment.filters["basename"] = os.path.basename
        environment.filters["bool"] = bool
        environment.filters["to_json"] = json.dumps
        cls.manifest_template = environment.from_string(cls.template)
        cls.history_manifest_template = environment.from_string(
            cls.history_template
        )
        cls.ondemand_config_template = environment.from_string(
            cls.ondemand_template
        )
        cls.dashboard_widget_template = environment.from_string(
            cls.widget_template
        )

    def render_manifest(self, install_dir):
        rendered = self.manifest_template.render(
            ood_opencomposer_install_dir=install_dir
        )
        return yaml.safe_load(rendered)

    def test_slurm_link_is_grouped_under_opencomposer(self):
        manifest = self.render_manifest(
            "/var/www/ood/apps/sys/OpenComposer"
        )
        self.assertEqual(manifest["name"], "Slurmジョブ")
        self.assertEqual(manifest["category"], "04 OpenComposer")
        self.assertEqual(manifest["icon"], "fas://terminal")
        self.assertEqual(
            manifest["url"],
            "/pun/sys/dashboard/custom/opencomposer_slurm",
        )
        self.assertFalse(manifest["new_window"])

    def test_history_link_is_grouped_under_opencomposer(self):
        manifest = yaml.safe_load(
            self.history_manifest_template.render()
        )
        self.assertEqual(manifest["name"], "History")
        self.assertEqual(manifest["category"], "04 OpenComposer")
        self.assertEqual(manifest["icon"], "fas://history")
        self.assertEqual(
            manifest["url"],
            "/pun/sys/dashboard/custom/opencomposer_history",
        )
        self.assertFalse(manifest["new_window"])

    def test_dashboard_defines_both_opencomposer_custom_pages(self):
        config = yaml.safe_load(
            self.ondemand_config_template.render(ood_dcv_enabled=False)
        )

        self.assertIn("sys/OpenComposer", config["pinned_apps"])
        self.assertIn("sys/OpenComposerHistory", config["pinned_apps"])
        self.assertEqual(
            config["custom_pages"]["opencomposer_slurm"]["rows"][0][
                "columns"
            ][0]["widgets"],
            ["opencomposer_slurm"],
        )
        self.assertEqual(
            config["custom_pages"]["opencomposer_history"]["rows"][0][
                "columns"
            ][0]["widgets"],
            ["opencomposer_history"],
        )

    def test_widget_embeds_the_configured_opencomposer_endpoint(self):
        rendered = self.dashboard_widget_template.render(
            ood_opencomposer_install_dir=(
                "/var/www/ood/apps/sys/CustomComposer"
            ),
            opencomposer_widget_title="History",
            opencomposer_widget_endpoint="history",
        )

        self.assertIn('title: "History"', rendered)
        self.assertIn(
            'path: "/pun/sys/CustomComposer/history"', rendered
        )

    def test_frame_keeps_the_ood_header_and_hides_opencomposer_nav(self):
        self.assertIn('class="opencomposer-frame"', self.frame_widget)
        self.assertIn(
            'querySelector("#_form_container > nav")',
            self.frame_widget,
        )
        self.assertIn(
            'document.body.classList.add("opencomposer-custom-page")',
            self.frame_widget,
        )
        self.assertIn(
            'nonce="<%= content_security_policy_nonce %>"',
            self.frame_widget,
        )


if __name__ == "__main__":
    unittest.main()
