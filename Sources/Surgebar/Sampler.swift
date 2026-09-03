import Foundation
import Darwin

/// Kernel memory-pressure level — the real signal from the OS, not a guess.
enum MemoryPressure: String, Equatable {
    case normal, warning, critical

    var label: String { rawValue.capitalized }
}

/// An immutable readout the UI paints. Sampling never happens on the UI path.
struct SystemSnapshot: Equatable {
    var cpuPercent: Double = 0          // 0…100, aggregate across cores
    var memoryUsedPercent: Double = 0   // 0…100 (active + wired + compressed)
    var pressure: MemoryPressure = .normal
}

/// Samples CPU on a 1s cadence via mach host stats, and receives memory-pressure
/// transitions event-driven from the kernel (`DispatchSource`), so there's no
/// polling for memory at all. Native mach APIs — no third-party runtime.
@MainActor
final class Sampler: ObservableObject {
    @Published private(set) var snapshot = SystemSnapshot()
    @Published private(set) var cpuHistory: [Double] = []

    private var timer: Timer?
    private var pressureSource: DispatchSourceMemoryPressure?
    private var prevTicks: (user: UInt32, system: UInt32, idle: UInt32, nice: UInt32)?
    private let historyLength = 48

    init() {
        installMemoryPressureSource()
        _ = readCPU()  // prime the tick delta
        snapshot.memoryUsedPercent = readMemoryUsedPercent()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
    }

    private func tick() {
        let cpu = readCPU()
        snapshot.cpuPercent = cpu
        snapshot.memoryUsedPercent = readMemoryUsedPercent()
        cpuHistory.append(cpu)
        if cpuHistory.count > historyLength { cpuHistory.removeFirst() }
    }

    // MARK: - Memory pressure (event-driven, from the kernel)

    private func installMemoryPressureSource() {
        let source = DispatchSource.makeMemoryPressureSource(
            eventMask: [.normal, .warning, .critical],
            queue: .main
        )
        source.setEventHandler { [weak self] in
            guard let self, let event = self.pressureSource?.data else { return }
            let level: MemoryPressure
            if event.contains(.critical) { level = .critical }
            else if event.contains(.warning) { level = .warning }
            else { level = .normal }
            self.snapshot.pressure = level
        }
        source.resume()
        pressureSource = source
    }

    // MARK: - CPU (aggregate, from HOST_CPU_LOAD_INFO tick deltas)

    private func readCPU() -> Double {
        var info = host_cpu_load_info()
        var count = mach_msg_type_number_t(
            MemoryLayout<host_cpu_load_info_data_t>.stride / MemoryLayout<integer_t>.stride
        )
        let kr = withUnsafeMutablePointer(to: &info) { ptr in
            ptr.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics(mach_host_self(), HOST_CPU_LOAD_INFO, $0, &count)
            }
        }
        guard kr == KERN_SUCCESS else { return snapshot.cpuPercent }

        let user = info.cpu_ticks.0
        let system = info.cpu_ticks.1
        let idle = info.cpu_ticks.2
        let nice = info.cpu_ticks.3
        defer { prevTicks = (user, system, idle, nice) }
        guard let prev = prevTicks else { return 0 }

        let dUser = Double(user &- prev.user)
        let dSystem = Double(system &- prev.system)
        let dNice = Double(nice &- prev.nice)
        let dIdle = Double(idle &- prev.idle)
        let busy = dUser + dSystem + dNice
        let total = busy + dIdle
        return total > 0 ? min(100, max(0, busy / total * 100)) : snapshot.cpuPercent
    }

    // MARK: - Memory used (from HOST_VM_INFO64)

    private func readMemoryUsedPercent() -> Double {
        var stats = vm_statistics64()
        var count = mach_msg_type_number_t(
            MemoryLayout<vm_statistics64_data_t>.stride / MemoryLayout<integer_t>.stride
        )
        let kr = withUnsafeMutablePointer(to: &stats) { ptr in
            ptr.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics64(mach_host_self(), HOST_VM_INFO64, $0, &count)
            }
        }
        guard kr == KERN_SUCCESS else { return snapshot.memoryUsedPercent }

        let pageSize = Double(vm_kernel_page_size)
        let total = Double(ProcessInfo.processInfo.physicalMemory)
        let used = (Double(stats.active_count)
                    + Double(stats.wire_count)
                    + Double(stats.compressor_page_count)) * pageSize
        return total > 0 ? min(100, used / total * 100) : 0
    }
}
