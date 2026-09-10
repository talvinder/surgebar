import Foundation
import SwiftUI

@MainActor final class ElsewhereModel: ObservableObject {
    @Published var queue: EWJSON = .null
    @Published var providers: EWJSON = .null
    @Published var doctor: EWJSON = .null
    @Published var version = "Unavailable"
    @Published var error: String?
    @Published var busy = false
    @Published var updated: Date?
    @Published var directory = FileManager.default.homeDirectoryForCurrentUser
    @Published var executable = ElsewhereClient.discover()
    @Published var advice: String?
    @Published var notice: String?
    private let discoverOnRefresh: Bool
    init(executable: URL? = ElsewhereClient.discover(), directory: URL = FileManager.default.homeDirectoryForCurrentUser, discoverOnRefresh: Bool = true) {
        self.executable = executable
        self.directory = directory
        self.discoverOnRefresh = discoverOnRefresh
    }
    var trust: EWJSON { providers["trust"] }
    var client: ElsewhereClient? { executable.map { ElsewhereClient(executable: $0, directory: directory) } }
    var configURL: URL? {
        guard let message = doctor["checks"].array.first(where: { $0["name"].string == "config" && $0["status"].string == "pass" })?["message"].string,
              message.hasPrefix("configuration found at /") else { return nil }
        return URL(fileURLWithPath: String(message.dropFirst("configuration found at ".count)))
    }
    /// Editing is available only for a directly approved file, never an inherited global boundary.
    var editableConfig: Data? {
        guard error == nil, trust["valid"].yes, let url = configURL, let data = try? Data(contentsOf: url),
              let json = try? JSONDecoder().decode(EWJSON.self, from: data), json["trust"]["approved"].yes else { return nil }
        for field in ["providers", "source", "limits", "artifact_store", "expires_at", "approved_at"] {
            guard json["trust"][field] == trust[field] else { return nil }
        }
        return data
    }
    func refresh() async {
        guard !busy else { return }
        if discoverOnRefresh { executable = ElsewhereClient.discover() }
        guard let client else { error = EWError.missing.localizedDescription; return }
        busy = true
        defer { busy = false }
        do {
            let q = try await client.json(["queue", "--json", "--history-limit", "10"])
            let p = try await client.json(["providers"])
            let d = try await client.json(["doctor", "--json"], diagnostic: true)
            let v = try await client.run(["--version"])
            guard q["capacity"] != .null, p["providers"] != .null, d["checks"] != .null else { throw EWError.malformed }
            queue = q; providers = p; doctor = d
            version = String(data: v, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "Unavailable"
            updated = Date(); error = nil
        } catch { self.error = error.localizedDescription }
    }
    func selectDirectory(_ url: URL) {
        guard !busy else { return }
        directory = url; queue = .null; providers = .null; doctor = .null; updated = nil; advice = nil; notice = nil; error = nil
    }
    func perform(_ args: [String], expectedConfig: Data? = nil) async {
        guard !busy, let client else { return }
        busy = true
        notice = nil
        do {
            if let expectedConfig {
                guard editableConfig == expectedConfig else { throw EWError.changed }
                // Approval snapshots must not silently adopt a newly configured destination.
                let freshProviders = try await client.json(["providers"])
                guard freshProviders == providers, editableConfig == expectedConfig else { throw EWError.changed }
            }
            _ = try await client.json(args)
            error = nil
            notice = "Elsewhere accepted the change."
        } catch { self.error = error.localizedDescription; busy = false; return }
        busy = false
        await refresh()
    }
    /// Only numeric, fixed-schema telemetry leaves the device for an explicit AI request.
    var aiSummary: String {
        let capacity = queue["capacity"]
        let fields: [(String, EWJSON)] = [
            ("memory headroom percent", capacity["memory"]["memory_level"]),
            ("available MB", capacity["budget"]["available_mb"]),
            ("new build slots", capacity["recommendations"]["build"]),
            ("new test slots", capacity["recommendations"]["test"]),
            ("new parallel agent slots", capacity["recommendations"]["parallel-agent"]),
            ("waiting jobs", queue["counts"]["waiting"])]
        return fields.map { name, value in "\(name): \(value.number.map(String.init(describing:)) ?? "unavailable")" }.joined(separator: "\n")
    }
}
