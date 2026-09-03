import Foundation
import Darwin

/// One running program, as a person would think of it.
struct RunningProcess: Identifiable, Equatable {
    let id: Int32              // process id (never shown to the user)
    let command: String        // short unix name, e.g. "Google Chrome H"
    let executablePath: String // full path, used to find the .app it belongs to
    var cpuPercent: Double     // share of one CPU core, 0…(100 × cores)
    var memoryBytes: UInt64    // resident memory
}

/// Lists running programs and works out how hard each is working *right now*.
///
/// This is deliberately on-demand: the always-on menu-bar sampler only reads two
/// cheap system-wide numbers every second. The heavier per-process scan runs only
/// while the "What's using your Mac" list is open, so surgebar itself stays light.
enum ProcessSampler {
    // libproc constants (from <sys/proc_info.h>) — named here to keep the call sites readable.
    private static let allPIDs: UInt32 = 1        // PROC_ALL_PIDS
    private static let taskInfoFlavor: Int32 = 4  // PROC_PIDTASKINFO

    /// CPU times from `proc_taskinfo` are in mach ticks, not nanoseconds. On Apple
    /// Silicon a tick is ~41.67 ns; on Intel it's 1 ns. This factor converts ticks
    /// → nanoseconds so a full core reads as 100%.
    private static let ticksToNanos: Double = {
        var tb = mach_timebase_info_data_t()
        mach_timebase_info(&tb)
        return tb.denom == 0 ? 1 : Double(tb.numer) / Double(tb.denom)
    }()

    /// A single reading of every process's cumulative CPU time + memory + name.
    private struct Reading {
        var cpuTicks: UInt64
        var memoryBytes: UInt64
        var command: String
        var path: String
    }

    /// Take two readings a short moment apart and turn the CPU-time *difference*
    /// into a live percentage. Runs off the main thread; safe to await.
    static func sample(intervalMillis: UInt64 = 600, limit: Int = 8) async -> [RunningProcess] {
        let first = readAll()
        try? await Task.sleep(nanoseconds: intervalMillis * 1_000_000)
        let second = readAll()

        let elapsedNanos = Double(intervalMillis) * 1_000_000.0
        var result: [RunningProcess] = []
        result.reserveCapacity(second.count)

        for (pid, now) in second {
            guard let before = first[pid] else { continue } // process started mid-window
            let deltaTicks = now.cpuTicks >= before.cpuTicks
                ? Double(now.cpuTicks - before.cpuTicks) : 0
            let deltaNanos = deltaTicks * ticksToNanos
            let percent = elapsedNanos > 0 ? (deltaNanos / elapsedNanos) * 100.0 : 0
            result.append(RunningProcess(
                id: pid,
                command: now.command,
                executablePath: now.path,
                cpuPercent: percent,
                memoryBytes: now.memoryBytes
            ))
        }

        result.sort { $0.cpuPercent > $1.cpuPercent }
        return Array(result.prefix(limit))
    }

    // MARK: - One raw reading of all processes

    private static func readAll() -> [Int32: Reading] {
        // How many pids are there? Ask for the buffer size first.
        let neededBytes = proc_listpids(allPIDs, 0, nil, 0)
        guard neededBytes > 0 else { return [:] }
        let count = Int(neededBytes) / MemoryLayout<pid_t>.size
        var pids = [pid_t](repeating: 0, count: count)
        let written = pids.withUnsafeMutableBytes { buf in
            proc_listpids(allPIDs, 0, buf.baseAddress, Int32(buf.count))
        }
        guard written > 0 else { return [:] }
        let actual = Int(written) / MemoryLayout<pid_t>.size

        var out: [Int32: Reading] = [:]
        out.reserveCapacity(actual)
        for i in 0..<actual {
            let pid = pids[i]
            if pid <= 0 { continue }
            guard let reading = read(pid: pid) else { continue }
            out[pid] = reading
        }
        return out
    }

    private static func read(pid: Int32) -> Reading? {
        var info = proc_taskinfo()
        let size = Int32(MemoryLayout<proc_taskinfo>.size)
        let returned = withUnsafeMutablePointer(to: &info) { ptr in
            proc_pidinfo(pid, taskInfoFlavor, 0, ptr, size)
        }
        guard returned == size else { return nil } // access denied / gone
        let cpuTicks = info.pti_total_user &+ info.pti_total_system
        return Reading(
            cpuTicks: cpuTicks,
            memoryBytes: info.pti_resident_size,
            command: commandName(pid: pid),
            path: executablePath(pid: pid)
        )
    }

    private static func commandName(pid: Int32) -> String {
        var buf = [CChar](repeating: 0, count: 2 * Int(MAXPATHLEN))
        let n = proc_name(pid, &buf, UInt32(buf.count))
        return n > 0 ? String(cString: buf) : ""
    }

    private static func executablePath(pid: Int32) -> String {
        var buf = [CChar](repeating: 0, count: Int(MAXPATHLEN) * 4)
        let n = proc_pidpath(pid, &buf, UInt32(buf.count))
        return n > 0 ? String(cString: buf) : ""
    }
}
