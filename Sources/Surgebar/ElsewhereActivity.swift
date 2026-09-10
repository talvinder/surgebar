import Foundation

/// Execution and cleanup are independent. Queue returncode may be the submission
/// command's exit code, so it cannot establish a cleaned remote job's outcome.
struct EWActivity {
    let job: EWJSON
    var state: String { job["state"].string ?? "unknown" }
    var failed: Bool { ["failed", "submission_failed"].contains(state) }
    var title: String {
        switch state {
        case "succeeded": return "Work completed"
        case "cleaned": return "Resources removed"
        case "failed": return "Work failed"
        case "submission_failed": return "Couldn’t start"
        case "cancelled", "canceled": return "Cancelled"
        case "running": return "Running on this Mac"
        case "submitted": return "Sent to provider"
        case "waiting_for_capacity": return "Waiting for room"
        case "cleanup_failed": return "Cleanup needs attention"
        default: return "Status unavailable"
        }
    }
    var symbol: String {
        switch state {
        case "succeeded": return "checkmark.circle"
        case "cleaned": return "shippingbox"
        case "failed", "submission_failed", "cleanup_failed": return "exclamationmark.circle"
        case "cancelled", "canceled": return "stop.circle"
        case "waiting_for_capacity": return "clock"
        default: return "circle.dotted"
        }
    }
    var explanation: String {
        switch state {
        case "succeeded":
            return job["provider"].string == "local" ? "The command finished successfully on this Mac." : "The work finished successfully. Resource cleanup is a separate step."
        case "cleaned":
            return "Temporary resources were removed. This record does not include the work’s outcome."
        case "failed", "submission_failed":
            return Self.failureExplanation(job["reason"].string ?? "", state: state)
        case "cancelled", "canceled": return "The job was stopped or removed from the queue."
        case "running": return "This job is using a local capacity reservation."
        case "submitted": return "The provider accepted the request; its latest progress may not be recorded here."
        case "waiting_for_capacity": return "Elsewhere is waiting for enough capacity for this job. It will not move to the cloud automatically."
        case "cleanup_failed": return "Some temporary resources could not be removed. Cleanup needs another check."
        default: return "Elsewhere has not recorded a recognised status."
        }
    }
    var timestamp: (label: String, date: Date)? {
        for (key, label) in [("completed_at", "Finished"), ("started_at", "Started"), ("created_at", "Queued")] {
            if let seconds = job[key].number, seconds.isFinite, seconds > 0 {
                return (label, Date(timeIntervalSince1970: seconds))
            }
        }
        return nil
    }
    var timestampText: String {
        guard let timestamp else { return "Time not recorded" }
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .medium
        return timestamp.label + " " + formatter.string(from: timestamp.date)
    }
    static func failureExplanation(_ evidence: String, state: String = "failed") -> String {
        let text = evidence.lowercased()
        // Exact diagnostics, not an inference from an exit code or a workload name.
        if text.contains("modulecache") && (text.contains("operation not permitted") || text.contains("permission denied")) {
            return "The build couldn’t access its compiler cache because of macOS file permissions."
        }
        if text.contains("no space left on device") { return "The machine ran out of disk space while the command was running." }
        if text.contains("out of memory") || text.contains("cannot allocate memory") { return "The command reported that it ran out of memory." }
        if text.contains("permission denied") || text.contains("operation not permitted") { return "The command was denied access to a file or system resource." }
        if text.contains("no such file or directory") { return "A file or program required by the command could not be found." }
        if text.contains("command not found") { return "A required program was not installed or could not be found." }
        if text.contains("could not resolve host") || text.contains("temporary failure in name resolution") { return "The command could not reach a service because its network address could not be resolved." }
        if text.contains("timed out") || text.contains("timeout exceeded") { return "An operation took too long and timed out." }
        if text.contains("trust contract has expired") { return "The permission to run remotely had expired." }
        if text.contains("outside the approved roots") { return "The source folder was outside the approved export locations." }
        if text.contains("managed worker is no longer running") { return "The local worker stopped before it recorded a result." }
        if text.contains("error:") { return "The command reported an error, but the saved detail does not identify a cause Surgebar can explain reliably." }
        return state == "submission_failed" ? "Elsewhere couldn’t start this job. No specific cause was recorded." : "The command stopped with an error. No specific cause was recorded."
    }
}
