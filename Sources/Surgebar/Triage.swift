import Foundation

/// Everything the AI advice needs to reach a provider. Value type, so it can be
/// handed to background work safely. The key comes from the Keychain, never hard-coded.
struct TriageConfig: Sendable {
    enum Provider: String, Sendable { case openAI, anthropic }
    var provider: Provider
    var baseURL: String
    var model: String
    var apiKey: String

    var isReady: Bool { !apiKey.isEmpty && !model.isEmpty && !baseURL.isEmpty }
}

/// One piece of plain-English advice from the AI. `kind` maps to a safe action;
/// `info` means "just so you know" with nothing to do.
struct TriageRecommendation: Identifiable, Equatable {
    let id = UUID()
    enum Kind: String { case slowDown, quit, forceQuit, info }
    let kind: Kind
    let pid: Int32?
    let label: String
    let reason: String
    let needsConfirm: Bool

    var action: ProcessAction? {
        switch kind {
        case .slowDown:  return .slowDown
        case .quit:      return .quit
        case .forceQuit: return .forceQuit
        case .info:      return nil
        }
    }
}

enum TriageError: LocalizedError {
    case notReady
    case http(Int, String)
    case unreachable(String)
    case badResponse

    var errorDescription: String? {
        switch self {
        case .notReady:            return "Add your AI key in Settings first."
        case .http(let c, let m):  return "The AI service returned an error (\(c)). \(m)"
        case .unreachable(let m):  return "Couldn't reach the AI service. \(m)"
        case .badResponse:         return "The AI sent something I couldn't read. Try again."
        }
    }
}

enum TriageEngine {
    private static let timeout: TimeInterval = 25

    /// Ask the configured AI what the person should do about the current load.
    static func advise(system: SystemSnapshot, processes: [PlainProcess], config: TriageConfig) async throws -> [TriageRecommendation] {
        guard config.isReady else { throw TriageError.notReady }
        let prompt = buildPrompt(system: system, processes: processes)
        let text = try await complete(prompt: prompt, config: config)
        return parse(text, allowedPIDs: Set(processes.filter { !$0.isSystem }.map { $0.id }))
    }

    static func explainElsewhere(summary: String, config: TriageConfig) async throws -> String {
        guard config.isReady else { throw TriageError.notReady }
        return try await complete(prompt: """
        Explain these capacity numbers in two short paragraphs. This is only a numeric snapshot,
        not a diagnosis of a specific job. Do not claim a specific cause for a waiting job.
        Elsewhere's local run command does not automatically migrate work to cloud compute.
        Remote work requires a separate placement request and valid execution permission.
        Do not suggest shell commands, changing permissions, or taking actions. You have no tools.
        \(summary)
        """, config: config)
    }

    /// A tiny round-trip so Settings can confirm the key/endpoint actually work.
    static func test(config: TriageConfig) async -> Result<String, TriageError> {
        guard config.isReady else { return .failure(.notReady) }
        do {
            let reply = try await complete(prompt: "Reply with just the word: OK", config: config)
            return .success(reply.trimmingCharacters(in: .whitespacesAndNewlines))
        } catch let e as TriageError {
            return .failure(e)
        } catch {
            return .failure(.unreachable(error.localizedDescription))
        }
    }

    // MARK: - Prompt

    private static func buildPrompt(system: SystemSnapshot, processes: [PlainProcess]) -> String {
        var programs: [[String: Any]] = []
        for p in processes where p.cpuPercent >= 1 {
            programs.append([
                "id": Int(p.id),
                "name": p.name,
                "whatItIs": p.whatItIs,
                "partOfMacOS": p.isSystem,
                "cpuPercent": Int(p.cpuPercent.rounded()),
                "memory": p.memoryText,
            ])
        }
        let state: [String: Any] = [
            "cpuBusyPercent": Int(system.cpuPercent.rounded()),
            "memoryUsedPercent": Int(system.memoryUsedPercent.rounded()),
            "memoryPressure": system.pressure.rawValue,
            "programs": programs,
        ]
        let json = (try? JSONSerialization.data(withJSONObject: state, options: [.prettyPrinted]))
            .flatMap { String(data: $0, encoding: .utf8) } ?? "{}"

        return """
        You are helping a NON-TECHNICAL person understand why their Mac feels busy and what, if anything, to do — in plain everyday English.

        Here is what's happening right now:
        \(json)

        Recommend 1 to 3 things the person could do. Reply with ONLY a JSON array — no prose, no markdown fences.

        Each item has these fields:
        - "kind": one of "slowDown" (let it keep running but give it less priority — safe, nothing lost), "quit" (close it the normal way), "forceQuit" (stop it immediately — last resort), or "info" (no action, just an explanation).
        - "pid": the program's "id" number from the data above (use null for "info").
        - "label": a short button line using the friendly name, e.g. "Quit Chrome — it's using most of your Mac". Max 70 characters. NEVER show the id number.
        - "reason": 1 to 2 short sentences a complete beginner understands — why it helps and what happens. No jargon, no id numbers, no technical terms.
        - "needsConfirm": true for any real app the person might be using (browser, editor, chat, video call); false only for something clearly stuck or a runaway helper.

        Rules:
        - Prefer "slowDown" over "quit" over "forceQuit". Only suggest force-quit for something clearly frozen.
        - NEVER suggest stopping anything where "partOfMacOS" is true.
        - For search indexing, Photos analysis, or backups: return ONE "info" item saying it finishes on its own and they can just wait.
        - Ignore anything using less than 5 percent CPU.
        - If nothing needs doing, return ONE "info" item reassuring them their Mac is fine.
        """
    }

