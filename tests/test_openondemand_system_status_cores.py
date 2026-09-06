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
        self.assertIn('"CPU Cores"', self.initializer)
        self.assertIn("physical_core_counts?", self.initializer)

    @unittest.skipUnless(shutil.which("ruby"), "Ruby is required")
    def test_mixed_ht_and_non_ht_nodes_are_counted_as_physical_cores(self):
        ruby_program = textwrap.dedent(
            f"""
            module OodCore
              module Job
                module Adapters
                  class Slurm
                    class Batch
                    end
                  end
                end
              end
            end
            $LOADED_FEATURES << "ood_core/job/adapters/slurm.rb"

            module SystemStatusHelper
              def status_hash(name, active, total)
                {{ message: "#{{name}} Available: #{{total - active}}" }}
              end

              def not_slurm_hash(_job_adapter)
                {{ message: "unsupported" }}
              end
            end
            class ExistingView
              include SystemStatusHelper
            end

            module Rails
              class Configuration
                def after_initialize
                  yield
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

            malformed = input + "unknown-node|*|*|*|invalid\n"
            abort "partial result" unless OciHpcSystemStatusPhysicalCores.counts(malformed).nil?

            cluster_class = Struct.new(
              :active_nodes,
              :total_nodes,
              :active_processors,
              :total_processors,
              :active_gpus,
              :total_gpus
            )
            core_info = cluster_class.new(0, 2, 20, 80, 0, 0)
            core_info.define_singleton_method(:physical_core_counts?) {{ true }}
            adapter_class = Struct.new(:cluster_info)
            core_status = ExistingView.new.components_status(
              adapter_class.new(core_info)
            )[1]
            abort core_status.inspect unless core_status[:message] == "CPU Cores Available: 60"

            fallback_info = cluster_class.new(0, 2, 24, 96, 0, 0)
            fallback_status = ExistingView.new.components_status(
              adapter_class.new(fallback_info)
            )[1]
            abort fallback_status.inspect unless fallback_status[:message] == "Processors Available: 72"
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
