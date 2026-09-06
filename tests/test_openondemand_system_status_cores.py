import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest


REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INITIALIZER_PATH = os.path.join(
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
    "initializers",
    "system_status_physical_cores.rb",
)
TASKS_PATH = os.path.join(
    REPOSITORY_ROOT,
    "playbooks",
    "roles",
    "openondemand",
    "tasks",
    "ood_dashboard_customizations.yml",
)


class OpenOnDemandSystemStatusCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INITIALIZER_PATH, encoding="utf-8") as initializer_file:
            cls.initializer = initializer_file.read()
        with open(TASKS_PATH, encoding="utf-8") as tasks_file:
            cls.tasks = tasks_file.read()

    def test_initializer_is_deployed_and_restarts_dashboard(self):
        destination = (
            "/etc/ood/config/apps/dashboard/initializers/"
            "system_status_physical_cores.rb"
        )
        self.assertIn(destination, self.tasks)
        self.assertIn("ood_system_status_physical_cores.changed", self.tasks)

    def test_initializer_uses_per_node_slurm_topology(self):
        self.assertIn('SINFO_FORMAT = "%N|%X|%Y|%Z|%C"', self.initializer)
        self.assertIn("nodes.key?(node_name)", self.initializer)
        self.assertIn("sockets * cores_per_socket", self.initializer)
        self.assertNotIn("total_processors / 2", self.initializer)

    def test_initializer_labels_the_value_as_cpu_cores(self):
        self.assertIn('name = "CPU Cores" if name == "Processors"', self.initializer)

    @unittest.skipUnless(shutil.which("ruby"), "Ruby is required")
    def test_mixed_ht_and_non_ht_nodes_are_counted_as_physical_cores(self):
        ruby_program = textwrap.dedent(
            f"""
            module Rails
              class Configuration
                def after_initialize
                end
              end

              class Application
                def config
                  @config ||= Configuration.new
                end
              end

              def self.application
                @application ||= Application.new
              end
            end

            require {INITIALIZER_PATH!r}

            input = <<~SINFO
              bm-1|2|32|1|16/48/0/64
              vm-1|1|16|2|8/24/0/32
              vm-1|1|16|2|8/24/0/32
            SINFO
            counts = OciHpcSystemStatusPhysicalCores.counts(input)
            abort counts.inspect unless counts == {{ active: 20, total: 80 }}
            """
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".rb", encoding="utf-8"
        ) as test_file:
            test_file.write(ruby_program)
            test_file.flush()
            result = subprocess.run(
                ["ruby", test_file.name],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
