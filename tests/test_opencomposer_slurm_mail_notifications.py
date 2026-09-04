import os
import re
import unittest


REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "openondemand",
    "templates",
    "opencomposer_slurm_form.yml.j2",
)

NOTIFICATION_GUARD = (
    "{% if slurm_job_notifications_enabled | default(false) | bool %}"
)
NOTIFICATION_BLOCK = re.compile(
    re.escape(NOTIFICATION_GUARD) + r"(?P<body>.*?){% endif %}",
    re.DOTALL,
)


class OpenComposerSlurmMailNotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(TEMPLATE_PATH, encoding="utf-8") as template_file:
            cls.template = template_file.read()

    def render_notification_condition(self, enabled):
        """Resolve only the feature guard without needing Ansible or Jinja."""
        return NOTIFICATION_BLOCK.sub(
            lambda match: match.group("body") if enabled else "", self.template
        )

    def test_notification_form_and_script_are_both_feature_guarded(self):
        self.assertEqual(self.template.count(NOTIFICATION_GUARD), 2)

        disabled_template = self.render_notification_condition(enabled=False)
        self.assertNotIn("mail_notification_enabled:", disabled_template)
        self.assertNotIn("mail_notification_types:", disabled_template)
        self.assertNotIn("#SBATCH --mail-type=", disabled_template)

        enabled_template = self.render_notification_condition(enabled=True)
        self.assertIn("mail_notification_enabled:", enabled_template)
        self.assertIn("mail_notification_types:", enabled_template)
        self.assertEqual(enabled_template.count("#SBATCH --mail-type="), 1)

    def test_master_checkbox_defaults_off_and_enables_event_checkboxes(self):
        master_widget = re.search(
            r"^  mail_notification_enabled:\n(?P<body>.*?)(?=^  mail_notification_types:)",
            self.template,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(master_widget)
        master_body = master_widget.group("body")

        self.assertIn("widget: checkbox", master_body)
        self.assertIn("メール通知を送信する", master_body)
        self.assertIn("enable-mail_notification_types", master_body)
        self.assertNotRegex(master_body, r"(?m)^    value:")

    def test_event_checkboxes_generate_one_nonempty_mail_type_directive(self):
        event_widget = re.search(
            r"^  mail_notification_types:\n(?P<body>.*?)(?=^\{% endif %\})",
            self.template,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(event_widget)
        event_body = event_widget.group("body")

        self.assertIn("widget: checkbox", event_body)
        self.assertIn("separator: {{ ',' | to_json }}", event_body)
        # OpenComposer v2.0.2 validates a required checkbox even while all of
        # its options are dynamically disabled. Leaving this widget optional
        # keeps the default-off master checkbox from disabling Submit. An empty
        # selection is still safe: showLine() drops separator-based lines when
        # the checkbox value is empty.
        self.assertNotRegex(event_body, r"(?m)^    required:")
        for event in ("BEGIN", "END", "FAIL"):
            self.assertIn("{{ '" + event + "' | to_json }}", event_body)

        enabled_template = self.render_notification_condition(enabled=True)
        generated_script = enabled_template.replace(
            "#{mail_notification_types}", "BEGIN,END,FAIL"
        )
        directives = re.findall(
            r"(?m)^\s*#SBATCH --mail-type=[^\n]+$", generated_script
        )
        self.assertEqual(directives, ["  #SBATCH --mail-type=BEGIN,END,FAIL"])
        self.assertNotIn("--mail-user", self.template)


if __name__ == "__main__":
    unittest.main()
