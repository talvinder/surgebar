import Foundation

/// Unknown fields survive evolving CLI schemas; missing values are never presented as zero.
indirect enum EWJSON: Decodable, Equatable, Sendable {
    case object([String: EWJSON]), array([EWJSON]), string(String), number(Double), bool(Bool), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([String: EWJSON].self) { self = .object(v) }
        else { self = .array(try c.decode([EWJSON].self)) }
    }
    subscript(_ key: String) -> EWJSON { object[key] ?? .null }
    var object: [String: EWJSON] { if case .object(let v) = self { return v }; return [:] }
    var array: [EWJSON] { if case .array(let v) = self { return v }; return [] }
    var text: String { switch self { case .string(let v): return v; case .number(let v): return v.formatted(); case .bool(let v): return v ? "Yes" : "No"; default: return "Unavailable" } }
    var string: String? { if case .string(let v) = self { return v }; return nil }
    var number: Double? { if case .number(let v) = self { return v }; return nil }
    var yes: Bool { self == .bool(true) }
    var strings: [String] { array.compactMap(\.string) }
}

enum EWError: LocalizedError {
    case missing, failed(String), timeout, malformed, changed
    var errorDescription: String? {
        switch self {
        case .missing: return "Elsewhere is not installed in a supported location. Surgebar still works normally."
        case .failed(let command): return "Elsewhere could not complete \(command). Check its configuration and credentials in Terminal."
        case .timeout: return "Elsewhere took too long to respond. The last snapshot may be out of date."
        case .malformed: return "This Elsewhere version returned an unsupported response."
        case .changed: return "Configuration changed after review. Refresh and review the change again."
        }
    }
}

struct ElsewhereClient: Sendable {
    let executable: URL
    let directory: URL
    static func discover() -> URL? {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return [home.appendingPathComponent(".local/bin/elsewhere"), URL(fileURLWithPath: "/opt/homebrew/bin/elsewhere"), URL(fileURLWithPath: "/usr/local/bin/elsewhere")].first { FileManager.default.isExecutableFile(atPath: $0.path) }
    }
    func json(_ arguments: [String], diagnostic: Bool = false) async throws -> EWJSON {
        let data = try await run(arguments, acceptedExitCodes: diagnostic ? [0, 1] : [0])
        guard let json = try? JSONDecoder().decode(EWJSON.self, from: data), case .object = json else { throw EWError.malformed }
        return json
    }
    func run(_ arguments: [String], timeout: TimeInterval = 20, acceptedExitCodes: Set<Int32> = [0]) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                do { continuation.resume(returning: try self.execute(arguments, timeout: timeout, acceptedExitCodes: acceptedExitCodes)) }
                catch { continuation.resume(throwing: error) }
            }
        }
    }
    private func execute(_ arguments: [String], timeout: TimeInterval, acceptedExitCodes: Set<Int32>) throws -> Data {
        let fm = FileManager.default
        let folder = fm.temporaryDirectory.appendingPathComponent("surgebar-ew-" + UUID().uuidString)
        try fm.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        defer { try? fm.removeItem(at: folder) }
        let output = folder.appendingPathComponent("out")
        fm.createFile(atPath: output.path, contents: nil, attributes: [.posixPermissions: 0o600])
        let handle = try FileHandle(forWritingTo: output)
        defer { try? handle.close() }
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.currentDirectoryURL = directory
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin").path + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        process.environment = env
        process.standardOutput = handle
        process.standardError = FileHandle.nullDevice
        process.standardInput = FileHandle.nullDevice
        try process.run()
        let deadline = Date().addingTimeInterval(timeout)
        var stopped = false
        while process.isRunning {
            let size = (try? fm.attributesOfItem(atPath: output.path)[.size] as? NSNumber)?.intValue ?? 0
            if Date() >= deadline || size > 2_000_000 {
                stopped = true
                process.terminate()
                Thread.sleep(forTimeInterval: 0.1)
                if process.isRunning { kill(process.processIdentifier, SIGKILL) }
                break
            }
            Thread.sleep(forTimeInterval: 0.05)
        }
        process.waitUntilExit()
        if stopped { throw EWError.timeout }
        guard acceptedExitCodes.contains(process.terminationStatus) else { throw EWError.failed(arguments.first ?? "request") }
        let data = try Data(contentsOf: output)
        guard data.count <= 2_000_000 else { throw EWError.malformed }
        return data
    }
}

struct EWPermissionDraft: Equatable {
    var cpu = 4
    var memory = 8192
    var seconds = 3600
    var cost = 5.0
    var days = 30
    var allowPrivate: Bool?
    var allowUncommitted: Bool?
    func arguments(path: String, trust: EWJSON) throws -> [String] {
        let providers = trust["providers"].object.keys.sorted()
        let roots = trust["source"]["allowed_roots"].strings
        guard trust["valid"].yes, !providers.isEmpty, !roots.isEmpty,
              providers.allSatisfy({ ["fly", "azure"].contains($0) }),
              cpu >= 1, memory >= 256, seconds >= 60, cost.isFinite, cost > 0, days >= 1 else { throw EWError.malformed }
        var args = ["trust-approve", "--path", path, "--max-cpu", String(cpu), "--max-memory-mb", String(memory), "--max-runtime-seconds", String(seconds), "--max-estimated-cost-usd", String(cost), "--expires-days", String(days)]
        for provider in providers { args += ["--provider", provider] }
        for root in roots { args += ["--source-root", root] }
        args += [(allowPrivate ?? trust["source"]["allow_private"].yes) ? "--allow-private" : "--no-allow-private", (allowUncommitted ?? trust["source"]["allow_uncommitted"].yes) ? "--allow-uncommitted" : "--no-allow-uncommitted"]
        return args
    }
}