    // MARK: - Provider calls

    private static func complete(prompt: String, config: TriageConfig) async throws -> String {
        do {
            switch config.provider {
            case .openAI:    return try await callOpenAI(prompt: prompt, config: config)
            case .anthropic: return try await callAnthropic(prompt: prompt, config: config)
            }
        } catch TriageError.http(let code, let body) where code == 404 || code == 400 {
            // The two protocols use different paths, so picking the wrong Service
            // fails with a bare 404 that says nothing useful. Name the likely cause.
            throw TriageError.http(code, body + protocolHint(config))
        }
    }

    /// Spots an endpoint/protocol mismatch — the most common setup mistake.
    private static func protocolHint(_ config: TriageConfig) -> String {
        let looksAnthropic = config.baseURL.lowercased().contains("anthropic")
            || config.model.lowercased().hasPrefix("claude")
        switch config.provider {
        case .openAI where looksAnthropic:
            return "\n\nThis endpoint looks like Claude. Set Service to “Anthropic (Claude)” in Settings."
        case .anthropic where !looksAnthropic:
            return "\n\nThis endpoint doesn't look like Claude. Set Service to “OpenAI-compatible” in Settings."
        default:
            return ""
        }
    }

    private static func callOpenAI(prompt: String, config: TriageConfig) async throws -> String {
        var request = URLRequest(url: chatCompletionsURL(config.baseURL), timeoutInterval: timeout)
        request.httpMethod = "POST"
        request.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "model": config.model,
            "messages": [["role": "user", "content": prompt]],
        ])
        let json = try await send(request)
        guard let choices = json["choices"] as? [[String: Any]],
              let message = choices.first?["message"] as? [String: Any],
              let content = message["content"] as? String else { throw TriageError.badResponse }
        return content
    }

    private static func callAnthropic(prompt: String, config: TriageConfig) async throws -> String {
        let base = config.baseURL.hasSuffix("/") ? String(config.baseURL.dropLast()) : config.baseURL
        guard let url = URL(string: base + "/v1/messages") else { throw TriageError.badResponse }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = "POST"
        request.setValue(config.apiKey, forHTTPHeaderField: "x-api-key")
        request.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "model": config.model,
            "max_tokens": 1024,
            "messages": [["role": "user", "content": prompt]],
        ])
        let json = try await send(request)
        guard let content = json["content"] as? [[String: Any]] else { throw TriageError.badResponse }
        let text = content.compactMap { block -> String? in
            (block["type"] as? String) == "text" ? block["text"] as? String : nil
        }.joined()
        guard !text.isEmpty else { throw TriageError.badResponse }
        return text
    }

    private static func send(_ request: URLRequest) async throws -> [String: Any] {
        let data: Data, response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw TriageError.unreachable(error.localizedDescription)
        }
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw TriageError.http(http.statusCode, String(body.prefix(160)))
        }
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw TriageError.badResponse
        }
        return json
    }

    /// Accepts "https://api.openai.com", ".../v1", or a full ".../chat/completions".
    static func chatCompletionsURL(_ raw: String) -> URL {
        var s = raw.trimmingCharacters(in: .whitespaces)
        if s.hasSuffix("/") { s.removeLast() }
        if s.hasSuffix("/chat/completions") { return URL(string: s) ?? fallback }
        if s.hasSuffix("/v1") { return URL(string: s + "/chat/completions") ?? fallback }
        return URL(string: s + "/v1/chat/completions") ?? fallback
    }
    private static let fallback = URL(string: "https://api.openai.com/v1/chat/completions")!

    // MARK: - Parsing

    private static func parse(_ text: String, allowedPIDs: Set<Int32>) -> [TriageRecommendation] {
        var body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if body.hasPrefix("```") {
            body = body.replacingOccurrences(of: "```json", with: "")
            body = body.replacingOccurrences(of: "```", with: "")
            body = body.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        guard let data = body.data(using: .utf8),
              let array = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return [] }

        var out: [TriageRecommendation] = []
        for item in array {
            guard let kindRaw = item["kind"] as? String,
                  let kind = TriageRecommendation.Kind(rawValue: kindRaw),
                  let label = item["label"] as? String,
                  let reason = item["reason"] as? String else { continue }
            let pid = (item["pid"] as? Int).map { Int32($0) }
            if kind != .info {
                // must point at a real, non-system program we listed
                guard let pid, allowedPIDs.contains(pid) else { continue }
            }
            let needsConfirm = (item["needsConfirm"] as? Bool) ?? true
            out.append(TriageRecommendation(kind: kind, pid: pid, label: label,
                                            reason: reason, needsConfirm: needsConfirm))
            if out.count == 3 { break }
        }
        return out
    }
}
