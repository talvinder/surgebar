import Foundation
import Darwin

/// Carries out the three actions on a running program. Every path refuses to
/// touch anything that's part of macOS, and reports back in plain words.
enum ProcessControl {
    enum Outcome: Equatable {
        case done
        case alreadyClosed
        case notAllowed(String)
    }

    static func apply(_ action: ProcessAction, to proc: PlainProcess) -> Outcome {
        guard !proc.isSystem else {
            return .notAllowed("This is part of macOS, so surgebar won't stop it.")
        }
        let pid = proc.raw.id
        let rc: Int32
        switch action {
        case .slowDown:  rc = setpriority(PRIO_PROCESS, id_t(pid), 19) // lower priority ("nice")
        case .quit:      rc = kill(pid, SIGTERM)                        // ask it to close
        case .forceQuit: rc = kill(pid, SIGKILL)                        // stop it now
        }
        if rc == 0 { return .done }

        switch errno {
        case ESRCH: return .alreadyClosed
        case EPERM: return .notAllowed("macOS wouldn't let me change this one — it belongs to the system or another account.")
        default:    return .notAllowed("That didn't work — the program may have just closed.")
        }
    }
}
