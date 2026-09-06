# frozen_string_literal: true

# Open OnDemand reports Slurm's CPU count as "Processors". Slurm's CPU count
# includes hardware threads when ThreadsPerCore is greater than one, so it is
# misleading for an HPC cluster containing both SMT-enabled and SMT-disabled
# nodes. Normalize the count per node using the topology reported by sinfo.
module OciHpcSystemStatusPhysicalCores
  SINFO_FORMAT = "%N|%X|%Y|%Z|%C".freeze

  class << self
    def counts(sinfo_output)
      nodes = {}

      sinfo_output.each_line do |line|
        line = line.strip
        next if line.empty? || line.start_with?("CLUSTER:")

        fields = line.split("|", 5)
        return unless fields.length == 5

        node_name = fields[0].strip
        return if node_name.empty?
        next if nodes.key?(node_name)

        sockets = positive_integer(fields[1])
        cores_per_socket = positive_integer(fields[2])
        threads_per_core = positive_integer(fields[3])
        cpu_state = fields[4].split("/", 4)
        return unless cpu_state.length == 4

        allocated_threads = non_negative_integer(cpu_state[0])
        total_threads = non_negative_integer(cpu_state[3])
        return if allocated_threads.nil? || total_threads.nil?

        total_cores = if sockets && cores_per_socket
                        sockets * cores_per_socket
                      end
        if threads_per_core.nil? && total_cores && total_threads.positive?
          threads_per_core = divide_rounding_up(total_threads, total_cores)
        end
        return unless threads_per_core

        total_cores ||= divide_rounding_up(total_threads, threads_per_core)
        return unless total_cores.positive?

        # This deployment uses SelectTypeParameters=CR_Core, so Slurm allocates
        # every hardware thread belonging to a selected physical core.
        active_cores = divide_rounding_up(
          allocated_threads,
          threads_per_core
        )

        nodes[node_name] = {
          active: [active_cores, total_cores].min,
          total: total_cores
        }
      end

      return if nodes.empty?

      {
        active: nodes.values.sum { |node| node[:active] },
        total: nodes.values.sum { |node| node[:total] }
      }
    end

    private

    def positive_integer(value)
      parsed = Integer(value, 10)
      parsed.positive? ? parsed : nil
    rescue ArgumentError, TypeError
      nil
    end

    def non_negative_integer(value)
      parsed = Integer(value, 10)
      parsed >= 0 ? parsed : nil
    rescue ArgumentError, TypeError
      nil
    end

    def divide_rounding_up(dividend, divisor)
      (dividend + divisor - 1) / divisor
    end
  end

  module SlurmBatchPatch
    def get_cluster_info
      original = super
      sinfo_output = call(
        "sinfo",
        "-ahN",
        "-o",
        OciHpcSystemStatusPhysicalCores::SINFO_FORMAT
      )
      core_counts = OciHpcSystemStatusPhysicalCores.counts(sinfo_output)
      return original unless core_counts

      physical_core_info = original.class.new(
        original.to_h.merge(
          active_processors: core_counts[:active],
          total_processors: core_counts[:total]
        )
      )
      physical_core_info.define_singleton_method(:physical_core_counts?) do
        true
      end
      physical_core_info
    rescue StandardError => error
      if defined?(Rails) && Rails.respond_to?(:logger) && Rails.logger
        Rails.logger.warn(
          "Could not calculate physical cores for System Status; " \
          "using Slurm CPU counts: #{error.message}"
        )
      end
      return original if original

      raise
    end
  end
end

Rails.application.config.after_initialize do
  require "ood_core/job/adapters/slurm"
  unless defined?(SystemStatusHelper)
    require Rails.root.join("app/helpers/system_status_helper").to_s
  end

  batch_class = OodCore::Job::Adapters::Slurm::Batch
  batch_patch = OciHpcSystemStatusPhysicalCores::SlurmBatchPatch
  unless batch_class.ancestors.include?(batch_patch)
    batch_class.prepend(batch_patch)
  end

  # Redefine this method in place so view classes that included the helper
  # before after_initialize also receive the new label. Keep the original label
  # when the topology query failed and get_cluster_info returned Slurm CPU data.
  SystemStatusHelper.module_eval do
    define_method(:components_status) do |job_adapter|
      begin
        cluster_info = job_adapter.cluster_info
      rescue NotImplementedError
        return [not_slurm_hash(job_adapter)]
      end

      processor_name = if cluster_info.respond_to?(:physical_core_counts?) &&
                          cluster_info.physical_core_counts?
                         "CPU Cores"
                       else
                         "Processors"
                       end

      [
        status_hash(
          "Nodes",
          cluster_info.active_nodes,
          cluster_info.total_nodes
        ),
        status_hash(
          processor_name,
          cluster_info.active_processors,
          cluster_info.total_processors
        ),
        status_hash(
          "GPUs",
          cluster_info.active_gpus,
          cluster_info.total_gpus
        )
      ]
    end
  end
end
